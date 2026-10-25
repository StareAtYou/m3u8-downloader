import QtQuick
import QtQuick.Controls
import "../theme" as AppTheme

ComboBox {
    id: control
    property color surfaceColor: AppTheme.Theme.surfaceRaised
    property color normalBorderColor: AppTheme.Theme.border
    property color focusBorderColor: AppTheme.Theme.focus
    implicitHeight: AppTheme.Theme.controlHeight
    leftPadding: 14
    rightPadding: 42
    font.pixelSize: AppTheme.Theme.bodySize
    contentItem: Text {
        leftPadding: 0
        text: control.displayText
        color: control.enabled ? AppTheme.Theme.text : AppTheme.Theme.muted
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Icon {
        name: "chevron-down"
        color: AppTheme.Theme.muted
        font.pixelSize: 13
        width: 38
        height: parent.height
        x: parent.width - width
    }
    background: Rectangle {
        radius: AppTheme.Theme.radius
        color: control.enabled ? control.surfaceColor : AppTheme.Theme.surfacePressed
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusBorderColor : control.hovered ? AppTheme.Theme.borderStrong : control.normalBorderColor
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        padding: 4
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle {
            color: AppTheme.Theme.surfaceRaised
            border.color: AppTheme.Theme.borderStrong
            radius: AppTheme.Theme.radius
        }
    }
    delegate: ItemDelegate {
        required property var model
        required property int index
        width: control.width - 8
        height: 40
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: model[control.textRole]
            color: AppTheme.Theme.text
            font: control.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            color: parent.highlighted ? AppTheme.Theme.blueSoft : parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"
            radius: AppTheme.Theme.radiusSmall
        }
    }
}
