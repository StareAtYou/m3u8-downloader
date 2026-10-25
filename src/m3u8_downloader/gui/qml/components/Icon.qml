import QtQuick
import "../theme" as AppTheme

Text {
    property string name: ""
    text: bridge.iconGlyph(name)
    font.family: bridge.iconFontFamily
    font.pixelSize: 18
    color: AppTheme.Theme.muted
    verticalAlignment: Text.AlignVCenter
    horizontalAlignment: Text.AlignHCenter
}
