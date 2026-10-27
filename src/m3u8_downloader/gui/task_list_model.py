from __future__ import annotations

from enum import IntEnum
from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QByteArray, QModelIndex, Qt, Signal, Slot

from ..terminal_view import STATE_LABELS


class TaskRole(IntEnum):
    TASK_ID = Qt.UserRole + 1
    TASK_NAME = Qt.UserRole + 2
    FILENAME = Qt.UserRole + 3
    STATE = Qt.UserRole + 4
    STATE_LABEL = Qt.UserRole + 5
    PROGRESS = Qt.UserRole + 6
    COMPLETED = Qt.UserRole + 7
    TOTAL = Qt.UserRole + 8
    SPEED_TEXT = Qt.UserRole + 9
    ROUTE = Qt.UserRole + 10
    ERROR_TEXT = Qt.UserRole + 11
    FINAL_PATH = Qt.UserRole + 12
    CAN_PAUSE = Qt.UserRole + 13
    CAN_RESUME = Qt.UserRole + 14
    CAN_CANCEL = Qt.UserRole + 15
    CAN_RETRY = Qt.UserRole + 16
    CAN_OPEN = Qt.UserRole + 17
    REDACTED_URL = Qt.UserRole + 18
    SAVE_ROOT = Qt.UserRole + 19


ROLE_NAMES = {
    TaskRole.TASK_ID: b"taskId",
    TaskRole.TASK_NAME: b"taskName",
    TaskRole.FILENAME: b"filename",
    TaskRole.STATE: b"taskState",
    TaskRole.STATE_LABEL: b"stateLabel",
    TaskRole.PROGRESS: b"progress",
    TaskRole.COMPLETED: b"completed",
    TaskRole.TOTAL: b"total",
    TaskRole.SPEED_TEXT: b"speedText",
    TaskRole.ROUTE: b"route",
    TaskRole.ERROR_TEXT: b"errorText",
    TaskRole.FINAL_PATH: b"finalPath",
    TaskRole.CAN_PAUSE: b"canPause",
    TaskRole.CAN_RESUME: b"canResume",
    TaskRole.CAN_CANCEL: b"canCancel",
    TaskRole.CAN_RETRY: b"canRetry",
    TaskRole.CAN_OPEN: b"canOpen",
    TaskRole.REDACTED_URL: b"redactedUrl",
    TaskRole.SAVE_ROOT: b"saveRoot",
}

_SAFE_FIELDS = {
    "task_id",
    "task_name",
    "filename",
    "state",
    "completed",
    "total",
    "speed_bps",
    "route",
    "error",
    "final_path",
    "redacted_url",
    "save_root",
    "pause_requested",
}

_ROOT_INDEX = QModelIndex()


def _speed(value: float) -> str:
    if value <= 0:
        return "—"
    if value < 1024:
        return f"{value:.0f} B/s"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB/s"
    return f"{value / 1024**2:.1f} MB/s"


class TaskListModel(QAbstractListModel):
    countChanged = Signal()
    completedCountChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return {int(role): QByteArray(name) for role, name in ROLE_NAMES.items()}

    def rowCount(self, parent=_ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self._items)

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._items)

    @Property(int, notify=completedCountChanged)
    def completedCount(self) -> int:
        return sum(item.get("state") == "completed" for item in self._items)

    def item(self, row: int) -> dict[str, Any]:
        return dict(self._items[row])

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, Any]:
        if not 0 <= row < len(self._items):
            return {}
        index = self.index(row, 0)
        return {bytes(name).decode("utf-8"): self.data(index, int(role)) for role, name in ROLE_NAMES.items()}

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        if role == Qt.DisplayRole:
            return item.get("task_name", "")
        state = str(item.get("state", ""))
        values = {
            TaskRole.TASK_ID: item.get("task_id", ""),
            TaskRole.TASK_NAME: item.get("task_name", ""),
            TaskRole.FILENAME: item.get("filename", ""),
            TaskRole.STATE: state,
            TaskRole.STATE_LABEL: STATE_LABELS.get(state, state),
            TaskRole.PROGRESS: min(1.0, int(item.get("completed", 0)) / max(1, int(item.get("total", 0)))),
            TaskRole.COMPLETED: int(item.get("completed", 0)),
            TaskRole.TOTAL: int(item.get("total", 0)),
            TaskRole.SPEED_TEXT: _speed(float(item.get("speed_bps", 0) or 0)),
            TaskRole.ROUTE: item.get("route") or "检测中",
            TaskRole.ERROR_TEXT: item.get("error") or "",
            TaskRole.FINAL_PATH: item.get("final_path") or "",
            TaskRole.REDACTED_URL: item.get("redacted_url") or "",
            TaskRole.SAVE_ROOT: item.get("save_root") or "",
            TaskRole.CAN_PAUSE: state in {"queued", "probing", "parsing", "downloading", "waiting_merge"},
            TaskRole.CAN_RESUME: state == "paused",
            TaskRole.CAN_CANCEL: state
            in {"queued", "probing", "parsing", "downloading", "paused", "waiting_merge", "interrupted"},
            TaskRole.CAN_RETRY: state in {"failed", "canceled", "interrupted"},
            TaskRole.CAN_OPEN: state == "completed",
        }
        try:
            return values[TaskRole(role)]
        except (KeyError, ValueError):
            return None

    def replace(self, snapshots: list[dict[str, Any]]) -> None:
        safe = [{key: value for key, value in snapshot.items() if key in _SAFE_FIELDS} for snapshot in snapshots]
        old_completed_count = self.completedCount
        old_task_ids = [item.get("task_id") for item in self._items]
        new_task_ids = [item.get("task_id") for item in safe]
        if old_task_ids == new_task_ids:
            changed_rows = [row for row, (old, new) in enumerate(zip(self._items, safe, strict=True)) if old != new]
            if not changed_rows:
                return
            self._items = safe
            changed_roles = [int(role) for role in ROLE_NAMES]
            range_start = previous_row = changed_rows[0]
            for row in changed_rows[1:]:
                if row != previous_row + 1:
                    self.dataChanged.emit(self.index(range_start, 0), self.index(previous_row, 0), changed_roles)
                    range_start = row
                previous_row = row
            self.dataChanged.emit(self.index(range_start, 0), self.index(previous_row, 0), changed_roles)
            if self.completedCount != old_completed_count:
                self.completedCountChanged.emit()
            return

        self.beginResetModel()
        self._items = safe
        self.endResetModel()
        self.countChanged.emit()
        if self.completedCount != old_completed_count:
            self.completedCountChanged.emit()
