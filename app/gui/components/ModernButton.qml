import QtQuick
import QtQuick.Controls
Button {
        id: buttonRoot
        property var theme
        property bool danger: false
        property bool secondary: false
        property bool compact: false
        property bool active: false
        property bool pulse: false
        implicitHeight: compact ? 32 : 36
        implicitWidth: Math.max(contentItem.implicitWidth + 24, compact ? 86 : 104)
        hoverEnabled: true
        contentItem: Text {
            text: parent.text
            color: parent.enabled ? "#ffffff" : "#697282"
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            opacity: buttonRoot.pulse ? 0.78 : 1.0
            color: !buttonRoot.enabled ? "#202631" : (buttonRoot.active ? theme.accent : (buttonRoot.danger ? (buttonRoot.hovered ? "#8f3d45" : "#693039") : (buttonRoot.secondary ? (buttonRoot.hovered ? "#2b3442" : "#222936") : (buttonRoot.hovered ? "#59c4a3" : theme.accent))))
            border.color: buttonRoot.secondary ? theme.border : "transparent"
            SequentialAnimation on opacity {
                running: buttonRoot.pulse
                loops: Animation.Infinite
                NumberAnimation { to: 0.55; duration: 260 }
                NumberAnimation { to: 1.0; duration: 260 }
            }
        }
    }
