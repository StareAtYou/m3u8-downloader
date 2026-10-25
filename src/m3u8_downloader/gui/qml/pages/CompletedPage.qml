pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as AppTheme

Rectangle {
    id: page
    property var taskModel
    color: AppTheme.Theme.window

    Text {
        id: title
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 28
        text: "已完成"
        color: AppTheme.Theme.text
        font.pixelSize: 24
        font.weight: Font.DemiBold
    }

    ListView {
        id: completedList
        objectName: "completedList"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: title.bottom
        anchors.bottom: parent.bottom
        anchors.margins: 28
        spacing: 8
        clip: true
        model: page.taskModel
        cacheBuffer: 4096
        delegate: Rectangle {
            id: row
            objectName: "completedRow"
            required property string taskName
            required property string filename
            required property string taskState
            required property string finalPath
            width: ListView.view.width
            height: taskState === "completed" ? AppTheme.Theme.taskRowHeight : 0
            visible: taskState === "completed"
            radius: AppTheme.Theme.radius
            color: AppTheme.Theme.surface
            border.color: AppTheme.Theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 12
                Text { text: row.taskName; color: AppTheme.Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                Text { text: row.filename; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 260; elide: Text.ElideMiddle; visible: page.width >= 700 }
                StatusBadge { label: "已完成"; tone: "green"; Layout.preferredWidth: 72; visible: page.width >= 560 }
                ToolButton {
                    onClicked: bridge.openOutputFolder(row.finalPath)
                    background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                    contentItem: Icon { name: "folder"; color: AppTheme.Theme.text }
                    ToolTip.visible: hovered
                    ToolTip.text: "打开输出目录"
                }
            }
        }
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle { implicitWidth: 6; radius: 3; color: AppTheme.Theme.borderStrong }
        }
    }

    EmptyState {
        objectName: "completedEmptyState"
        anchors.centerIn: completedList
        visible: !page.taskModel || page.taskModel.completedCount === 0
        title: "暂无已完成任务"
        message: "下载并合并完成的视频会显示在这里"
    }
}
