from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_GUI = REPO_ROOT / "tests" / "gui"
DEFAULT_REFERENCE = REPO_ROOT / "tests" / "fixtures" / "gui" / "m3u8-desktop-dark-control-center.png"
if str(TEST_GUI) not in sys.path:
    sys.path.insert(0, str(TEST_GUI))

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication
from qml_harness import QML_ROOT, StaticClient, six_tasks

from m3u8_downloader.gui.bridge import AppBridge


def _visual_descendants(item: QQuickItem, object_name: str) -> list[QQuickItem]:
    matches: list[QQuickItem] = []
    for child in item.childItems():
        if child.objectName() == object_name:
            matches.append(child)
        matches.extend(_visual_descendants(child, object_name))
    return matches


def _process_events(rounds: int = 12) -> None:
    for _ in range(rounds):
        QGuiApplication.processEvents()


def _save_image(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"无法保存截图：{path}")


def _stack_images(top: QImage, bottom: QImage) -> QImage:
    output = QImage(max(top.width(), bottom.width()), top.height() + bottom.height(), QImage.Format.Format_RGB32)
    output.fill(QColor("#081018"))
    painter = QPainter(output)
    painter.drawImage(0, 0, top)
    painter.drawImage(0, top.height(), bottom)
    painter.end()
    return output


def _geometry(item: QQuickItem) -> tuple[int, int, int, int]:
    point = item.mapToScene(QPointF(0, 0))
    return (round(point.x()), round(point.y()), round(item.width()), round(item.height()))


def capture_ui_reference(
    *,
    output: Path,
    reference: Path,
    comparison_output: Path,
    detail_comparison_output: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    if not reference.is_file():
        raise FileNotFoundError(f"设计基准不存在：{reference}")
    if width <= 0 or height <= 0:
        raise ValueError("截图尺寸必须为正数")

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([])
    app.setFont(QFont("Arial"))

    tasks = six_tasks()
    client = StaticClient(tasks)
    bridge = AppBridge(client)
    bridge.tasks.replace(tasks)
    warnings: list[str] = []
    old_handler = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_ROOT / "Main.qml")))
    if not engine.rootObjects():
        qInstallMessageHandler(old_handler)
        bridge.close()
        raise RuntimeError("Main.qml 无法加载")

    root = engine.rootObjects()[0]
    root.setWidth(width)
    root.setHeight(height)
    _process_events()
    task_table = root.findChild(QQuickItem, "taskTable")
    table_viewport = root.findChild(QQuickItem, "tableViewport")
    if task_table is None or table_viewport is None:
        qInstallMessageHandler(old_handler)
        bridge.close()
        raise RuntimeError("任务表格未创建")
    task_table.setProperty("currentIndex", 1)
    _process_events()

    implementation = root.grabWindow()
    if (implementation.width(), implementation.height()) != (width, height):
        qInstallMessageHandler(old_handler)
        bridge.close()
        raise RuntimeError(f"截图尺寸错误：{implementation.width()}×{implementation.height()}，预期 {width}×{height}")
    _save_image(implementation, output)

    source = QImage(str(reference))
    if source.isNull():
        qInstallMessageHandler(old_handler)
        bridge.close()
        raise RuntimeError(f"无法读取设计基准：{reference}")
    normalized_source = source.scaled(
        width,
        height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _save_image(_stack_images(normalized_source, implementation), comparison_output)

    detail_top = round(height * 0.68)
    source_detail = normalized_source.copy(0, detail_top, width, height - detail_top)
    implementation_detail = implementation.copy(0, detail_top, width, height - detail_top)
    _save_image(_stack_images(source_detail, implementation_detail), detail_comparison_output)

    rows = _visual_descendants(table_viewport, "taskRow")
    state_badges = _visual_descendants(table_viewport, "stateBadge")
    route_badges = _visual_descendants(table_viewport, "routeBadge")
    tracked_names = (
        "urlInput",
        "taskNameInput",
        "saveInput",
        "addTaskButton",
        "batchAddButton",
        "tableViewport",
        "detailPanel",
        "logPanel",
    )
    geometry = {
        name: _geometry(item) for name in tracked_names if (item := root.findChild(QQuickItem, name)) is not None
    }
    geometry["rows"] = tuple(_geometry(row) for row in rows)

    result = {
        "row_count": len(rows),
        "current_index": int(task_table.property("currentIndex")),
        "state_tones": {str(badge.property("tone")) for badge in state_badges},
        "route_tones": {str(badge.property("tone")) for badge in route_badges},
        "fixture_only": isinstance(client, StaticClient),
        "warnings": warnings,
        "geometry": geometry,
    }

    root.close()
    root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _process_events(2)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _process_events(2)
    bridge.close()
    qInstallMessageHandler(old_handler)
    if warnings:
        raise RuntimeError("QML warnings:\n" + "\n".join(warnings))

    if owns_app:
        app.quit()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture deterministic M3U8 desktop UI visual evidence")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference", default=DEFAULT_REFERENCE, type=Path)
    parser.add_argument("--comparison-output", required=True, type=Path)
    parser.add_argument("--detail-comparison-output", required=True, type=Path)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    capture_ui_reference(
        output=args.output,
        reference=args.reference,
        comparison_output=args.comparison_output,
        detail_comparison_output=args.detail_comparison_output,
        width=args.width,
        height=args.height,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
