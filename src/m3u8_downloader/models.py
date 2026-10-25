from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .privacy import redact_url


class TaskState(StrEnum):
    QUEUED = "queued"
    PROBING = "probing"
    PARSING = "parsing"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    WAITING_MERGE = "waiting_merge"
    MERGING = "merging"
    COMPLETED = "completed"
    CANCELING = "canceling"
    CANCELED = "canceled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class OverwritePolicy(StrEnum):
    REJECT = "reject"
    OVERWRITE = "overwrite"


LEGAL_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.QUEUED: frozenset({TaskState.PROBING, TaskState.PAUSED, TaskState.CANCELING, TaskState.FAILED}),
    TaskState.PROBING: frozenset({TaskState.PARSING, TaskState.PAUSED, TaskState.CANCELING, TaskState.FAILED}),
    TaskState.PARSING: frozenset({TaskState.DOWNLOADING, TaskState.PAUSED, TaskState.CANCELING, TaskState.FAILED}),
    TaskState.DOWNLOADING: frozenset(
        {TaskState.PAUSED, TaskState.WAITING_MERGE, TaskState.CANCELING, TaskState.FAILED}
    ),
    TaskState.PAUSED: frozenset({TaskState.QUEUED, TaskState.CANCELING}),
    TaskState.WAITING_MERGE: frozenset({TaskState.MERGING, TaskState.PAUSED, TaskState.CANCELING, TaskState.FAILED}),
    TaskState.MERGING: frozenset({TaskState.COMPLETED, TaskState.CANCELING, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.CANCELING: frozenset({TaskState.CANCELED, TaskState.FAILED}),
    TaskState.CANCELED: frozenset({TaskState.QUEUED}),
    TaskState.FAILED: frozenset({TaskState.QUEUED}),
    TaskState.INTERRUPTED: frozenset({TaskState.QUEUED, TaskState.CANCELING}),
}


def validate_transition(current: TaskState, target: TaskState) -> None:
    if current == target:
        return
    if target not in LEGAL_TRANSITIONS[current]:
        raise ValueError(f"非法任务状态转换: {current.value} -> {target.value}")


@dataclass(frozen=True)
class AppSettings:
    default_save_dir: str = ""
    max_active_tasks: int = 3
    segment_threads: int = 16
    proxy_policy: str = "auto"
    manual_proxy: str | None = None
    ffmpeg_path: str = "ffmpeg"
    theme: str = "dark"
    close_behavior: str = "tray"

    def validate(self) -> AppSettings:
        if not 1 <= self.max_active_tasks <= 16:
            raise ValueError("同时下载任务数必须在 1 到 16 之间")
        if not 1 <= self.segment_threads <= 64:
            raise ValueError("分片线程数必须在 1 到 64 之间")
        if self.proxy_policy not in {"auto", "direct", "manual"}:
            raise ValueError("无效的代理策略")
        if self.proxy_policy == "manual":
            if not self.manual_proxy:
                raise ValueError("手动代理策略必须提供本地代理地址")
            from .network import parse_manual_proxy

            parse_manual_proxy(self.manual_proxy)
        if self.theme not in {"system", "dark", "light"}:
            raise ValueError("无效的界面主题")
        if self.close_behavior not in {"tray", "shutdown"}:
            raise ValueError("无效的关闭行为")
        return self


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    redacted_url: str
    task_name: str
    filename: str
    save_root: str
    workspace: str
    final_path: str
    overwrite_policy: OverwritePolicy
    state: TaskState
    completed: int
    total: int
    speed_bps: float
    route: str
    error: str | None
    created_at: str
    updated_at: str
    pause_requested: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["overwrite_policy"] = self.overwrite_policy.value
        data["state"] = self.state.value
        return data


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    state: TaskState
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "state": self.state.value, "payload": dict(self.payload)}


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    url: str
    task_name: str
    filename: str
    save_root: str
    workspace: str
    final_path: str
    overwrite_policy: OverwritePolicy
    state: TaskState
    completed: int = 0
    total: int = 0
    speed_bps: float = 0.0
    route: str = ""
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    pause_requested: bool = False

    @classmethod
    def new(cls, **values: Any) -> TaskRecord:
        now = datetime.now(UTC).isoformat()
        return cls(state=TaskState.QUEUED, created_at=now, updated_at=now, **values)

    def to_snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=self.task_id,
            redacted_url=redact_url(self.url),
            task_name=self.task_name,
            filename=self.filename,
            save_root=self.save_root,
            workspace=self.workspace,
            final_path=self.final_path,
            overwrite_policy=self.overwrite_policy,
            state=self.state,
            completed=self.completed,
            total=self.total,
            speed_bps=self.speed_bps,
            route=self.route,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
            pause_requested=self.pause_requested,
        )

    def event(self, state: TaskState, payload: Mapping[str, Any] | None = None) -> TaskEvent:
        safe_payload = dict(payload or {})
        sensitive_keys = {"url", "key", "password", "token", "secret"}
        if any(str(key).lower() in sensitive_keys for key in safe_payload):
            raise ValueError("事件负载包含敏感字段")
        return TaskEvent(task_id=self.task_id, state=state, payload=safe_payload)
