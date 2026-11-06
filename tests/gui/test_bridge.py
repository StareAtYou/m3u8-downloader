from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, QUrl

from m3u8_downloader.gui.bridge import AppBridge, ensure_service_running
from m3u8_downloader.ipc_client import ServiceError


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
            return {
                "settings": {
                    "default_save_dir": "/tmp",
                    "max_active_tasks": 3,
                    "close_behavior": "shutdown",
                    "overwrite_existing": True,
                }
            }
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


class BlockingConflictClient(Client):
    def __init__(self) -> None:
        super().__init__()
        self.alpha_started = threading.Event()
        self.release_alpha = threading.Event()

    def request(self, action, payload, request_id=None):
        self.calls.append((action, payload))
        if action == "submit" and payload.get("task_name") == "Alpha" and not payload.get("overwrite"):
            self.alpha_started.set()
            self.release_alpha.wait(2)
            raise ServiceError("file_exists", "目标文件已存在")
        if action == "submit":
            return {"tasks": [{"task_id": "new-task"}]}
        return super().request(action, payload, request_id)


class BlockingSettingsClient(Client):
    def __init__(self) -> None:
        super().__init__()
        self.settings_requested = threading.Event()
        self.release_settings = threading.Event()

    def request(self, action, payload, request_id=None):
        if action == "get_settings":
            self.calls.append((action, payload))
            self.settings_requested.set()
            self.release_settings.wait(2)
            return {
                "settings": {
                    "default_save_dir": "/configured",
                    "overwrite_existing": True,
                }
            }
        return super().request(action, payload, request_id)


class FailingControlClient(Client):
    def request(self, action, payload, request_id=None):
        if action == "pause":
            raise ServiceError("invalid_request", "无法暂停")
        return super().request(action, payload, request_id)


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

    bridge.loadSettings()
    qtbot.waitUntil(lambda: bridge.defaultSaveDir == "/tmp" and bridge.overwriteExisting is True)
    bridge.submitTask("https://example/a.m3u8", "Movie")
    qtbot.waitUntil(lambda: client.calls[-1][0] == "submit", timeout=1000)
    assert client.calls[-1] == (
        "submit",
        {"url": "https://example/a.m3u8", "task_name": "Movie", "save_root": "/tmp", "overwrite": True},
    )

    assert bridge.submitBatch([{"url": "https://example/b.m3u8", "task_name": "Episode"}]) is True
    qtbot.waitUntil(lambda: client.calls[-1][0] == "submit_batch")
    assert client.calls[-1] == (
        "submit_batch",
        {
            "tasks": [
                {
                    "url": "https://example/b.m3u8",
                    "task_name": "Episode",
                    "save_root": "/tmp",
                    "overwrite": True,
                }
            ]
        },
    )

    bridge._apply_result(
        "get_settings",
        {"settings": {"default_save_dir": "/videos", "overwrite_existing": False}},
    )
    bridge.submitTaskWithOverwrite("https://example/override.m3u8", "Override")
    qtbot.waitUntil(lambda: client.calls[-1][0] == "submit")
    assert client.calls[-1][1] == {
        "url": "https://example/override.m3u8",
        "task_name": "Override",
        "save_root": "/videos",
        "overwrite": True,
    }

    bridge.controlTask("pause", "task-1")
    qtbot.waitUntil(lambda: client.calls[-1][0] == "pause")
    bridge.pauseAll()
    qtbot.waitUntil(lambda: client.calls[-1] == ("pause_all", {}))
    bridge.resumeAll()
    qtbot.waitUntil(lambda: client.calls[-1] == ("resume_all", {}))
    bridge.deleteTask("task-1", False)
    qtbot.waitUntil(lambda: client.calls[-1] == ("delete_task", {"task_id": "task-1", "delete_files": False}))
    bridge.deleteTask("task-2", True)
    qtbot.waitUntil(lambda: client.calls[-1] == ("delete_task", {"task_id": "task-2", "delete_files": True}))
    bridge.saveSettings({"default_save_dir": "/videos", "max_active_tasks": 2})
    qtbot.waitUntil(lambda: client.calls[-1][0] == "update_settings")
    bridge.close()


def test_submit_waits_for_settings_and_empty_saved_directory_uses_downloads(qtbot) -> None:
    client = BlockingSettingsClient()
    bridge = AppBridge(client)
    bridge.submitTask("https://example/early.m3u8", "Early")
    assert client.settings_requested.wait(1)
    assert not any(action == "submit" for action, _payload in client.calls)

    client.release_settings.set()
    qtbot.waitUntil(lambda: any(action == "submit" for action, _payload in client.calls))
    assert client.calls[-1][1]["save_root"] == "/configured"
    assert client.calls[-1][1]["overwrite"] is True

    bridge._apply_result(
        "update_settings",
        {"settings": {"default_save_dir": "", "overwrite_existing": False}},
    )
    assert bridge.defaultSaveDir == str(Path.home() / "Downloads")
    bridge.submitTask("https://example/fallback.m3u8", "Fallback")
    qtbot.waitUntil(lambda: client.calls[-1][1].get("task_name") == "Fallback")
    assert client.calls[-1][1]["save_root"] == str(Path.home() / "Downloads")
    bridge.close()


def test_file_conflict_carries_immutable_submission_context(qtbot) -> None:
    client = BlockingConflictClient()
    bridge = AppBridge(client)
    bridge._apply_result(
        "get_settings",
        {"settings": {"default_save_dir": "/alpha-root", "overwrite_existing": False}},
    )
    failures = []
    bridge.requestFailedDetailed.connect(
        lambda action, code, message, context: failures.append((action, code, message, context))
    )

    bridge.submitTask("https://example/alpha.m3u8", "Alpha")
    assert client.alpha_started.wait(1)
    bridge._apply_result(
        "update_settings",
        {"settings": {"default_save_dir": "/beta-root", "overwrite_existing": False}},
    )
    bridge.submitTask("https://example/beta.m3u8", "Beta")
    qtbot.waitUntil(
        lambda: any(payload.get("task_name") == "Beta" for action, payload in client.calls if action == "submit")
    )
    client.release_alpha.set()
    qtbot.waitUntil(lambda: bool(failures))

    action, code, _message, context = failures[0]
    assert (action, code) == ("submit", "file_exists")
    assert context == {
        "url": "https://example/alpha.m3u8",
        "task_name": "Alpha",
        "save_root": "/alpha-root",
        "overwrite": False,
    }
    bridge.submitTaskWithOverwrite(context["url"], context["task_name"], context["save_root"])
    qtbot.waitUntil(lambda: client.calls[-1][1].get("overwrite") is True)
    assert client.calls[-1][1] == {**context, "overwrite": True}
    bridge.close()


def test_non_submission_failure_uses_an_empty_detail_context(qtbot) -> None:
    bridge = AppBridge(FailingControlClient())
    failures = []
    bridge.requestFailedDetailed.connect(
        lambda action, code, message, context: failures.append((action, code, message, context))
    )

    bridge.controlTask("pause", "task-1")
    qtbot.waitUntil(lambda: bool(failures))

    assert failures == [("pause", "invalid_request", "无法暂停", {})]
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
