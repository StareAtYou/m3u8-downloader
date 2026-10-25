import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as AppTheme

Rectangle {
    id: page
    color: AppTheme.Theme.window

    Flickable {
        id: settingsScroll
        objectName: "settingsScroll"
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: form.height + 56
        flickableDirection: Flickable.VerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle { implicitWidth: 6; radius: 3; color: AppTheme.Theme.borderStrong }
        }

        function reveal(item) {
            if (!item || !item.visible)
                return
            const point = item.mapToItem(settingsScroll.contentItem, 0, 0)
            const itemTop = point.y
            const itemBottom = itemTop + item.height
            const padding = 12
            if (itemTop - padding < contentY)
                contentY = Math.max(0, itemTop - padding)
            else if (itemBottom + padding > contentY + height)
                contentY = Math.min(Math.max(0, contentHeight - height), itemBottom + padding - height)
        }

        ColumnLayout {
            id: form
            x: 34
            y: 28
            width: Math.min(720, settingsScroll.width - 68)
            spacing: 9

            Text { text: "下载设置"; color: AppTheme.Theme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
            Text { text: "保存后会应用于新任务；活动任务继续使用提交时的参数。"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.bottomMargin: 8 }

            Text { objectName: "defaultSaveLabel"; text: "默认保存目录"; color: AppTheme.Theme.muted; font.pixelSize: AppTheme.Theme.bodySize }
            StyledTextField {
                id: defaultSaveDir
                objectName: "defaultSaveDir"
                Layout.fillWidth: true
                text: bridge.defaultSaveDir
                KeyNavigation.tab: closeBehavior
                KeyNavigation.backtab: saveSettingsButton
                KeyNavigation.priority: KeyNavigation.BeforeItem
                onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(defaultSaveDir)
            }

            Text { objectName: "closeBehaviorLabel"; text: "关闭窗口时"; color: AppTheme.Theme.muted; font.pixelSize: AppTheme.Theme.bodySize; Layout.topMargin: 4 }
            StyledComboBox {
                id: closeBehavior
                objectName: "closeBehavior"
                Layout.fillWidth: true
                model: ["最小化到系统托盘", "退出界面"]
                KeyNavigation.tab: activeTasks
                KeyNavigation.backtab: defaultSaveDir
                KeyNavigation.priority: KeyNavigation.BeforeItem
                onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(closeBehavior)
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 18
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: "同时下载任务数"; color: AppTheme.Theme.muted; font.pixelSize: AppTheme.Theme.bodySize }
                    StyledSpinBox {
                        id: activeTasks
                        objectName: "activeTasks"
                        Layout.fillWidth: true
                        from: 1
                        to: 16
                        value: 3
                        KeyNavigation.tab: segmentThreads
                        KeyNavigation.backtab: closeBehavior
                        KeyNavigation.priority: KeyNavigation.BeforeItem
                        onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(activeTasks)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: "每个任务的片段线程数"; color: AppTheme.Theme.muted; font.pixelSize: AppTheme.Theme.bodySize }
                    StyledSpinBox {
                        id: segmentThreads
                        objectName: "segmentThreads"
                        Layout.fillWidth: true
                        from: 1
                        to: 64
                        value: 16
                        KeyNavigation.tab: proxyPolicy
                        KeyNavigation.backtab: activeTasks
                        KeyNavigation.priority: KeyNavigation.BeforeItem
                        onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(segmentThreads)
                    }
                }
            }

            Text { objectName: "proxyPolicyLabel"; text: "代理策略"; color: AppTheme.Theme.muted; font.pixelSize: AppTheme.Theme.bodySize; Layout.topMargin: 4 }
            StyledComboBox {
                id: proxyPolicy
                objectName: "proxyPolicy"
                Layout.fillWidth: true
                model: ["自动选择", "仅直连", "手动本地代理"]
                KeyNavigation.tab: manualProxy.visible ? manualProxy : ffmpegPath
                KeyNavigation.backtab: segmentThreads
                KeyNavigation.priority: KeyNavigation.BeforeItem
                onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(proxyPolicy)
            }
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                Text {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: "本地代理地址"
                    color: AppTheme.Theme.muted
                    font.pixelSize: 12
                    visible: manualProxy.visible
                }
                StyledTextField {
                    id: manualProxy
                    objectName: "manualProxy"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    visible: proxyPolicy.currentIndex === 2
                    placeholderText: "socks5://127.0.0.1:7890"
                    KeyNavigation.tab: ffmpegPath
                    KeyNavigation.backtab: proxyPolicy
                    KeyNavigation.priority: KeyNavigation.BeforeItem
                    onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(manualProxy)
                }
            }

            Text { objectName: "ffmpegLabel"; text: "FFmpeg 路径"; color: AppTheme.Theme.muted; font.pixelSize: AppTheme.Theme.bodySize }
            StyledTextField {
                id: ffmpegPath
                objectName: "ffmpegPath"
                Layout.fillWidth: true
                text: "ffmpeg"
                KeyNavigation.tab: saveSettingsButton
                KeyNavigation.backtab: manualProxy.visible ? manualProxy : proxyPolicy
                KeyNavigation.priority: KeyNavigation.BeforeItem
                onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(ffmpegPath)
            }

            PrimaryButton {
                id: saveSettingsButton
                objectName: "saveSettingsButton"
                Layout.topMargin: 8
                text: "保存设置"
                KeyNavigation.tab: defaultSaveDir
                KeyNavigation.backtab: ffmpegPath
                KeyNavigation.priority: KeyNavigation.BeforeItem
                onActiveFocusChanged: if (activeFocus) settingsScroll.reveal(saveSettingsButton)
                onClicked: bridge.saveSettings({
                    "default_save_dir": defaultSaveDir.text,
                    "max_active_tasks": activeTasks.value,
                    "segment_threads": segmentThreads.value,
                    "proxy_policy": proxyPolicy.currentIndex === 0 ? "auto" : proxyPolicy.currentIndex === 1 ? "direct" : "manual",
                    "manual_proxy": manualProxy.text || null,
                    "ffmpeg_path": ffmpegPath.text || "ffmpeg",
                    "close_behavior": closeBehavior.currentIndex === 0 ? "tray" : "shutdown"
                })
            }
        }
    }

    Connections {
        target: bridge
        function onSettingsLoaded(settings) {
            defaultSaveDir.text = settings.default_save_dir || bridge.defaultSaveDir
            activeTasks.value = settings.max_active_tasks || 3
            segmentThreads.value = settings.segment_threads || 16
            proxyPolicy.currentIndex = settings.proxy_policy === "direct" ? 1 : settings.proxy_policy === "manual" ? 2 : 0
            manualProxy.text = settings.manual_proxy || ""
            ffmpegPath.text = settings.ffmpeg_path || "ffmpeg"
            closeBehavior.currentIndex = settings.close_behavior === "shutdown" ? 1 : 0
        }
    }
    Component.onCompleted: bridge.loadSettings()
}
