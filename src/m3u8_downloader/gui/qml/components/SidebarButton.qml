import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as AppTheme

Button {
    id: control
    property string iconName: ""
    property int badge: 0
    property bool selected: false
    implicitHeight: 52
    leftPadding: 18
    rightPadding: 12
    focusPolicy: Qt.StrongFocus
    background: Rectangle {
        color: control.selected ? AppTheme.Theme.blueSoft : control.down ? AppTheme.Theme.surfacePressed : control.hovered ? AppTheme.Theme.surfaceHover : "transparent"
        border.width: control.activeFocus ? 2 : 0
        border.color: AppTheme.Theme.focus
        radius: AppTheme.Theme.radius
        Rectangle {
            visible: control.selected
            width: 4
            radius: 2
            color: AppTheme.Theme.blue
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
        }
    }
    contentItem: RowLayout {
        spacing: 14
        Icon { name: control.iconName; color: control.selected ? "white" : AppTheme.Theme.text }
        Text {
            Layout.fillWidth: true
            text: control.text
            color: AppTheme.Theme.text
            font.pixelSize: 16
            font.weight: control.selected ? Font.DemiBold : Font.Normal
        }
        Rectangle {
            visible: control.badge > 0
            implicitWidth: 30
            implicitHeight: 28
            radius: 9
            color: "#314155"
            Text { anchors.centerIn: parent; text: control.badge; color: AppTheme.Theme.text; font.pixelSize: 13 }
        }
    }
}
