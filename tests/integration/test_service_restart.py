from __future__ import annotations

import time
from pathlib import Path

from m3u8_downloader.manager import TaskManager
from m3u8_downloader.models import AppSettings, TaskState
from m3u8_downloader.storage import TaskRepository


def _drain_until(manager: TaskManager, task_id: str, target: TaskState, timeout: float = 25) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        manager.drain_worker_events()
        snapshot = manager.get(task_id)
        if snapshot.state is target:
            return
        if snapshot.state is TaskState.FAILED:
            raise AssertionError(f"resumed task failed: {snapshot!r}")
        time.sleep(0.05)
    raise AssertionError(f"task did not reach {target}: {manager.get(task_id)!r}")


def test_restart_marks_active_task_interrupted_and_retry_ignores_stale_part(
    tmp_path: Path,
    hls_source: str,
    ffmpeg_path: str,
) -> None:
    database = tmp_path / "data" / "tasks.sqlite3"
    workspace_root = tmp_path / "cache" / "workspaces"
    save_root = tmp_path / "videos"
    save_root.mkdir()

    first_repository = TaskRepository(database)
    first_repository.update_settings(AppSettings(max_active_tasks=1, segment_threads=3, ffmpeg_path=ffmpeg_path))
    first_manager = TaskManager(first_repository, workspace_root, auto_schedule=False)
    snapshot = first_manager.submit(hls_source, "断点恢复任务", save_root)
    first_repository.update_state(snapshot.task_id, TaskState.PROBING)
    first_repository.update_state(snapshot.task_id, TaskState.PARSING)
    first_repository.update_state(snapshot.task_id, TaskState.DOWNLOADING)
    workspace = Path(first_repository.get_private(snapshot.task_id).workspace)
    workspace.mkdir(parents=True)
    stale_part = workspace / "000000.ts.part"
    stale_part.write_bytes(b"incomplete-data-must-not-be-merged")
    first_manager.shutdown(timeout=0)
    first_repository.close()

    second_repository = TaskRepository(database)
    second_manager = TaskManager(second_repository, workspace_root)
    try:
        interrupted = second_manager.get(snapshot.task_id)
        assert interrupted.state is TaskState.INTERRUPTED
        assert stale_part.exists()
        second_manager.retry(snapshot.task_id)
        _drain_until(second_manager, snapshot.task_id, TaskState.COMPLETED)

        output = save_root / "断点恢复任务" / "断点恢复任务.mp4"
        assert output.is_file() and output.stat().st_size > 0
        assert not workspace.exists()
        assert not list(save_root.rglob("*.part"))
    finally:
        second_manager.shutdown()
        second_repository.close()
