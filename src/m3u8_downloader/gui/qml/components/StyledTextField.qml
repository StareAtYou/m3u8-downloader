import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

TextField {
    id: control
    property string trailingIcon: ""
    property color surfaceColor: AppTheme.Theme.surfaceRaised
    property color normalBorderColor: AppTheme.Theme.border
    property color focusBorderColor: AppTheme.Theme.focus
    property alias trailingAction: trailingActionButton
    property Item trailingTabTarget: null
    signal trailingClicked()

    implicitHeight: AppTheme.Theme.controlHeight
    leftPadding: 14
    rightPadding: trailingIcon ? 44 : 14
    color: AppTheme.Theme.text
    placeholderTextColor: "#74889d"
    selectionColor: AppTheme.Theme.blueSoft
    selectedTextColor: AppTheme.Theme.text
    selectByMouse: true
    font.pixelSize: AppTheme.Theme.bodySize
    background: Rectangle {
        radius: AppTheme.Theme.radius
        color: control.enabled ? control.surfaceColor : AppTheme.Theme.surfacePressed
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusBorderColor : control.hovered ? AppTheme.Theme.borderStrong : control.normalBorderColor
    }
    ToolButton {
        id: trailingActionButton
        objectName: "trailingAction"
        visible: control.trailingIcon.length > 0
        enabled: control.enabled
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 42
        focusPolicy: Qt.StrongFocus
        activeFocusOnTab: visible
        KeyNavigation.tab: control.trailingTabTarget
        Accessible.name: control.trailingIcon === "folder" ? "选择保存目录" : "输入框附加操作"
        onClicked: control.trailingClicked()
        background: Item {}
        contentItem: Icon {
            name: control.trailingIcon
            color: parent.hovered ? AppTheme.Theme.text : AppTheme.Theme.muted
            font.pixelSize: 16
        }
    }
}
