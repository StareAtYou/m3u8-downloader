import QtQuick
import "../theme" as AppTheme

Item {
    id: track
    property real progress: 0
    property string tone: "blue"
    readonly property real normalizedProgress: Math.max(0, Math.min(1, progress))
    readonly property color toneColor: tone === "green" ? AppTheme.Theme.green
        : tone === "amber" ? AppTheme.Theme.amber
        : tone === "purple" ? AppTheme.Theme.purple
        : tone === "red" ? AppTheme.Theme.red
        : AppTheme.Theme.blue
    implicitHeight: 12
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: "#304050"
    }
    Rectangle {
        width: parent.width * track.normalizedProgress
        height: parent.height
        radius: height / 2
        color: track.toneColor
    }
}
