import QtQuick
import QtQuick.Layouts
import "../theme" as AppTheme

ColumnLayout {
    id: emptyState
    property string title: "暂无内容"
    property string message: ""
    spacing: 7
    Text {
        Layout.alignment: Qt.AlignHCenter
        text: emptyState.title
        color: AppTheme.Theme.text
        font.pixelSize: 17
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
    }
    Text {
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: 460
        text: emptyState.message
        color: AppTheme.Theme.muted
        font.pixelSize: AppTheme.Theme.bodySize
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
    }
}
