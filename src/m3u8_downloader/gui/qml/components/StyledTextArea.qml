import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

TextArea {
    id: control
    property color surfaceColor: AppTheme.Theme.surfaceRaised
    property color normalBorderColor: AppTheme.Theme.border
    property color focusBorderColor: AppTheme.Theme.focus
    implicitHeight: 120
    leftPadding: 14
    rightPadding: 14
    topPadding: 12
    bottomPadding: 12
    color: AppTheme.Theme.text
    placeholderTextColor: "#74889d"
    selectionColor: AppTheme.Theme.blueSoft
    selectedTextColor: AppTheme.Theme.text
    selectByMouse: true
    wrapMode: TextEdit.Wrap
    font.pixelSize: AppTheme.Theme.bodySize
    background: Rectangle {
        radius: AppTheme.Theme.radius
        color: control.enabled ? control.surfaceColor : AppTheme.Theme.surfacePressed
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusBorderColor : control.hovered ? AppTheme.Theme.borderStrong : control.normalBorderColor
    }
}
