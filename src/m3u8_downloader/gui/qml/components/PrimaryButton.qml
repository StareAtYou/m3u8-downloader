import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

Button {
    id: control
    property color surfaceColor: AppTheme.Theme.blue
    property color focusBorderColor: AppTheme.Theme.focus
    implicitHeight: AppTheme.Theme.buttonHeight
    implicitWidth: 126
    font.pixelSize: 15
    font.weight: Font.DemiBold
    contentItem: Text {
        text: control.text
        color: control.enabled ? "white" : "#7890a7"
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: AppTheme.Theme.radius
        color: !control.enabled ? "#233241" : control.down ? "#0877d2" : control.hovered ? "#2aa2ff" : control.surfaceColor
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusBorderColor : "#2ca4ff"
    }
}
