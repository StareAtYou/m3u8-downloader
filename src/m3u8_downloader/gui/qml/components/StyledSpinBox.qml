import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

SpinBox {
    id: control
    property color surfaceColor: AppTheme.Theme.surfaceRaised
    property color normalBorderColor: AppTheme.Theme.border
    property color focusBorderColor: AppTheme.Theme.focus
    implicitHeight: AppTheme.Theme.controlHeight
    editable: true
    font.pixelSize: AppTheme.Theme.bodySize
    contentItem: TextInput {
        z: 2
        text: control.textFromValue(control.value, control.locale)
        color: AppTheme.Theme.text
        selectionColor: AppTheme.Theme.blueSoft
        selectedTextColor: AppTheme.Theme.text
        horizontalAlignment: Qt.AlignLeft
        verticalAlignment: Qt.AlignVCenter
        leftPadding: 14
        rightPadding: 78
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly
    }
    up.indicator: Rectangle {
        x: control.width - width
        width: 38
        height: control.height / 2
        color: control.up.pressed ? AppTheme.Theme.surfacePressed : control.up.hovered ? AppTheme.Theme.surfaceHover : "transparent"
        Icon { anchors.centerIn: parent; name: "plus"; color: AppTheme.Theme.muted; font.pixelSize: 11 }
    }
    down.indicator: Rectangle {
        x: control.width - width
        y: control.height / 2
        width: 38
        height: control.height / 2
        color: control.down.pressed ? AppTheme.Theme.surfacePressed : control.down.hovered ? AppTheme.Theme.surfaceHover : "transparent"
        Icon { anchors.centerIn: parent; name: "minus"; color: AppTheme.Theme.muted; font.pixelSize: 11 }
    }
    background: Rectangle {
        radius: AppTheme.Theme.radius
        color: control.enabled ? control.surfaceColor : AppTheme.Theme.surfacePressed
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusBorderColor : control.hovered ? AppTheme.Theme.borderStrong : control.normalBorderColor
    }
}
