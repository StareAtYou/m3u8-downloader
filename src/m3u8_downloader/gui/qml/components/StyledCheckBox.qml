import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

CheckBox {
    id: control
    spacing: 9
    font.pixelSize: 13
    indicator: Rectangle {
        objectName: "customCheckIndicator"
        implicitWidth: 20
        implicitHeight: 20
        x: control.leftPadding
        y: parent.height / 2 - height / 2
        radius: 5
        color: control.checked ? AppTheme.Theme.blue : control.hovered ? AppTheme.Theme.surfaceHover : AppTheme.Theme.surfaceRaised
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? AppTheme.Theme.focus : control.checked ? AppTheme.Theme.blue : AppTheme.Theme.borderStrong
        Icon {
            anchors.centerIn: parent
            name: "checkmark"
            visible: control.checked
            color: "white"
            font.pixelSize: 11
        }
    }
    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: control.enabled ? AppTheme.Theme.muted : "#64778a"
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
