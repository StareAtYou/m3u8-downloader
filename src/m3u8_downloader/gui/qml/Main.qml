import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"
import "dialogs"
import "theme" as AppTheme

ApplicationWindow {
    id: window
    objectName: "mainWindow"
    visible: true
    width: 1440
    height: 1024
    minimumWidth: 820
    minimumHeight: 640
    title: "M3U8 Downloader Pro"
    color: AppTheme.Theme.window
    property int currentPage: 0
    property bool trayAvailable: false
    property string errorMessage: ""
    property var pendingTask: ({})
    property var pendingDeleteTask: ({})
    readonly property bool compactLayout: width < 1100
    readonly property bool horizontalOverflow: urlInput.x < 0
        || batchAddButton.x + batchAddButton.width > composer.width

    Action { id: pauseAllAction; objectName: "pauseAllAction"; text: "暂停全部"; onTriggered: bridge.pauseAll() }
    Action { id: showWindowAction; objectName: "showWindowAction"; text: "显示主窗口"; onTriggered: window.show() }
    Action { id: quitAction; objectName: "quitAction"; text: "退出"; onTriggered: Qt.quit() }

    function requestTaskDeletion(taskId, taskName, finalPath) {
        pendingDeleteTask = {"taskId": taskId, "taskName": taskName, "finalPath": finalPath}
        deleteTaskDialog.open()
    }

    Rectangle {
        id: sidebar
        width: 208
        color: AppTheme.Theme.sidebar
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        border.color: "#213140"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            anchors.topMargin: 58
            spacing: 8
            SidebarButton {
                id: downloadsNavigation
                objectName: "downloadsNavigation"
                Layout.fillWidth: true
                text: "下载任务"
                iconName: "download"
                badge: bridge.tasks.count
                selected: window.currentPage === 0
                KeyNavigation.tab: completedNavigation
                onClicked: window.currentPage = 0
            }
            SidebarButton {
                id: completedNavigation
                objectName: "completedNavigation"
                Layout.fillWidth: true
                text: "已完成"
                iconName: "check"
                badge: bridge.tasks.completedCount
                selected: window.currentPage === 1
                KeyNavigation.tab: settingsNavigation
                KeyNavigation.backtab: downloadsNavigation
                onClicked: window.currentPage = 1
            }
            SidebarButton {
                id: settingsNavigation
                objectName: "settingsNavigation"
                Layout.fillWidth: true
                text: "设置"
                iconName: "settings"
                selected: window.currentPage === 2
                KeyNavigation.tab: downloads.tableFocusTarget
                KeyNavigation.backtab: completedNavigation
                onClicked: window.currentPage = 2
            }
            Item { Layout.fillHeight: true }
        }
    }

    Rectangle {
        id: composer
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: parent.top
        height: window.compactLayout ? 204 : 176
        color: "#101a24"

        readonly property real marginLeft: window.compactLayout ? 18 : 24
        readonly property real marginRight: window.compactLayout ? 18 : 14
        readonly property real gap: 14
        readonly property real availableWidth: width - marginLeft - marginRight
        readonly property real desktopNameWidth: 260
        readonly property real compactFirstWidth: (availableWidth - gap) * 0.6
        readonly property real compactSecondWidth: availableWidth - gap - compactFirstWidth
        readonly property real desktopUrlWidth: availableWidth - desktopNameWidth
            - addTaskButton.width - batchAddButton.width - gap * 3

        Text {
            id: urlLabel
            objectName: "urlLabel"
            x: composer.marginLeft
            y: window.compactLayout ? 18 : 38
            text: "M3U8 地址"
            color: AppTheme.Theme.muted
            font.pixelSize: AppTheme.Theme.labelSize
        }
        StyledTextField {
            id: urlInput
            objectName: "urlInput"
            x: urlLabel.x
            y: window.compactLayout ? 44 : 64
            width: window.compactLayout ? composer.compactFirstWidth : composer.desktopUrlWidth
            placeholderText: "https://cdn.example.com/video/master.m3u8"
            KeyNavigation.tab: taskNameInput
        }

        Text {
            id: taskNameLabel
            objectName: "taskNameLabel"
            x: window.compactLayout ? urlInput.x + urlInput.width + composer.gap : urlInput.x + urlInput.width + composer.gap
            y: urlLabel.y
            text: "任务名称"
            color: AppTheme.Theme.muted
            font.pixelSize: AppTheme.Theme.labelSize
        }
        StyledTextField {
            id: taskNameInput
            objectName: "taskNameInput"
            x: taskNameLabel.x
            y: urlInput.y
            width: window.compactLayout ? composer.compactSecondWidth : composer.desktopNameWidth
            text: ""
            placeholderText: "例如：风起长安 第03集"
            KeyNavigation.tab: addTaskButton
            KeyNavigation.backtab: urlInput
        }
        Text {
            id: outputPreview
            objectName: "outputPreview"
            x: taskNameInput.x
            y: window.compactLayout ? 99 : 120
            width: taskNameInput.width
            text: "输出：" + bridge.previewFilename(taskNameInput.text)
            color: bridge.previewFilename(taskNameInput.text) === taskNameInput.text.trim() + ".mp4"
                ? AppTheme.Theme.muted : AppTheme.Theme.amber
            font.pixelSize: 13
            elide: Text.ElideMiddle
        }

        PrimaryButton {
            id: addTaskButton
            objectName: "addTaskButton"
            x: window.compactLayout
                ? composer.marginLeft
                : taskNameInput.x + taskNameInput.width + composer.gap
            y: window.compactLayout ? 132 : urlInput.y
            text: "添加任务"
            KeyNavigation.tab: batchAddButton
            KeyNavigation.backtab: taskNameInput
            onClicked: {
                window.pendingTask = {"url": urlInput.text, "task_name": taskNameInput.text}
                bridge.submitTask(urlInput.text, taskNameInput.text)
            }
        }
        SecondaryButton {
            id: batchAddButton
            objectName: "batchAddButton"
            x: addTaskButton.x + addTaskButton.width + composer.gap
            y: addTaskButton.y
            text: "批量添加"
            KeyNavigation.tab: downloadsNavigation
            KeyNavigation.backtab: addTaskButton
            onClicked: batchDialog.open()
        }
    }

    DownloadsPage {
        id: downloads
        objectName: "downloadsPage"
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: composer.bottom
        anchors.bottom: parent.bottom
        visible: window.currentPage === 0
        taskModel: bridge.tasks
        onDeleteRequested: function(taskId, taskName, finalPath) {
            window.requestTaskDeletion(taskId, taskName, finalPath)
        }
    }
    CompletedPage {
        id: completed
        objectName: "completedPage"
        anchors.fill: downloads
        visible: window.currentPage === 1
        taskModel: bridge.tasks
        onDeleteRequested: function(taskId, taskName, finalPath) {
            window.requestTaskDeletion(taskId, taskName, finalPath)
        }
    }
    SettingsPage {
        objectName: "settingsPage"
        anchors.fill: downloads
        visible: window.currentPage === 2
    }
    BatchDialog {
        id: batchDialog
        objectName: "batchDialog"
    }

    Dialog {
        id: errorDialog
        objectName: "errorDialog"
        title: "操作失败"
        modal: true
        width: Math.min(window.width - 48, 480)
        anchors.centerIn: parent
        standardButtons: Dialog.Ok
        contentItem: Label {
            text: window.errorMessage
            color: AppTheme.Theme.text
            wrapMode: Text.Wrap
            width: errorDialog.availableWidth
        }
    }

    Dialog {
        id: overwriteConflictDialog
        objectName: "overwriteConflictDialog"
        title: "文件已存在"
        modal: true
        width: Math.min(window.width - 48, 480)
        anchors.centerIn: parent
        contentItem: Label {
            text: "同名输出文件已存在。是否覆盖原文件？"
            color: AppTheme.Theme.text
            wrapMode: Text.Wrap
            width: overwriteConflictDialog.availableWidth
        }
        footer: DialogButtonBox {
            Button { text: "返回修改"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            Button {
                objectName: "confirmOverwriteButton"
                text: "覆盖"
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
                onClicked: {
                    overwriteConflictDialog.close()
                    bridge.submitTaskWithOverwrite(window.pendingTask.url, window.pendingTask.task_name)
                }
            }
        }
    }

    Dialog {
        id: deleteTaskDialog
        objectName: "deleteTaskDialog"
        title: "删除任务"
        modal: true
        width: Math.min(window.width - 48, 560)
        anchors.centerIn: parent
        onOpened: deleteRecordOnlyButton.forceActiveFocus()
        contentItem: ColumnLayout {
            spacing: 10
            Label {
                id: deleteTaskMessage
                objectName: "deleteTaskMessage"
                Layout.fillWidth: true
                text: "确认删除任务“" + (window.pendingDeleteTask.taskName || "") + "”？"
                color: AppTheme.Theme.text
                font.pixelSize: 15
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: "仅删除记录不会触碰本地文件。删除记录和本地文件会清理任务分片；仅当任务已完成且输出路径未被其他记录引用时，才会同时删除以下视频文件：\n"
                    + (window.pendingDeleteTask.finalPath || "")
                color: AppTheme.Theme.muted
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }
        }
        footer: DialogButtonBox {
            Button {
                objectName: "deleteCancelButton"
                text: "取消"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                id: deleteRecordOnlyButton
                objectName: "deleteRecordOnlyButton"
                text: "仅删除记录"
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
                onClicked: {
                    deleteTaskDialog.close()
                    bridge.deleteTask(window.pendingDeleteTask.taskId || "", false)
                }
            }
            Button {
                objectName: "deleteRecordAndFilesButton"
                text: "删除记录和本地文件"
                DialogButtonBox.buttonRole: DialogButtonBox.DestructiveRole
                onClicked: {
                    deleteTaskDialog.close()
                    bridge.deleteTask(window.pendingDeleteTask.taskId || "", true)
                }
            }
        }
    }

    Connections {
        target: bridge
        function onRequestFailed(action, message) {
            window.errorMessage = message
            if (action === "submit" && (message.indexOf("已存在") >= 0 || message.indexOf("占用") >= 0))
                overwriteConflictDialog.open()
            else
                errorDialog.open()
        }
        function onRequestSucceeded(action, result) {
            if (action === "submit") {
                urlInput.text = ""
                taskNameInput.text = ""
            } else if (action === "submit_batch") {
                batchDialog.close()
            }
        }
    }

    Component.onCompleted: bridge.start()
    onClosing: function(close) {
        if (window.trayAvailable && bridge.closeBehavior === "tray") {
            close.accepted = false
            window.hide()
        } else {
            close.accepted = true
        }
    }
}
