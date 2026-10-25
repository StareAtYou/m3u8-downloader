import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as AppTheme

Dialog {
    id: dialog
    property string saveRoot: ""
    property bool overwrite: false
    title: "批量添加任务"
    modal: true
    width: Math.min(620, Overlay.overlay ? Overlay.overlay.width - 48 : 620)
    height: 430
    anchors.centerIn: Overlay.overlay
    background: Rectangle { color: AppTheme.Theme.surfaceRaised; border.color: AppTheme.Theme.border; radius: 10 }
    header: Item {
        implicitHeight: 54
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            text: dialog.title
            color: AppTheme.Theme.text
            font.pixelSize: 19
            font.weight: Font.DemiBold
        }
    }
    contentItem: ColumnLayout {
        spacing: 12
        Text { text: "每行填写：M3U8 地址 | 任务名称"; color: AppTheme.Theme.muted }
        StyledTextArea {
            id: batchInput
            objectName: "batchInput"
            Layout.fillWidth: true
            Layout.fillHeight: true
            placeholderText: "https://example.com/01.m3u8 | 第01集"
            KeyNavigation.priority: KeyNavigation.BeforeItem
            KeyNavigation.tab: batchCancelButton
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            SecondaryButton {
                id: batchCancelButton
                objectName: "batchCancelButton"
                text: "取消"
                KeyNavigation.tab: batchSubmitButton
                onClicked: dialog.close()
            }
            PrimaryButton {
                id: batchSubmitButton
                objectName: "batchSubmitButton"
                text: "全部添加"
                KeyNavigation.tab: batchInput
                onClicked: {
                    let tasks = []
                    let lines = batchInput.text.split("\n")
                    for (let i = 0; i < lines.length; ++i) {
                        if (!lines[i].trim()) continue
                        let parts = lines[i].split("|")
                        tasks.push({"url": parts[0] ? parts[0].trim() : "", "task_name": parts[1] ? parts[1].trim() : ""})
                    }
                    bridge.submitBatch(tasks, dialog.saveRoot, dialog.overwrite)
                }
            }
        }
    }
    onOpened: batchInput.forceActiveFocus()
}
