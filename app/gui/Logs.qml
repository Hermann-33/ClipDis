import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var appBridge
    property var theme
    property var navigate
    property string logsText: ""
    property string logsPath: ""
    Component.onCompleted: refresh()

    function refresh() {
        if (appBridge === null || appBridge === undefined)
            return
        logsPath = appBridge.getLogsFolderPath()
        logsText = appBridge.getRecentLogs().join("\n")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Label { text: "Logs"; color: theme.text; font.pixelSize: 24; font.bold: true; Layout.fillWidth: true }
            SmallButton { text: "Refresh"; theme: root.theme; primary: true; onClicked: refresh() }
            SmallButton { text: "Open Logs Folder"; theme: root.theme; onClicked: appBridge.openLogsFolder() }
        }

        Label {
            text: logsPath
            color: theme.muted
            font.pixelSize: 12
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: "#0d1015"
            border.color: theme.border

            ScrollView {
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                TextArea {
                    text: logsText.length ? logsText : "No logs loaded."
                    readOnly: true
                    wrapMode: TextArea.Wrap
                    color: theme.text
                    selectedTextColor: theme.bg
                    selectionColor: theme.accent
                    background: Rectangle { color: "transparent" }
                    font.family: "Consolas"
                    font.pixelSize: 12
                }
            }
        }
    }

    component SmallButton: Button {
        property var theme
        property bool primary: false
        implicitHeight: 34
        implicitWidth: Math.max(contentItem.implicitWidth + 24, 96)
        hoverEnabled: true
        contentItem: Text {
            text: parent.text
            color: "#ffffff"
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: parent.primary ? (parent.hovered ? "#59c4a3" : theme.accent) : (parent.hovered ? "#2b3442" : theme.panelSoft)
            border.color: parent.primary ? "transparent" : theme.border
        }
    }
}
