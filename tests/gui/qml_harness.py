from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl, qInstallMessageHandler
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from m3u8_downloader.gui.bridge import AppBridge

QML_ROOT = Path(__file__).parents[2] / "src" / "m3u8_downloader" / "gui" / "qml"


class Subscription:
    def close(self) -> None:
        pass


class StaticClient:
    def __init__(self, tasks: list[dict] | None = None) -> None:
        self.tasks = list(tasks or [])

    def request(self, action, payload, request_id=None):
        if action == "list":
            return {"tasks": self.tasks}
        if action == "get_settings":
            return {"settings": {}}
        return {"tasks": self.tasks}

    def subscribe(self, callback, on_disconnect=None):
        return Subscription()


def six_tasks() -> list[dict]:
    states = [
        ("downloading", 109, 402, 8.6 * 1024**2, "本地代理", None),
        ("waiting_merge", 180, 180, 0, "本地代理", None),
        ("queued", 0, 260, 0, "检测中", None),
        ("paused", 72, 300, 0, "直连", None),
        ("failed", 16, 240, 0, "直连", "分片请求失败"),
        ("completed", 128, 128, 0, "直连", None),
    ]
    names = [
        "风起长安 第02集",
        "周末音乐会 2026",
        "极其漫长的中文任务名称用于验证表格截断不会挤压操作按钮和其他重要信息",
        "产品发布会回放",
        "旅行纪录片 第01集",
        "城市夜景延时摄影",
    ]
    tasks = []
    for index, (state, completed, total, speed, route, error) in enumerate(states, start=1):
        name = names[index - 1]
        tasks.append(
            {
                "task_id": str(index),
                "task_name": name,
                "filename": f"{name}.mp4",
                "state": state,
                "completed": completed,
                "total": total,
                "speed_bps": speed,
                "route": route,
                "error": error,
                "final_path": f"/tmp/层级很深的输出目录/节目归档/2026/十月/{name}.mp4",
                "redacted_url": (
                    "https://user:%2A%2A%2A@cdn.example.com/video.m3u8?token=%2A%2A%2A#redacted"
                    if index == 3
                    else f"https://cdn.example.com/{index}.m3u8"
                ),
                "save_root": "/tmp/层级很深的输出目录/节目归档/2026/十月",
                "url": (
                    "https://real-user:real-password@cdn.example.com/video.m3u8?token=real-token#private"
                    if index == 3
                    else f"https://cdn.example.com/{index}.m3u8"
                ),
            }
        )
    return tasks


def demo_tasks() -> list[dict]:
    return six_tasks()


def one_task() -> list[dict]:
    return six_tasks()[:1]


def many_tasks(count: int = 30) -> list[dict]:
    seeds = six_tasks()
    return [
        {
            **seeds[index % len(seeds)],
            "task_id": f"many-{index:02d}",
            "task_name": f"{seeds[index % len(seeds)]['task_name']} #{index + 1:02d}",
        }
        for index in range(count)
    ]


def load_qml(qtbot, tasks: list[dict] | None = None, width: int = 1440, height: int = 1024):
    QGuiApplication.instance().setFont(QFont("Arial"))
    snapshots = demo_tasks() if tasks is None else tasks
    bridge = AppBridge(StaticClient(snapshots))
    bridge.tasks.replace(snapshots)
    warnings: list[str] = []
    old_handler = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
    assert engine.rootObjects(), "Main.qml did not load"
    root = engine.rootObjects()[0]
    root.setWidth(width)
    root.setHeight(height)
    qtbot.wait(20)
    qInstallMessageHandler(old_handler)
    return engine, root, bridge, warnings
