import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

Button {
    id: control
    property color surfaceColor: AppTheme.Theme.surfaceRaised
    property color focusBorderColor: AppTheme.Theme.focus
    implicitWidth: 108
    implicitHeight: AppTheme.Theme.buttonHeight
    font.pixelSize: AppTheme.Theme.labelSize
    font.weight: Font.DemiBold
    contentItem: Text {
        text: control.text
        color: control.enabled ? "#b8d8f6" : "#71869a"
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: AppTheme.Theme.radius
        color: !control.enabled ? AppTheme.Theme.surfacePressed : control.down ? "#142536" : control.hovered ? AppTheme.Theme.surfaceHover : control.surfaceColor
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusBorderColor : AppTheme.Theme.borderStrong
    }
}
