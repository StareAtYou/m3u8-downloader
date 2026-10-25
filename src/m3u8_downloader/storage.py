from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    AppSettings,
    OverwritePolicy,
    TaskRecord,
    TaskSnapshot,
    TaskState,
    validate_transition,
)

_ACTIVE_STATES = (
    TaskState.PROBING,
    TaskState.PARSING,
    TaskState.DOWNLOADING,
    TaskState.WAITING_MERGE,
    TaskState.MERGING,
    TaskState.CANCELING,
)


class TaskRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self._migrate()
        if os.name != "nt":
            self.database_path.chmod(0o600)

    @property
    def schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def _migrate(self) -> None:
        if self.schema_version >= 1:
            return
        self._connection.executescript(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                task_name TEXT NOT NULL,
                filename TEXT NOT NULL,
                save_root TEXT NOT NULL,
                workspace TEXT NOT NULL,
                final_path TEXT NOT NULL,
                overwrite_policy TEXT NOT NULL,
                state TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                speed_bps REAL NOT NULL DEFAULT 0,
                route TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                pause_requested INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX tasks_state_idx ON tasks(state);
            CREATE UNIQUE INDEX tasks_active_output_idx ON tasks(final_path)
                WHERE state NOT IN ('completed', 'canceled', 'failed');
            CREATE TABLE settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                value TEXT NOT NULL
            );
            CREATE TABLE idempotency (
                client_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                response TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(client_id, request_id)
            );
            PRAGMA user_version = 1;
            """
        )
        self._connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        outermost = self._transaction_depth == 0
        if outermost:
            self._connection.execute("BEGIN IMMEDIATE")
        self._transaction_depth += 1
        try:
            yield
        except BaseException:
            self._transaction_depth -= 1
            if outermost:
                self._connection.rollback()
            raise
        else:
            self._transaction_depth -= 1
            if outermost:
                self._connection.commit()

    def _commit_if_needed(self) -> None:
        if self._transaction_depth == 0:
            self._connection.commit()

    def create_task(self, **values: Any) -> TaskRecord:
        record = TaskRecord.new(**values)
        self._connection.execute(
            """
            INSERT INTO tasks (
                task_id, url, task_name, filename, save_root, workspace, final_path,
                overwrite_policy, state, completed, total, speed_bps, route, error,
                created_at, updated_at, pause_requested
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.task_id,
                record.url,
                record.task_name,
                record.filename,
                record.save_root,
                record.workspace,
                record.final_path,
                record.overwrite_policy.value,
                record.state.value,
                record.completed,
                record.total,
                record.speed_bps,
                record.route,
                record.error,
                record.created_at,
                record.updated_at,
                int(record.pause_requested),
            ),
        )
        self._commit_if_needed()
        return record

    def get_private(self, task_id: str) -> TaskRecord:
        row = self._connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._record_from_row(row)

    def get_snapshot(self, task_id: str) -> TaskSnapshot:
        return self.get_private(task_id).to_snapshot()

    def list_snapshots(self) -> list[TaskSnapshot]:
        rows = self._connection.execute("SELECT * FROM tasks ORDER BY created_at, task_id").fetchall()
        return [self._record_from_row(row).to_snapshot() for row in rows]

    def update_state(self, task_id: str, target: TaskState, *, error: str | None = None) -> TaskRecord:
        current = self.get_private(task_id)
        validate_transition(current.state, target)
        self._connection.execute(
            "UPDATE tasks SET state = ?, error = ?, updated_at = ? WHERE task_id = ?",
            (target.value, error, _now(), task_id),
        )
        self._commit_if_needed()
        return self.get_private(task_id)

    def apply_worker_event(self, task_id: str, target: TaskState, payload: Mapping[str, Any]) -> TaskRecord:
        current = self.get_private(task_id)
        validate_transition(current.state, target)
        updates: dict[str, Any] = {
            "state": target.value,
            "updated_at": _now(),
        }
        for key in ("completed", "total", "speed_bps", "route", "error"):
            if key in payload:
                updates[key] = payload[key]
        if target is TaskState.FAILED and "error" not in updates:
            updates["error"] = "下载任务失败"
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self._connection.execute(
            f"UPDATE tasks SET {assignments} WHERE task_id = ?",
            (*updates.values(), task_id),
        )
        self._commit_if_needed()
        return self.get_private(task_id)

    def set_pause_requested(self, task_id: str, requested: bool) -> TaskRecord:
        self._connection.execute(
            "UPDATE tasks SET pause_requested = ?, updated_at = ? WHERE task_id = ?",
            (int(requested), _now(), task_id),
        )
        self._commit_if_needed()
        return self.get_private(task_id)

    def recover_interrupted(self) -> list[TaskRecord]:
        placeholders = ",".join("?" for _ in _ACTIVE_STATES)
        rows = self._connection.execute(
            f"SELECT task_id FROM tasks WHERE state IN ({placeholders})",
            tuple(state.value for state in _ACTIVE_STATES),
        ).fetchall()
        if not rows:
            return []
        now = _now()
        self._connection.execute(
            f"UPDATE tasks SET state = ?, updated_at = ? WHERE state IN ({placeholders})",
            (TaskState.INTERRUPTED.value, now, *(state.value for state in _ACTIVE_STATES)),
        )
        self._commit_if_needed()
        return [self.get_private(row["task_id"]) for row in rows]

    def get_settings(self) -> AppSettings:
        row = self._connection.execute("SELECT value FROM settings WHERE singleton = 1").fetchone()
        if row is None:
            return AppSettings()
        return AppSettings(**json.loads(row["value"])).validate()

    def update_settings(self, settings: AppSettings) -> None:
        settings.validate()
        self._connection.execute(
            "INSERT INTO settings(singleton, value) VALUES(1, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET value = excluded.value",
            (json.dumps(asdict(settings), ensure_ascii=False, sort_keys=True),),
        )
        self._commit_if_needed()

    def remember_request(self, client_id: str, request_id: str, response: Mapping[str, Any]) -> None:
        encoded = json.dumps(dict(response), ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("幂等响应过大")
        self._connection.execute(
            "INSERT OR IGNORE INTO idempotency(client_id, request_id, response, created_at) VALUES(?, ?, ?, ?)",
            (client_id, request_id, encoded, _now()),
        )
        self._commit_if_needed()

    def recall_request(self, client_id: str, request_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT response FROM idempotency WHERE client_id = ? AND request_id = ?",
            (client_id, request_id),
        ).fetchone()
        return None if row is None else json.loads(row["response"])

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            url=row["url"],
            task_name=row["task_name"],
            filename=row["filename"],
            save_root=row["save_root"],
            workspace=row["workspace"],
            final_path=row["final_path"],
            overwrite_policy=OverwritePolicy(row["overwrite_policy"]),
            state=TaskState(row["state"]),
            completed=row["completed"],
            total=row["total"],
            speed_bps=row["speed_bps"],
            route=row["route"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            pause_requested=bool(row["pause_requested"]),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
