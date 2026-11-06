from __future__ import annotations

import math

import pytest
from PySide6.QtCore import Qt

from m3u8_downloader.gui.task_list_model import TaskListModel


def task(
    task_id: str,
    state: str = "downloading",
    completed: int = 2,
    *,
    eta_seconds: object = 45,
    auto_retry_count: int = 0,
    next_retry_at: str | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "task_name": f"Task {task_id}",
        "filename": f"Task {task_id}.mp4",
        "state": state,
        "completed": completed,
        "total": 10,
        "speed_bps": 1024,
        "eta_seconds": eta_seconds,
        "route": "直连",
        "error": None,
        "final_path": f"/tmp/{task_id}.mp4",
        "redacted_url": "https://example/media.m3u8?token=%2A%2A%2A",
        "save_root": "/tmp/下载目录",
        "url": "https://user:password@example/media.m3u8?token=real-secret#private",
        "pause_requested": False,
        "auto_retry_count": auto_retry_count,
        "next_retry_at": next_retry_at,
    }


def roles(model: TaskListModel) -> dict[str, int]:
    return {bytes(name).decode(): role for role, name in model.roleNames().items()}


def test_snapshot_roles_are_display_safe_and_complete(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1")])
    names = roles(model)

    assert {
        "taskId",
        "taskName",
        "filename",
        "taskState",
        "stateLabel",
        "progress",
        "speedText",
        "etaText",
        "route",
        "errorText",
        "canPause",
        "canResume",
        "canCancel",
        "canRetry",
        "canOpen",
        "canDelete",
    }.issubset(names)
    index = model.index(0, 0)
    assert model.data(index, names["taskId"]) == "1"
    assert model.data(index, names["progress"]) == 0.2
    assert model.data(index, names["etaText"]) == "约 45 秒"
    assert model.get(0)["taskName"] == "Task 1"
    assert model.get(0)["taskState"] == "downloading"
    assert model.get(99) == {}
    assert "real-secret" not in repr(model.item(0))
    assert model.data(index, Qt.DisplayRole) == "Task 1"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (45, "约 45 秒"),
        (180, "约 3 分钟"),
        (7200, "约 2 小时"),
        (7500, "约 2 小时 5 分钟"),
    ],
)
def test_eta_text_formats_download_estimates(seconds: float, expected: str) -> None:
    model = TaskListModel()
    model.replace([task("1", eta_seconds=seconds)])

    assert model.get(0)["etaText"] == expected


@pytest.mark.parametrize("value", [None, -1, math.nan, math.inf, "soon", True])
def test_eta_text_rejects_unreliable_values(value: object) -> None:
    model = TaskListModel()
    model.replace([task("1", eta_seconds=value)])
    assert model.get(0)["etaText"] == "—"

    model.replace([task("1", state="paused", eta_seconds=45)])
    assert model.get(0)["etaText"] == "—"


def test_retry_wait_state_label_uses_persisted_attempt_count() -> None:
    model = TaskListModel()
    model.replace(
        [
            task(
                "waiting",
                state="failed",
                auto_retry_count=2,
                next_retry_at="2026-11-06T13:00:00+00:00",
            ),
            task("exhausted", state="failed", auto_retry_count=3),
        ]
    )

    assert model.get(0)["stateLabel"] == "等待重试 2/3"
    assert model.get(1)["stateLabel"] == "失败"


def test_replace_inserts_updates_moves_and_removes_by_task_id(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1"), task("2")])
    assert model.rowCount() == 2

    model.replace([task("2", state="completed", completed=10), task("3")])
    assert model.rowCount() == 2
    assert model.item(0)["task_id"] == "2"
    assert model.item(0)["state"] == "completed"
    assert model.item(1)["task_id"] == "3"


def test_replace_updates_stable_task_rows_without_resetting_the_model(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1"), task("2")])
    changes = []
    resets = []
    counts = []
    model.dataChanged.connect(
        lambda first, last, changed_roles: changes.append((first.row(), last.row(), set(changed_roles)))
    )
    model.modelReset.connect(lambda: resets.append(True))
    model.countChanged.connect(lambda: counts.append(True))

    model.replace([task("1", completed=7), task("2")])

    assert changes == [(0, 0, set(roles(model).values()))]
    assert resets == []
    assert counts == []
    assert model.item(0)["completed"] == 7


def test_replace_identical_snapshot_emits_no_refresh_signals(qtbot) -> None:
    model = TaskListModel()
    snapshot = [task("1"), task("2")]
    model.replace(snapshot)
    changes = []
    resets = []
    counts = []
    model.dataChanged.connect(lambda *_: changes.append(True))
    model.modelReset.connect(lambda: resets.append(True))
    model.countChanged.connect(lambda: counts.append(True))

    model.replace(snapshot)

    assert changes == []
    assert resets == []
    assert counts == []


def test_stable_state_change_notifies_completed_count_without_count_change(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1"), task("2")])
    completed_counts = []
    counts = []
    model.completedCountChanged.connect(lambda: completed_counts.append(model.completedCount))
    model.countChanged.connect(lambda: counts.append(True))

    model.replace([task("1", state="completed", completed=10), task("2")])

    assert completed_counts == [1]
    assert counts == []


def test_bulk_action_counts_and_delete_eligibility_follow_task_states(qtbot) -> None:
    model = TaskListModel()
    model.replace(
        [
            task("1", state="downloading"),
            task("2", state="paused"),
            task("3", state="completed", completed=10),
        ]
    )
    pausable_changes = []
    paused_changes = []
    model.pausableCountChanged.connect(lambda: pausable_changes.append(model.pausableCount))
    model.pausedCountChanged.connect(lambda: paused_changes.append(model.pausedCount))

    assert model.pausableCount == 1
    assert model.pausedCount == 1
    assert model.get(0)["canDelete"] is False
    assert model.get(1)["canDelete"] is True
    assert model.get(2)["canDelete"] is True

    model.replace(
        [
            task("1", state="paused"),
            task("2", state="paused"),
            task("3", state="completed", completed=10),
        ]
    )

    assert pausable_changes == [0]
    assert paused_changes == [2]
    assert model.pausableCount == 0
    assert model.pausedCount == 2


def test_replace_changed_task_identity_uses_structural_reset(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1"), task("2")])
    changes = []
    resets = []
    counts = []
    model.dataChanged.connect(lambda *_: changes.append(True))
    model.modelReset.connect(lambda: resets.append(True))
    model.countChanged.connect(lambda: counts.append(True))

    model.replace([task("2"), task("3")])

    assert changes == []
    assert resets == [True]
    assert counts == [True]


def test_safe_location_roles_and_completed_count_update_on_replace(qtbot) -> None:
    model = TaskListModel()
    with qtbot.waitSignal(model.countChanged):
        model.replace([task("1"), task("2", state="completed", completed=10)])

    assert model.completedCount == 1
    assert model.get(0)["redactedUrl"] == "https://example/media.m3u8?token=%2A%2A%2A"
    assert model.get(0)["saveRoot"] == "/tmp/下载目录"

    with qtbot.waitSignal(model.countChanged):
        model.replace([task("3", state="completed", completed=10), task("4", state="completed", completed=10)])

    assert model.count == 2
    assert model.completedCount == 2


def test_full_url_fields_never_enter_presentation_roles(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1")])

    assert "url" not in model.item(0)
    assert "password" not in repr(model.item(0))
    assert "real-secret" not in repr(model.get(0))
    assert set(model.get(0)) == {
        "taskId",
        "taskName",
        "filename",
        "taskState",
        "stateLabel",
        "progress",
        "completed",
        "total",
        "speedText",
        "etaText",
        "route",
        "errorText",
        "finalPath",
        "redactedUrl",
        "saveRoot",
        "canPause",
        "canResume",
        "canCancel",
        "canRetry",
        "canOpen",
        "canDelete",
    }
