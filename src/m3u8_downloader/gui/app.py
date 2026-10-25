from __future__ import annotations

import os
import sys
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .bridge import AppBridge, ensure_service_running


def qml_path() -> Path:
    package_path = Path(__file__).parent / "qml" / "Main.qml"
    if package_path.is_file():
        return package_path
    bundled_path = Path(sys.executable).resolve().parent / "gui" / "qml" / "Main.qml"
    return bundled_path


def _create_tray(app: QApplication, window, bridge: AppBridge) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(qta.icon("fa6s.download", color="#1593ff"), app)
    menu = QMenu()
    show_action = QAction("显示主窗口", menu)
    pause_action = QAction("暂停全部", menu)
    quit_action = QAction("退出", menu)
    show_action.triggered.connect(window.show)
    pause_action.triggered.connect(bridge.pauseAll)
    quit_action.triggered.connect(app.quit)
    menu.addAction(show_action)
    menu.addAction(pause_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda _: window.show())
    tray.show()
    return tray


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QApplication(sys.argv)
    app.setApplicationName("M3U8 Downloader Pro")
    app.setOrganizationName("M3U8 Downloader Pro")
    app.setWindowIcon(qta.icon("fa6s.download", color="#1593ff"))
    bridge = AppBridge(ensure_service_running())
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(qml_path())))
    if not engine.rootObjects():
        bridge.close()
        return 1
    window = engine.rootObjects()[0]
    tray = _create_tray(app, window, bridge)
    window.setProperty("trayAvailable", tray is not None)
    app.setQuitOnLastWindowClosed(tray is None)
    app.aboutToQuit.connect(bridge.close)
    # Retain references for the complete application lifetime.
    app._m3u8_engine = engine  # type: ignore[attr-defined]
    app._m3u8_bridge = bridge  # type: ignore[attr-defined]
    app._m3u8_tray = tray  # type: ignore[attr-defined]
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
