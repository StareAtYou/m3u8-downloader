from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, QUrl
from PySide6.QtTest import QSignalSpy

from m3u8_downloader.gui.bridge import AppBridge, ensure_service_running


class Subscription:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class Client:
    def __init__(self) -> None:
        self.calls = []
        self.callback = None
        self.subscription = Subscription()
        self.disconnect_callback = None
        self.subscribe_count = 0
        self.list_tasks = []

    def request(self, action, payload, request_id=None):
        self.calls.append((action, payload))
        if action == "list":
            return {"tasks": self.list_tasks}
        if action == "get_settings":
            return {"settings": {"default_save_dir": "/tmp", "max_active_tasks": 3, "close_behavior": "shutdown"}}
        if action == "update_settings":
            return {"settings": payload}
        if action == "submit":
            return {"tasks": [{"task_id": "new-task"}]}
        return {"task": {"task_id": payload.get("task_id", "")}}

    def subscribe(self, callback, on_disconnect=None):
        self.callback = callback
        self.disconnect_callback = on_disconnect
        self.subscribe_count += 1
        self.subscription = Subscription()
        return self.subscription


def snapshot() -> dict:
    return {
        "task_id": "1",
        "task_name": "Movie",
        "filename": "Movie.mp4",
        "state": "downloading",
        "completed": 1,
        "total": 2,
        "speed_bps": 1024,
        "route": "直连",
        "error": None,
        "final_path": "/tmp/Movie.mp4",
        "redacted_url": "https://example/a.m3u8",
        "pause_requested": False,
    }


def test_subscription_delivery_mutates_model_on_main_qt_thread(qtbot) -> None:
    client = Client()
    bridge = AppBridge(client)
    delivered_threads = []
    bridge.tasksApplied.connect(lambda: delivered_threads.append(QThread.currentThread()))
    bridge.start()
    qtbot.waitUntil(lambda: client.callback is not None and any(action == "list" for action, _ in client.calls))
    qtbot.wait(20)
    delivered_threads.clear()

    thread = threading.Thread(
        target=lambda: client.callback({"type": "event", "event": "tasks_changed", "payload": {"tasks": [snapshot()]}})
    )
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: bridge.tasks.rowCount() == 1)

    assert delivered_threads
    assert all(thread == bridge.thread() for thread in delivered_threads)
    bridge.close()
    assert client.subscription.closed is True


def test_preview_submit_overwrite_controls_and_settings_are_async(qtbot) -> None:
    client = Client()
    bridge = AppBridge(client)
    assert bridge.previewFilename("Bad:/Name") == "Bad__Name.mp4"

    spy = QSignalSpy(bridge.requestSucceeded)
    bridge.submitTask("https://example/a.m3u8", "Movie", "/tmp", True)
    qtbot.waitUntil(lambda: spy.count() > 0, timeout=1000)
    assert client.calls[-1] == (
        "submit",
        {"url": "https://example/a.m3u8", "task_name": "Movie", "save_root": "/tmp", "overwrite": True},
    )

    bridge.controlTask("pause", "task-1")
    qtbot.waitUntil(lambda: client.calls[-1][0] == "pause")
    bridge.loadSettings()
    qtbot.waitUntil(
        lambda: (
            client.calls[-1][0] == "get_settings"
            and bridge.defaultSaveDir == "/tmp"
            and bridge.closeBehavior == "shutdown"
        )
    )
    bridge.saveSettings({"default_save_dir": "/videos", "max_active_tasks": 2})
    qtbot.waitUntil(lambda: client.calls[-1][0] == "update_settings")
    bridge.close()


def test_open_output_folder_uses_platform_url_and_close_does_not_shutdown_service(tmp_path: Path) -> None:
    client = Client()
    opened: list[QUrl] = []
    bridge = AppBridge(client, url_opener=lambda url: opened.append(url) or True)
    output = tmp_path / "Movie.mp4"

    assert bridge.openOutputFolder(str(output)) is True
    assert opened[0].toLocalFile() == str(tmp_path)
    bridge.close()
    assert not any(action == "shutdown" for action, _ in client.calls)


def test_local_path_from_url_preserves_spaces_and_chinese_characters(tmp_path: Path) -> None:
    bridge = AppBridge(Client())
    folder = tmp_path / "下载 目录"

    assert bridge.localPathFromUrl(QUrl.fromLocalFile(str(folder))) == str(folder)
    bridge.close()


def test_copy_text_uses_injected_clipboard_writer() -> None:
    copied: list[str] = []
    bridge = AppBridge(Client(), clipboard_writer=copied.append)

    bridge.copyText("https://example.com/video.m3u8?token=%2A%2A%2A")

    assert copied == ["https://example.com/video.m3u8?token=%2A%2A%2A"]
    bridge.close()


def test_ensure_service_running_attaches_or_starts(monkeypatch) -> None:
    sentinel = object()
    calls = []
    monkeypatch.setattr(
        "m3u8_downloader.gui.bridge.connect_or_start",
        lambda factory, starter: calls.append((factory, starter)) or sentinel,
    )
    assert ensure_service_running() is sentinel
    assert len(calls) == 1


def test_bridge_reconnects_subscription_and_refreshes_snapshot(qtbot) -> None:
    client = Client()
    bridge = AppBridge(client)
    bridge.start()
    qtbot.waitUntil(lambda: client.subscribe_count == 1)
    client.list_tasks = [snapshot()]

    client.disconnect_callback()

    qtbot.waitUntil(lambda: client.subscribe_count >= 2, timeout=2000)
    qtbot.waitUntil(lambda: bridge.tasks.rowCount() == 1, timeout=2000)
    bridge.close()
