import QtQuick
import "../theme" as AppTheme

Rectangle {
    id: badge
    property string label: ""
    property string tone: "muted"
    readonly property color toneColor: tone === "green" ? AppTheme.Theme.green
        : tone === "amber" ? AppTheme.Theme.amber
        : tone === "purple" ? AppTheme.Theme.purple
        : tone === "red" ? AppTheme.Theme.red
        : tone === "blue" ? AppTheme.Theme.blue
        : AppTheme.Theme.muted
    readonly property color textColor: toneColor
    implicitWidth: Math.max(58, labelText.implicitWidth + 22)
    implicitHeight: 28
    radius: AppTheme.Theme.radius
    color: Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.14)
    border.color: Qt.rgba(toneColor.r, toneColor.g, toneColor.b, 0.35)
    Text {
        id: labelText
        anchors.centerIn: parent
        text: badge.label
        color: badge.textColor
        font.pixelSize: AppTheme.Theme.metaSize
        font.weight: Font.DemiBold
    }
}
