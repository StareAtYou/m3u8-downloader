import math
import os
import sqlite3
from pathlib import Path

import pytest

from m3u8_downloader import storage
from m3u8_downloader.models import AppSettings, OverwritePolicy, TaskState
from m3u8_downloader.storage import TaskRepository


def create_task(repository: TaskRepository, task_id: str = "task-1"):
    return repository.create_task(
        task_id=task_id,
        url="https://media.example/video.m3u8?token=private",
        task_name="演示",
        filename=f"演示-{task_id}.mp4",
        save_root="/tmp/videos",
        workspace=f"/tmp/work/{task_id}",
        final_path=f"/tmp/videos/演示/{task_id}.mp4",
        overwrite_policy=OverwritePolicy.REJECT,
    )


def test_creates_schema_and_round_trips_private_and_public_records(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    created = create_task(repository)

    assert repository.schema_version == 2
    assert repository.get_private(created.task_id).url.endswith("token=private")
    assert repository.get_snapshot(created.task_id).redacted_url.endswith("token=%2A%2A%2A")
    assert repository.get_snapshot(created.task_id).auto_retry_count == 0
    assert repository.get_snapshot(created.task_id).next_retry_at is None
    assert repository.get_snapshot(created.task_id).eta_seconds is None
    if os.name != "nt":
        assert (tmp_path / "tasks.sqlite3").stat().st_mode & 0o077 == 0


def test_migrates_v1_database_without_losing_existing_task(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, url TEXT NOT NULL, task_name TEXT NOT NULL,
            filename TEXT NOT NULL, save_root TEXT NOT NULL, workspace TEXT NOT NULL,
            final_path TEXT NOT NULL, overwrite_policy TEXT NOT NULL, state TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
            speed_bps REAL NOT NULL DEFAULT 0, route TEXT NOT NULL DEFAULT '', error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            pause_requested INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX tasks_state_idx ON tasks(state);
        CREATE UNIQUE INDEX tasks_active_output_idx ON tasks(final_path)
            WHERE state NOT IN ('completed', 'canceled', 'failed');
        CREATE TABLE settings (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), value TEXT NOT NULL);
        CREATE TABLE idempotency (
            client_id TEXT NOT NULL, request_id TEXT NOT NULL, response TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(client_id, request_id)
        );
        INSERT INTO tasks VALUES (
            'legacy', 'https://example/legacy.m3u8?token=private', 'Legacy', 'Legacy.mp4',
            '/videos', '/work/legacy', '/videos/Legacy/Legacy.mp4', 'reject', 'failed',
            3, 10, 512.0, '直连', '旧错误',
            '2026-11-01T00:00:00+00:00', '2026-11-01T01:00:00+00:00', 0
        );
        PRAGMA user_version = 1;
        """
    )
    connection.commit()
    connection.close()

    repository = TaskRepository(database)
    migrated = repository.get_private("legacy")

    assert repository.schema_version == 2
    assert migrated.url.endswith("token=private")
    assert migrated.state is TaskState.FAILED
    assert (migrated.completed, migrated.total, migrated.error) == (3, 10, "旧错误")
    assert (migrated.auto_retry_count, migrated.next_retry_at, migrated.eta_seconds) == (0, None, None)


def test_interrupted_v1_migration_rolls_back_every_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "tasks.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY, url TEXT NOT NULL, task_name TEXT NOT NULL,
            filename TEXT NOT NULL, save_root TEXT NOT NULL, workspace TEXT NOT NULL,
            final_path TEXT NOT NULL, overwrite_policy TEXT NOT NULL, state TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
            speed_bps REAL NOT NULL DEFAULT 0, route TEXT NOT NULL DEFAULT '', error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            pause_requested INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE settings (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), value TEXT NOT NULL);
        CREATE TABLE idempotency (
            client_id TEXT NOT NULL, request_id TEXT NOT NULL, response TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(client_id, request_id)
        );
        PRAGMA user_version = 1;
        """
    )
    connection.close()
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def interrupted_connect(*args, **kwargs):
        candidate = real_connect(*args, **kwargs)
        alter_count = 0

        def authorizer(action, _first, _second, _database, _trigger):
            nonlocal alter_count
            if action == sqlite3.SQLITE_ALTER_TABLE:
                alter_count += 1
                if alter_count == 2:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        candidate.set_authorizer(authorizer)
        opened.append(candidate)
        return candidate

    monkeypatch.setattr(storage.sqlite3, "connect", interrupted_connect)
    with pytest.raises(sqlite3.DatabaseError):
        TaskRepository(database)
    for candidate in opened:
        candidate.close()
    monkeypatch.setattr(storage.sqlite3, "connect", real_connect)

    check = real_connect(database)
    columns = [row[1] for row in check.execute("PRAGMA table_info(tasks)")]
    version = check.execute("PRAGMA user_version").fetchone()[0]
    check.close()
    assert version == 1
    assert "auto_retry_count" not in columns

    assert TaskRepository(database).schema_version == 2


def test_retry_metadata_orders_due_tasks_and_can_activate_or_reset(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    first = create_task(repository, "task-a")
    second = create_task(repository, "task-b")
    repository._connection.execute("UPDATE tasks SET created_at = ?", ("2026-11-01T00:00:00+00:00",))
    repository._connection.commit()
    for task in (first, second):
        repository.update_state(task.task_id, TaskState.FAILED, error="temporary")
    repository.schedule_retry(second.task_id, "2026-11-06T12:00:00+00:00")
    repository.schedule_retry(first.task_id, "2026-11-06T12:00:00+00:00")

    assert [item.task_id for item in repository.list_due_retries("2026-11-06T12:00:00+00:00")] == [
        first.task_id,
        second.task_id,
    ]
    activated = repository.activate_scheduled_retry(first.task_id)
    assert activated.state is TaskState.QUEUED
    assert activated.auto_retry_count == 1
    assert activated.next_retry_at is None
    assert activated.error is None

    reset = repository.clear_retry_schedule(second.task_id, reset_count=True)
    assert reset.state is TaskState.FAILED
    assert reset.auto_retry_count == 0
    assert reset.next_retry_at is None


def test_worker_eta_persists_only_finite_non_negative_values(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    task = create_task(repository)
    repository.apply_worker_event(task.task_id, TaskState.PROBING, {})
    repository.apply_worker_event(task.task_id, TaskState.PARSING, {})
    repository.apply_worker_event(task.task_id, TaskState.DOWNLOADING, {"eta_seconds": 12.5})
    assert repository.get_snapshot(task.task_id).eta_seconds == 12.5

    for invalid in (-1, math.nan, math.inf, "soon", True):
        repository.apply_worker_event(task.task_id, TaskState.DOWNLOADING, {"eta_seconds": invalid})
        assert repository.get_snapshot(task.task_id).eta_seconds is None


def test_rolls_back_explicit_transaction(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")

    with pytest.raises(RuntimeError), repository.transaction():
        create_task(repository)
        raise RuntimeError("rollback")

    assert repository.list_snapshots() == []


def test_lists_newest_first_with_deterministic_tie_break_and_oldest_on_request(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    create_task(repository, "task-a")
    create_task(repository, "task-b")
    repository._connection.execute("UPDATE tasks SET created_at = ?", ("2026-11-03T12:00:00+00:00",))
    repository._connection.commit()

    assert [item.task_id for item in repository.list_snapshots()] == ["task-b", "task-a"]
    assert [item.task_id for item in repository.list_snapshots(newest_first=False)] == ["task-a", "task-b"]


def test_recovers_active_tasks_as_interrupted(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    task = create_task(repository)
    repository.update_state(task.task_id, TaskState.PROBING)

    recovered = repository.recover_interrupted()

    assert [record.state for record in recovered] == [TaskState.INTERRUPTED]
    assert repository.get_private(task.task_id).state == TaskState.INTERRUPTED


def test_delete_task_removes_only_the_requested_record(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    create_task(repository, "task-a")
    create_task(repository, "task-b")

    repository.delete_task("task-a")

    with pytest.raises(KeyError):
        repository.get_private("task-a")
    assert repository.get_private("task-b").task_id == "task-b"
    with pytest.raises(KeyError):
        repository.delete_task("missing")


def test_validates_and_persists_settings(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    assert repository.get_settings() == AppSettings()

    updated = AppSettings(max_active_tasks=5, segment_threads=24, theme="light")
    repository.update_settings(updated)

    reopened = TaskRepository(tmp_path / "tasks.sqlite3")
    assert reopened.get_settings() == updated
    with pytest.raises(ValueError):
        reopened.update_settings(AppSettings(segment_threads=0))


def test_persists_idempotent_response_across_reopen(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(database)
    response = {"task_id": "task-1", "created": True}
    repository.remember_request("client-a", "request-a", response)
    repository.close()

    reopened = TaskRepository(database)
    assert reopened.recall_request("client-a", "request-a") == response
    assert reopened.recall_request("client-a", "other") is None
