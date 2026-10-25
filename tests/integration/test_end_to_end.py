from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from m3u8_downloader.ipc_client import ServiceClient
from m3u8_downloader.manager import TaskManager
from m3u8_downloader.models import AppSettings
from m3u8_downloader.service import ServiceServer
from m3u8_downloader.storage import TaskRepository


def _wait_for_completed(client: ServiceClient, expected: int, timeout: float = 25) -> list[dict]:
    deadline = time.monotonic() + timeout
    latest: list[dict] = []
    while time.monotonic() < deadline:
        latest = client.request("list", {})["tasks"]
        if len(latest) == expected and all(task["state"] == "completed" for task in latest):
            return latest
        failed = [task for task in latest if task["state"] == "failed"]
        if failed:
            raise AssertionError(f"download failed: {failed!r}")
        time.sleep(0.05)
    raise AssertionError(f"tasks did not complete: {latest!r}")


def test_two_clients_share_parallel_tasks_and_receive_playable_named_outputs(
    tmp_path: Path,
    hls_source: str,
    ffmpeg_path: str,
) -> None:
    repository = TaskRepository(tmp_path / "data" / "tasks.sqlite3")
    repository.update_settings(AppSettings(max_active_tasks=2, segment_threads=4, ffmpeg_path=ffmpeg_path))
    manager = TaskManager(repository, tmp_path / "cache" / "workspaces")
    server = ServiceServer(
        manager,
        authkey=b"integration-auth-key-that-is-long-enough",
        address=("127.0.0.1", 0),
        instance_lock_path=tmp_path / "data" / "service.lock",
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    assert server.ready.wait(2)

    terminal = ServiceClient(server.address, server.authkey, client_id="terminal")
    gui = ServiceClient(server.address, server.authkey, client_id="gui")
    events: list[dict] = []
    event_ready = threading.Event()

    def on_event(frame: dict) -> None:
        events.append(frame)
        tasks = frame.get("payload", {}).get("tasks", [])
        if len(tasks) == 2 and all(task["state"] == "completed" for task in tasks):
            event_ready.set()

    subscription = gui.subscribe(on_event)
    save_root = tmp_path / "videos"
    save_root.mkdir()
    names = ["并发任务 A", "并发任务 B"]
    try:
        terminal.request(
            "submit_batch",
            {
                "tasks": [
                    {"url": hls_source, "task_name": name, "save_root": str(save_root), "overwrite": False}
                    for name in names
                ]
            },
            request_id="two-real-media-tasks",
        )
        completed = _wait_for_completed(gui, 2)
        assert event_ready.wait(2), "GUI subscription did not observe the terminal-created tasks"
        assert {task["task_name"] for task in completed} == set(names)
        assert len(terminal.request("list", {})["tasks"]) == 2

        for name in names:
            output = save_root / name / f"{name}.mp4"
            assert output.is_file() and output.stat().st_size > 0
            subprocess.run(
                [ffmpeg_path, "-v", "error", "-i", str(output), "-f", "null", "-"],
                check=True,
                capture_output=True,
            )
        assert not list(save_root.rglob("*.part"))
        assert not list((tmp_path / "cache" / "workspaces").glob("*"))
        assert any(frame.get("event") == "tasks_changed" for frame in events)
    finally:
        subscription.close()
        server.shutdown()
        server_thread.join(timeout=2)
        manager.shutdown()
        repository.close()
