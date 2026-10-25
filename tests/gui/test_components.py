from __future__ import annotations

import os
from pathlib import Path
from xml.etree import ElementTree

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

from m3u8_downloader.gui.bridge import AppBridge

QML_ROOT = Path(__file__).parents[2] / "src" / "m3u8_downloader" / "gui" / "qml"


class Client:
    def request(self, action, payload, request_id=None):
        return {"tasks": []}


def load_component(name: str):
    QGuiApplication.instance().setFont(QFont("Arial"))
    engine = QQmlEngine()
    bridge = AppBridge(Client())
    engine.rootContext().setContextProperty("bridge", bridge)
    warnings: list[str] = []
    old_handler = qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_ROOT / "components" / name)))
    instance = component.create()
    qInstallMessageHandler(old_handler)
    assert component.errors() == []
    assert instance is not None
    return engine, bridge, component, instance, warnings


def test_form_controls_have_deterministic_surfaces_and_focus_tokens(qtbot) -> None:
    for filename in ("StyledTextField.qml", "StyledTextArea.qml", "StyledComboBox.qml", "StyledSpinBox.qml"):
        engine, bridge, component, control, warnings = load_component(filename)
        assert warnings == [], filename
        assert control.property("surfaceColor") == QColor("#182432")
        assert control.property("normalBorderColor") == QColor("#273747")
        assert control.property("focusBorderColor") == QColor("#1593ff")
        if filename == "StyledTextField.qml":
            assert control.property("implicitHeight") == 48
        bridge.close()
        del control, component, engine


def test_buttons_checkbox_status_progress_and_empty_state_contracts(qtbot) -> None:
    for filename in ("PrimaryButton.qml", "SecondaryButton.qml"):
        engine, bridge, component, button, warnings = load_component(filename)
        assert warnings == []
        assert button.property("implicitHeight") == 50
        bridge.close()
        del button, component, engine

    engine, bridge, component, checkbox, warnings = load_component("StyledCheckBox.qml")
    indicator = checkbox.findChild(object, "customCheckIndicator")
    assert warnings == []
    assert indicator is not None
    assert indicator.property("width") == 20
    assert indicator.property("height") == 20
    bridge.close()
    del checkbox, component, engine

    engine, bridge, component, badge, warnings = load_component("StatusBadge.qml")
    assert warnings == []
    expected = {
        "blue": "#1593ff",
        "green": "#58dc73",
        "amber": "#ffbb44",
        "purple": "#b989ff",
        "red": "#ff6b7a",
        "muted": "#9db0c5",
    }
    for tone, color in expected.items():
        badge.setProperty("tone", tone)
        assert badge.property("toneColor") == QColor(color)
    bridge.close()
    del badge, component, engine

    engine, bridge, component, progress, warnings = load_component("ProgressTrack.qml")
    assert warnings == []
    progress.setProperty("progress", -0.25)
    assert progress.property("normalizedProgress") == 0.0
    progress.setProperty("progress", 1.25)
    assert progress.property("normalizedProgress") == 1.0
    bridge.close()
    del progress, component, engine

    engine, bridge, component, empty, warnings = load_component("EmptyState.qml")
    assert warnings == []
    empty.setProperty("title", "暂无任务")
    empty.setProperty("message", "添加一个下载任务")
    assert empty.property("title") == "暂无任务"
    assert empty.property("message") == "添加一个下载任务"
    bridge.close()
    del empty, component, engine


def test_all_shared_components_are_packaged_in_qrc() -> None:
    qrc = QML_ROOT.parent / "resources.qrc"
    packaged = {node.text for node in ElementTree.parse(qrc).findall(".//file")}
    expected = {
        f"qml/components/{name}.qml"
        for name in (
            "StyledTextField",
            "StyledTextArea",
            "StyledComboBox",
            "StyledSpinBox",
            "SecondaryButton",
            "StyledCheckBox",
            "StatusBadge",
            "ProgressTrack",
            "EmptyState",
        )
    }
    assert expected <= packaged
