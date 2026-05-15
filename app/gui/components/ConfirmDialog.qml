import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var theme
    property string title: "Confirm action"
    property string message: ""
    property string confirmText: "Confirm"
    property string cancelText: "Cancel"
    property bool danger: true
    signal accepted()
    signal rejected()

    anchors.fill: parent
    visible: false
    z: 1000
    focus: visible

    function open() {
        visible = true
        forceActiveFocus()
    }

    function close() {
        visible = false
    }

    Keys.onEscapePressed: {
        root.close()
        root.rejected()
    }

    Rectangle {
        anchors.fill: parent
        color: "#99000000"

        MouseArea {
            anchors.fill: parent
            onClicked: {
                root.close()
                root.rejected()
            }
        }
    }

    Rectangle {
        id: card
        width: Math.min(420, root.width - 36)
        implicitHeight: content.implicitHeight + 32
        anchors.centerIn: parent
        radius: 16
        color: theme.panel
        border.color: theme.border

        MouseArea { anchors.fill: parent }

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: root.title
                color: theme.text
                font.pixelSize: 17
                font.bold: true
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                text: root.message
                color: theme.muted
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                maximumLineCount: 5
                elide: Text.ElideRight
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Item { Layout.fillWidth: true }
                DialogButton {
                    text: root.cancelText
                    theme: root.theme
                    secondary: true
                    onClicked: {
                        root.close()
                        root.rejected()
                    }
                }
                DialogButton {
                    text: root.confirmText
                    theme: root.theme
                    danger: root.danger
                    onClicked: {
                        root.close()
                        root.accepted()
                    }
                }
            }
        }
    }

    component DialogButton: Button {
        property var theme
        property bool danger: false
        property bool secondary: false
        implicitHeight: 34
        implicitWidth: Math.max(contentItem.implicitWidth + 28, 92)
        hoverEnabled: true
        contentItem: Text {
            text: parent.text
            color: "#ffffff"
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 9
            color: parent.secondary
                ? (parent.hovered ? "#2b3442" : "#222936")
                : (parent.danger ? (parent.hovered ? "#8f3d45" : "#693039") : (parent.hovered ? "#59c4a3" : theme.accent))
            border.color: parent.secondary ? theme.border : "transparent"
        }
    }
}
