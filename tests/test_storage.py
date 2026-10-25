import os
from pathlib import Path

import pytest

from m3u8_downloader.models import AppSettings, OverwritePolicy, TaskState
from m3u8_downloader.storage import TaskRepository


def create_task(repository: TaskRepository, task_id: str = "task-1"):
    return repository.create_task(
        task_id=task_id,
        url="https://media.example/video.m3u8?token=private",
        task_name="演示",
        filename="演示.mp4",
        save_root="/tmp/videos",
        workspace=f"/tmp/work/{task_id}",
        final_path="/tmp/videos/演示/演示.mp4",
        overwrite_policy=OverwritePolicy.REJECT,
    )


def test_creates_schema_and_round_trips_private_and_public_records(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    created = create_task(repository)

    assert repository.schema_version == 1
    assert repository.get_private(created.task_id).url.endswith("token=private")
    assert repository.get_snapshot(created.task_id).redacted_url.endswith("token=%2A%2A%2A")
    if os.name != "nt":
        assert (tmp_path / "tasks.sqlite3").stat().st_mode & 0o077 == 0


def test_rolls_back_explicit_transaction(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")

    with pytest.raises(RuntimeError), repository.transaction():
        create_task(repository)
        raise RuntimeError("rollback")

    assert repository.list_snapshots() == []


def test_recovers_active_tasks_as_interrupted(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    task = create_task(repository)
    repository.update_state(task.task_id, TaskState.PROBING)

    recovered = repository.recover_interrupted()

    assert [record.state for record in recovered] == [TaskState.INTERRUPTED]
    assert repository.get_private(task.task_id).state == TaskState.INTERRUPTED


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
