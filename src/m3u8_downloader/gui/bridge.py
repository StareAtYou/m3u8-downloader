from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import qtawesome as qta
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from ..cli import DEFAULT_ADDRESS, connect_or_start, spawn_service
from ..config import AppPaths
from ..ipc_client import ServiceClient
from ..naming import sanitize_task_name
from ..service import load_or_create_auth_key
from .task_list_model import TaskListModel


def ensure_service_running() -> ServiceClient:
    paths = AppPaths.from_platform()
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    authkey = load_or_create_auth_key(paths.config_dir / "service.key")
    return connect_or_start(lambda: ServiceClient(DEFAULT_ADDRESS, authkey), spawn_service)


class AppBridge(QObject):
    tasksApplied = Signal()
    requestSucceeded = Signal(str, object)
    requestFailed = Signal(str, str)
    settingsLoaded = Signal(object)
    defaultSaveDirChanged = Signal()
    closeBehaviorChanged = Signal()
    connectionStateChanged = Signal(bool)
    _eventReceived = Signal(object)
    _resultReceived = Signal(str, object)
    _errorReceived = Signal(str, str)

    def __init__(self, client: Any, *, url_opener=None, clipboard_writer=None, parent=None) -> None:
        super().__init__(parent)
        qta.icon("fa6s.download")
        self.client = client
        self._tasks = TaskListModel(self)
        self._default_save_dir = str(Path.home() / "Downloads")
        self._close_behavior = "tray"
        self._subscription = None
        self._closing = threading.Event()
        self._disconnected = threading.Event()
        self._started = False
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="gui-ipc")
        self._url_opener = url_opener or QDesktopServices.openUrl
        self._clipboard_writer = clipboard_writer or self._write_system_clipboard
        self._eventReceived.connect(self._apply_event)
        self._resultReceived.connect(self._apply_result)
        self._errorReceived.connect(self.requestFailed)

    @Property(QObject, constant=True)
    def tasks(self) -> TaskListModel:
        return self._tasks

    @Property(str, notify=defaultSaveDirChanged)
    def defaultSaveDir(self) -> str:
        return self._default_save_dir

    @Property(str, notify=closeBehaviorChanged)
    def closeBehavior(self) -> str:
        return self._close_behavior

    @Property(str, constant=True)
    def iconFontFamily(self) -> str:
        return "Font Awesome 6 Free Solid"

    @Slot(str, result=str)
    def iconGlyph(self, name: str) -> str:
        icons = {
            "download": "fa6s.download",
            "check": "fa6s.circle-check",
            "settings": "fa6s.gear",
            "folder": "fa6s.folder",
            "pause": "fa6s.pause",
            "play": "fa6s.play",
            "retry": "fa6s.rotate-right",
            "cancel": "fa6s.xmark",
            "more": "fa6s.ellipsis-vertical",
            "clock": "fa6s.clock",
            "copy": "fa6s.copy",
            "tray": "fa6s.window-restore",
            "quit": "fa6s.power-off",
            "plus": "fa6s.plus",
            "minus": "fa6s.minus",
            "checkmark": "fa6s.check",
            "chevron-down": "fa6s.chevron-down",
        }
        return qta.charmap(icons.get(name, "fa6s.circle"))

    @Slot()
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._executor.submit(self._connection_loop)

    def _connection_loop(self) -> None:
        delay = 0.2
        while not self._closing.is_set():
            self._disconnected.clear()
            try:
                self._subscription = self.client.subscribe(self._eventReceived.emit, self._on_disconnect)
                result = self.client.request("list", {})
                self._eventReceived.emit({"payload": result})
                settings = self.client.request("get_settings", {})
                self._resultReceived.emit("get_settings", settings)
                self.connectionStateChanged.emit(True)
                delay = 0.2
                while not self._closing.is_set() and not self._disconnected.wait(0.2):
                    pass
            except Exception as exc:  # noqa: BLE001 - isolate IPC failures from the Qt event loop
                self.connectionStateChanged.emit(False)
                self._errorReceived.emit("connect", str(exc))
            finally:
                subscription, self._subscription = self._subscription, None
                if subscription is not None:
                    subscription.close()
            if not self._closing.is_set():
                self._closing.wait(delay)
                delay = min(delay * 2, 3.0)

    def _on_disconnect(self) -> None:
        self.connectionStateChanged.emit(False)
        self._disconnected.set()

    @Slot(object)
    def _apply_event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        payload = event.get("payload", {})
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if isinstance(tasks, list):
            self._tasks.replace(tasks)
            self.tasksApplied.emit()

    def _request(self, action: str, payload: dict[str, Any]) -> None:
        def run() -> None:
            try:
                result = self.client.request(action, payload)
            except Exception as exc:  # noqa: BLE001 - errors cross into UI as text signals
                self._errorReceived.emit(action, str(exc))
            else:
                self._resultReceived.emit(action, result)

        self._executor.submit(run)

    @Slot(str, object)
    def _apply_result(self, action: str, result: object) -> None:
        if action == "get_settings" and isinstance(result, dict):
            settings = result.get("settings", {})
            if isinstance(settings, dict):
                default_dir = str(settings.get("default_save_dir") or self._default_save_dir)
                if default_dir != self._default_save_dir:
                    self._default_save_dir = default_dir
                    self.defaultSaveDirChanged.emit()
                close_behavior = str(settings.get("close_behavior") or self._close_behavior)
                if close_behavior != self._close_behavior:
                    self._close_behavior = close_behavior
                    self.closeBehaviorChanged.emit()
                self.settingsLoaded.emit(settings)
        elif action == "update_settings" and isinstance(result, dict):
            settings = result.get("settings", {})
            if isinstance(settings, dict):
                default_dir = str(settings.get("default_save_dir") or self._default_save_dir)
                if default_dir != self._default_save_dir:
                    self._default_save_dir = default_dir
                    self.defaultSaveDirChanged.emit()
                close_behavior = str(settings.get("close_behavior") or self._close_behavior)
                if close_behavior != self._close_behavior:
                    self._close_behavior = close_behavior
                    self.closeBehaviorChanged.emit()
        self.requestSucceeded.emit(action, result)

    @Slot(str, result=str)
    def previewFilename(self, name: str) -> str:
        try:
            return f"{sanitize_task_name(name)}.mp4"
        except ValueError:
            return "请输入有效任务名称"

    @Slot(QUrl, result=str)
    def localPathFromUrl(self, url: QUrl) -> str:
        return url.toLocalFile()

    @staticmethod
    def _write_system_clipboard(text: str) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            app.clipboard().setText(text)

    @Slot(str)
    def copyText(self, text: str) -> None:
        self._clipboard_writer(text)

    @Slot(str, str, str, bool)
    def submitTask(self, url: str, task_name: str, save_root: str, overwrite: bool) -> None:
        self._request(
            "submit",
            {"url": url, "task_name": task_name, "save_root": save_root, "overwrite": overwrite},
        )

    @Slot("QVariantList", str, bool, result=bool)
    def submitBatch(self, tasks: list[Any], save_root: str, overwrite: bool) -> bool:
        prepared = []
        try:
            for task in tasks:
                if not isinstance(task, dict):
                    raise TypeError("批量任务格式无效")
                url = str(task.get("url", "")).strip()
                name = sanitize_task_name(str(task.get("task_name", "")))
                if not url:
                    raise ValueError("批量任务 URL 不能为空")
                prepared.append({"url": url, "task_name": name, "save_root": save_root, "overwrite": overwrite})
        except (TypeError, ValueError) as exc:
            self.requestFailed.emit("submit_batch", str(exc))
            return False
        self._request("submit_batch", {"tasks": prepared})
        return True

    @Slot(str, str)
    def controlTask(self, action: str, task_id: str) -> None:
        if action not in {"pause", "resume", "cancel", "retry"}:
            self.requestFailed.emit(action, "不支持的任务操作")
            return
        self._request(action, {"task_id": task_id})

    @Slot()
    def pauseAll(self) -> None:
        self._request("pause_all", {})

    @Slot()
    def loadSettings(self) -> None:
        self._request("get_settings", {})

    @Slot("QVariantMap")
    def saveSettings(self, settings: dict[str, Any]) -> None:
        self._request("update_settings", dict(settings))

    @Slot(str, result=bool)
    def openOutputFolder(self, final_path: str) -> bool:
        return bool(self._url_opener(QUrl.fromLocalFile(str(Path(final_path).parent))))

    @Slot()
    def close(self) -> None:
        self._closing.set()
        self._disconnected.set()
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None
        self._executor.shutdown(wait=False, cancel_futures=True)
