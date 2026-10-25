pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme" as AppTheme

Rectangle {
    id: page
    objectName: "downloadsPageRoot"
    color: AppTheme.Theme.window
    property var taskModel
    property var selectedTask: ({})
    property bool allRowsSelected: false
    property int activeDetailTab: 0
    property alias tableFocusTarget: taskTable
    readonly property bool compactDetails: width < 892
    readonly property real detailPanelContentHeight: compactDetails ? 330 : Math.max(detailsFlickable.height, 260)
    readonly property bool detailsHorizontalOverflow: detailsFlickable.contentWidth > detailsFlickable.width
    readonly property real selectionWidth: width < 700 ? 28 : 34
    readonly property bool wideColumns: width >= 1200
    readonly property bool showSpeed: width >= 1050
    readonly property bool showEta: width >= 1150
    readonly property bool showRoute: width >= 900
    readonly property real nameWidth: width < 700 ? 110 : wideColumns ? 288 : width >= 1050 ? 230 : 170
    readonly property real specWidth: width < 700 ? 80 : wideColumns ? 125 : 112
    readonly property real speedWidth: wideColumns ? 97 : 82
    readonly property real etaWidth: wideColumns ? 88 : 78
    readonly property real routeWidth: wideColumns ? 108 : 100
    readonly property real stateWidth: width < 700 ? 76 : wideColumns ? 122 : 92
    readonly property real actionsWidth: width < 700 ? 72 : wideColumns ? 88 : 104
    readonly property real columnGap: width < 700 ? 6 : 10
    readonly property real fixedColumnWidth: selectionWidth + nameWidth + specWidth + stateWidth + actionsWidth
        + (showSpeed ? speedWidth : 0) + (showEta ? etaWidth : 0) + (showRoute ? routeWidth : 0)
    readonly property int visibleColumnGaps: 5 + (showSpeed ? 1 : 0) + (showEta ? 1 : 0) + (showRoute ? 1 : 0)
    readonly property real progressWidth: Math.max(80,
        width - 28 - fixedColumnWidth - visibleColumnGaps * columnGap)

    function toneForState(state) {
        if (state === "completed") return "green"
        if (state === "waiting_merge" || state === "queued") return "amber"
        if (state === "failed" || state === "canceled" || state === "interrupted") return "red"
        if (state === "paused") return "purple"
        return "blue"
    }

    function refreshSelectedTask() {
        if (!taskModel || taskModel.count === 0) {
            taskTable.currentIndex = -1
            selectedTask = ({})
            return
        }
        let index = taskTable.currentIndex
        if (index < 0 || index >= taskModel.count)
            index = 0
        taskTable.currentIndex = index
        selectedTask = taskModel.get(index)
    }

    Rectangle {
        id: tableSection
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: page.width >= 892
            ? Math.min(516, Math.max(250, page.height - 268))
            : Math.min(380, Math.max(300, page.height * 0.5))
        color: "transparent"

        Rectangle {
            id: tableHeader
            objectName: "tableHeader"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: AppTheme.Theme.tableHeaderHeight
            color: "#172431"
            border.color: AppTheme.Theme.border
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: page.columnGap
                StyledCheckBox {
                    objectName: "selectionColumnHeader"
                    Layout.preferredWidth: page.selectionWidth
                    Layout.minimumWidth: page.selectionWidth
                    Layout.maximumWidth: page.selectionWidth
                    text: ""
                    checked: page.allRowsSelected
                    onToggled: page.allRowsSelected = checked
                }
                Text { objectName: "nameColumnHeader"; text: "任务名称"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.nameWidth; Layout.minimumWidth: page.nameWidth; Layout.maximumWidth: page.nameWidth }
                Text { objectName: "specColumnHeader"; text: "规格 / 片段"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.specWidth; Layout.minimumWidth: page.specWidth; Layout.maximumWidth: page.specWidth }
                Text { objectName: "progressColumnHeader"; text: "进度"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.progressWidth; Layout.minimumWidth: page.progressWidth; Layout.maximumWidth: page.progressWidth }
                Text { objectName: "speedColumnHeader"; text: "速度"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.speedWidth; Layout.minimumWidth: page.speedWidth; Layout.maximumWidth: page.speedWidth; visible: page.showSpeed }
                Text { objectName: "etaColumnHeader"; text: "预计剩余"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.etaWidth; Layout.minimumWidth: page.etaWidth; Layout.maximumWidth: page.etaWidth; visible: page.showEta }
                Text { objectName: "routeColumnHeader"; text: "网络路线"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.routeWidth; Layout.minimumWidth: page.routeWidth; Layout.maximumWidth: page.routeWidth; visible: page.showRoute }
                Text { objectName: "stateColumnHeader"; text: "状态"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.stateWidth; Layout.minimumWidth: page.stateWidth; Layout.maximumWidth: page.stateWidth }
                Text { objectName: "operationsColumnHeader"; text: "操作"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: page.actionsWidth; Layout.minimumWidth: page.actionsWidth; Layout.maximumWidth: page.actionsWidth }
            }
        }

        Rectangle {
            id: tableViewport
            objectName: "tableViewport"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: tableHeader.bottom
            anchors.bottom: parent.bottom
            color: AppTheme.Theme.window
            border.color: AppTheme.Theme.border

            ListView {
                id: taskTable
                objectName: "taskTable"
                anchors.fill: parent
                clip: true
                cacheBuffer: 4096
                spacing: page.width >= 892 ? 14 : 8
                model: page.taskModel
                currentIndex: -1
                activeFocusOnTab: true
                delegate: Rectangle {
                    id: row
                    objectName: "taskRow"
                    required property int index
                    required property string taskId
                    required property string taskName
                    required property string taskState
                    required property string stateLabel
                    required property real progress
                    required property int completed
                    required property int total
                    required property string speedText
                    required property string route
                    required property string finalPath
                    required property bool canPause
                    required property bool canResume
                    required property bool canRetry
                    required property bool canOpen
                    required property bool canCancel
                    width: taskTable.width
                    height: AppTheme.Theme.taskRowHeight
                    color: ListView.isCurrentItem ? "#142b42" : rowMouse.containsMouse ? "#111f2c" : "transparent"
                    border.color: ListView.isCurrentItem ? "#275d88" : AppTheme.Theme.border

                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: taskTable.currentIndex = row.index
                    }
                    Rectangle {
                        objectName: "currentRowAccent"
                        visible: row.ListView.isCurrentItem
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 3
                        color: AppTheme.Theme.blue
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: page.columnGap
                        StyledCheckBox {
                            id: rowSelection
                            objectName: "rowSelection"
                            Layout.preferredWidth: page.selectionWidth
                            Layout.minimumWidth: page.selectionWidth
                            Layout.maximumWidth: page.selectionWidth
                            text: ""
                            checked: page.allRowsSelected
                            KeyNavigation.tab: pauseButton
                        }
                        Text {
                            objectName: "rowTaskName"
                            text: row.taskName
                            color: AppTheme.Theme.text
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            Layout.preferredWidth: page.nameWidth
                            Layout.minimumWidth: page.nameWidth
                            Layout.maximumWidth: page.nameWidth
                            elide: Text.ElideRight
                            maximumLineCount: 1
                        }
                        ColumnLayout {
                            objectName: "rowSpecColumn"
                            Layout.preferredWidth: page.specWidth
                            Layout.minimumWidth: page.specWidth
                            Layout.maximumWidth: page.specWidth
                            spacing: 2
                            Text {
                                objectName: row.index === 0 ? "firstSpecification" : "rowSpecification"
                                text: "—"
                                color: AppTheme.Theme.text
                                font.pixelSize: 13
                            }
                            Text {
                                text: row.total > 0 ? row.total + " 个片段" : "—"
                                color: AppTheme.Theme.muted
                                font.pixelSize: 12
                            }
                        }
                        ColumnLayout {
                            objectName: "rowProgressColumn"
                            Layout.preferredWidth: page.progressWidth
                            Layout.minimumWidth: page.progressWidth
                            Layout.maximumWidth: page.progressWidth
                            spacing: 5
                            ProgressTrack {
                                Layout.fillWidth: true
                                progress: row.progress
                                tone: page.toneForState(row.taskState)
                            }
                            Text {
                                text: Math.round(row.progress * 1000) / 10 + "%  ·  " + row.completed + " / " + row.total
                                color: AppTheme.Theme.muted
                                font.pixelSize: 12
                            }
                        }
                        Text { objectName: "rowSpeedColumn"; text: row.speedText; color: AppTheme.Theme.text; font.pixelSize: 13; Layout.preferredWidth: page.speedWidth; Layout.minimumWidth: page.speedWidth; Layout.maximumWidth: page.speedWidth; visible: page.showSpeed }
                        Text {
                            objectName: row.index === 0 ? "firstEta" : "rowEta"
                            text: "—"
                            color: AppTheme.Theme.muted
                            font.pixelSize: 13
                            Layout.preferredWidth: page.etaWidth
                            Layout.minimumWidth: page.etaWidth
                            Layout.maximumWidth: page.etaWidth
                            visible: page.showEta
                        }
                        StatusBadge {
                            objectName: "routeBadge"
                            Layout.preferredWidth: page.routeWidth
                            Layout.minimumWidth: page.routeWidth
                            Layout.maximumWidth: page.routeWidth
                            label: row.route
                            tone: row.route.indexOf("代理") >= 0 ? "purple" : "blue"
                            visible: page.showRoute
                        }
                        StatusBadge {
                            objectName: "stateBadge"
                            Layout.preferredWidth: page.stateWidth
                            Layout.minimumWidth: page.stateWidth
                            Layout.maximumWidth: page.stateWidth
                            label: row.stateLabel
                            tone: page.toneForState(row.taskState)
                        }
                        RowLayout {
                            objectName: "rowActions"
                            Layout.preferredWidth: page.actionsWidth
                            Layout.minimumWidth: page.actionsWidth
                            Layout.maximumWidth: page.actionsWidth
                            spacing: 0
                            ToolButton {
                                id: pauseButton
                                visible: row.canPause
                                onClicked: bridge.controlTask("pause", row.taskId)
                                background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                                contentItem: Icon { name: "pause"; color: AppTheme.Theme.text }
                                ToolTip.visible: hovered
                                ToolTip.text: "暂停"
                            }
                            ToolButton {
                                visible: row.canResume
                                onClicked: bridge.controlTask("resume", row.taskId)
                                background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                                contentItem: Icon { name: "play"; color: AppTheme.Theme.green }
                                ToolTip.visible: hovered
                                ToolTip.text: "继续"
                            }
                            ToolButton {
                                visible: row.canRetry
                                onClicked: bridge.controlTask("retry", row.taskId)
                                background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                                contentItem: Icon { name: "retry"; color: AppTheme.Theme.blue }
                                ToolTip.visible: hovered
                                ToolTip.text: "重试"
                            }
                            ToolButton {
                                visible: row.canOpen
                                onClicked: bridge.openOutputFolder(row.finalPath)
                                background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                                contentItem: Icon { name: "folder"; color: AppTheme.Theme.text }
                                ToolTip.visible: hovered
                                ToolTip.text: "打开目录"
                            }
                            ToolButton {
                                visible: row.canCancel
                                onClicked: bridge.controlTask("cancel", row.taskId)
                                background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                                contentItem: Icon { name: "cancel"; color: AppTheme.Theme.muted }
                                ToolTip.visible: hovered
                                ToolTip.text: "取消"
                            }
                        }
                    }
                }
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    contentItem: Rectangle { implicitWidth: 6; radius: 3; color: AppTheme.Theme.borderStrong }
                }
            }

            EmptyState {
                objectName: "taskEmptyState"
                visible: !page.taskModel || page.taskModel.count === 0
                anchors.centerIn: parent
                title: "暂无下载任务"
                message: "在上方填写地址和任务名称，开始新的下载任务"
            }
        }
    }

    Rectangle {
        id: detailsRegion
        objectName: "detailsRegion"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: tableSection.bottom
        anchors.bottom: parent.bottom
        anchors.margins: 24
        color: "transparent"

        Flickable {
            id: detailsFlickable
            objectName: "detailsFlickable"
            anchors.fill: parent
            clip: true
            contentWidth: width
            contentHeight: page.compactDetails
                ? detailPanel.height + 16 + logPanel.height
                : page.detailPanelContentHeight
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }
            ScrollBar.vertical: ScrollBar {
                policy: detailsFlickable.contentHeight > detailsFlickable.height
                    ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
                contentItem: Rectangle { implicitWidth: 6; radius: 3; color: AppTheme.Theme.borderStrong }
            }

            Item {
                id: detailPanel
                objectName: "detailPanel"
                x: 0
                y: 0
                width: page.compactDetails ? detailsFlickable.width : detailsFlickable.width * 0.58 - 14
                height: page.detailPanelContentHeight

                Text {
                    id: detailTitle
                    objectName: "detailTitle"
                    anchors.left: parent.left
                    anchors.top: parent.top
                    width: Math.min(implicitWidth, parent.width - detailStatus.width - 16)
                    text: page.selectedTask.taskName || "请选择任务"
                    color: AppTheme.Theme.text
                    font.pixelSize: 21
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                StatusBadge {
                    id: detailStatus
                    objectName: "detailStatus"
                    anchors.left: detailTitle.right
                    anchors.leftMargin: 12
                    anchors.top: parent.top
                    label: page.selectedTask.stateLabel || "—"
                    tone: page.toneForState(page.selectedTask.taskState || "")
                }
                Text {
                    id: detailSource
                    objectName: "detailSource"
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.topMargin: 40
                    width: Math.min(implicitWidth, parent.width - copySourceButton.width - 8)
                    text: page.selectedTask.redactedUrl || "—"
                    color: AppTheme.Theme.muted
                    font.pixelSize: 13
                    elide: Text.ElideMiddle
                }
                ToolButton {
                    id: copySourceButton
                    objectName: "copySourceButton"
                    anchors.left: detailSource.right
                    anchors.leftMargin: 8
                    anchors.top: parent.top
                    anchors.topMargin: 28
                    width: 34
                    height: 34
                    visible: Boolean(page.selectedTask.redactedUrl)
                    onClicked: bridge.copyText(page.selectedTask.redactedUrl)
                    background: Rectangle { color: parent.hovered ? AppTheme.Theme.surfaceHover : "transparent"; radius: AppTheme.Theme.radiusSmall }
                    contentItem: Icon { name: "copy"; color: AppTheme.Theme.muted; font.pixelSize: 14 }
                    ToolTip.visible: hovered
                    ToolTip.text: "复制脱敏地址"
                }
                ProgressTrack {
                    id: detailProgress
                    objectName: "detailProgress"
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.topMargin: 82
                    width: Math.max(160, parent.width - 178)
                    progress: page.selectedTask.progress || 0
                    tone: page.toneForState(page.selectedTask.taskState || "")
                }
                Text {
                    id: detailProgressPercent
                    objectName: "detailProgressPercent"
                    anchors.left: detailProgress.right
                    anchors.leftMargin: 14
                    anchors.verticalCenter: detailProgress.verticalCenter
                    text: Math.round((page.selectedTask.progress || 0) * 100) + "%"
                    color: AppTheme.Theme.text
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Text {
                    anchors.left: detailProgressPercent.right
                    anchors.leftMargin: 12
                    anchors.verticalCenter: detailProgress.verticalCenter
                    text: (page.selectedTask.completed || 0) + " / " + (page.selectedTask.total || 0) + " 个片段"
                    color: AppTheme.Theme.muted
                    font.pixelSize: 13
                }

                GridLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 124
                    columns: 4
                    columnSpacing: 12
                    rowSpacing: 13

                    Text { objectName: "detailSaveLabel"; text: "保存目录"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 58 }
                    Text { objectName: "detailSaveRoot"; text: page.selectedTask.saveRoot || "—"; color: AppTheme.Theme.text; font.pixelSize: 13; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    Text { text: "最终文件名"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 70 }
                    Text { objectName: "detailFilename"; text: page.selectedTask.filename || "—"; color: AppTheme.Theme.text; font.pixelSize: 13; elide: Text.ElideMiddle; Layout.fillWidth: true }

                    Text { text: "片段进度"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 58 }
                    Text { objectName: "detailSegments"; text: (page.selectedTask.completed || 0) + " / " + (page.selectedTask.total || 0); color: AppTheme.Theme.text; font.pixelSize: 13; Layout.fillWidth: true }
                    Text { text: "下载速度"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 70 }
                    Text { objectName: "detailSpeed"; text: page.selectedTask.speedText || "—"; color: AppTheme.Theme.text; font.pixelSize: 13; Layout.fillWidth: true }

                    Text { text: "网络路线"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 58 }
                    Text { objectName: "detailRoute"; text: page.selectedTask.route || "检测中"; color: AppTheme.Theme.text; font.pixelSize: 13; Layout.fillWidth: true }
                    Text { text: "错误摘要"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 70 }
                    Text { objectName: "detailError"; text: page.selectedTask.errorText || "—"; color: page.selectedTask.errorText ? AppTheme.Theme.red : AppTheme.Theme.text; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true }

                    Text { text: "媒体规格"; color: AppTheme.Theme.muted; font.pixelSize: 13; Layout.preferredWidth: 58 }
                    Text { objectName: "detailMediaSpec"; text: "—"; color: AppTheme.Theme.text; font.pixelSize: 13; Layout.fillWidth: true }
                    Item { Layout.preferredWidth: 70; implicitHeight: 1 }
                    Item { Layout.fillWidth: true; implicitHeight: 1 }
                }
            }

            Rectangle {
                visible: !page.compactDetails
                x: detailPanel.width + 13
                y: 0
                width: 1
                height: detailsFlickable.height
                color: AppTheme.Theme.border
            }

            Item {
                id: logPanel
                objectName: "logPanel"
                x: page.compactDetails ? 0 : detailPanel.width + 28
                y: page.compactDetails ? detailPanel.height + 16 : 0
                width: page.compactDetails ? detailsFlickable.width : detailsFlickable.width - x
                height: page.compactDetails ? 260 : page.detailPanelContentHeight

                Button {
                    id: logTabButton
                    objectName: "logTabButton"
                    x: 0
                    y: 0
                    width: 76
                    height: 34
                    text: "任务日志"
                    checkable: true
                    checked: page.activeDetailTab === 0
                    onCheckedChanged: { if (checked) page.activeDetailTab = 0 }
                    contentItem: Text { text: parent.text; color: parent.checked ? AppTheme.Theme.text : AppTheme.Theme.muted; font.pixelSize: 14; font.weight: parent.checked ? Font.DemiBold : Font.Normal; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    background: Item {}
                }
                Button {
                    id: networkTabButton
                    objectName: "networkTabButton"
                    x: logTabButton.width + 20
                    y: 0
                    width: 112
                    height: 34
                    text: "网络路线说明"
                    checkable: true
                    checked: page.activeDetailTab === 1
                    onCheckedChanged: { if (checked) page.activeDetailTab = 1 }
                    contentItem: Text { text: parent.text; color: parent.checked ? AppTheme.Theme.text : AppTheme.Theme.muted; font.pixelSize: 14; font.weight: parent.checked ? Font.DemiBold : Font.Normal; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    background: Item {}
                }
                Rectangle {
                    id: activeTabIndicator
                    objectName: "activeTabIndicator"
                    x: page.activeDetailTab === 0 ? logTabButton.x : networkTabButton.x
                    y: 44
                    width: page.activeDetailTab === 0 ? logTabButton.width : networkTabButton.width
                    height: 2
                    color: AppTheme.Theme.blue
                }
                Rectangle {
                    objectName: "logContentPanel"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.topMargin: 62
                    color: "#0e1720"
                    border.color: AppTheme.Theme.border
                    radius: AppTheme.Theme.radius
                    Text {
                        objectName: "logContentText"
                        anchors.fill: parent
                        anchors.margins: 16
                        text: page.activeDetailTab === 0
                            ? (page.selectedTask.taskName
                                ? "当前状态    " + page.selectedTask.stateLabel
                                    + "\n下载进度    " + (page.selectedTask.completed || 0) + " / " + (page.selectedTask.total || 0)
                                    + "\n下载速度    " + (page.selectedTask.speedText || "—")
                                    + "\n网络路线    " + (page.selectedTask.route || "检测中")
                                    + (page.selectedTask.errorText ? "\n错误摘要    " + page.selectedTask.errorText : "")
                                : "选择一个任务以查看运行信息")
                            : (page.selectedTask.taskName
                                ? (page.selectedTask.route.indexOf("代理") >= 0
                                    ? "当前任务通过本地代理传输。\n路线：" + page.selectedTask.route
                                    : page.selectedTask.route === "检测中"
                                        ? "正在检测当前任务的可用网络路线。"
                                        : "当前任务通过本地网络直连。\n路线：" + page.selectedTask.route)
                                : "选择一个任务以查看网络路线说明")
                        color: AppTheme.Theme.muted
                        font.pixelSize: 13
                        lineHeight: 1.55
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    Connections {
        target: page.taskModel
        ignoreUnknownSignals: true
        function onCountChanged() { Qt.callLater(page.refreshSelectedTask) }
    }
    Connections {
        target: taskTable
        function onCurrentIndexChanged() { Qt.callLater(page.refreshSelectedTask) }
    }
    Component.onCompleted: Qt.callLater(page.refreshSelectedTask)
}
