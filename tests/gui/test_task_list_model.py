from __future__ import annotations

from PySide6.QtCore import Qt

from m3u8_downloader.gui.task_list_model import TaskListModel


def task(task_id: str, state: str = "downloading", completed: int = 2) -> dict:
    return {
        "task_id": task_id,
        "task_name": f"Task {task_id}",
        "filename": f"Task {task_id}.mp4",
        "state": state,
        "completed": completed,
        "total": 10,
        "speed_bps": 1024,
        "route": "直连",
        "error": None,
        "final_path": f"/tmp/{task_id}.mp4",
        "redacted_url": "https://example/media.m3u8?token=%2A%2A%2A",
        "save_root": "/tmp/下载目录",
        "url": "https://user:password@example/media.m3u8?token=real-secret#private",
        "pause_requested": False,
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
        "route",
        "errorText",
        "canPause",
        "canResume",
        "canCancel",
        "canRetry",
        "canOpen",
    }.issubset(names)
    index = model.index(0, 0)
    assert model.data(index, names["taskId"]) == "1"
    assert model.data(index, names["progress"]) == 0.2
    assert model.get(0)["taskName"] == "Task 1"
    assert model.get(0)["taskState"] == "downloading"
    assert model.get(99) == {}
    assert "real-secret" not in repr(model.item(0))
    assert model.data(index, Qt.DisplayRole) == "Task 1"


def test_replace_inserts_updates_moves_and_removes_by_task_id(qtbot) -> None:
    model = TaskListModel()
    model.replace([task("1"), task("2")])
    assert model.rowCount() == 2

    model.replace([task("2", state="completed", completed=10), task("3")])
    assert model.rowCount() == 2
    assert model.item(0)["task_id"] == "2"
    assert model.item(0)["state"] == "completed"
    assert model.item(1)["task_id"] == "3"


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
    }
