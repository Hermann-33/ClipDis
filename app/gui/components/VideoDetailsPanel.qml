import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var clipData: ({})
    property var theme
    signal uploadRequested(int jobId)
    signal deleteRequested(int jobId)

    radius: 12
    color: theme.panel
    border.color: theme.border

    function jobId() { return Number(clipData.job_id || clipData.id || 0) }
    function hasClip() { return jobId() > 0 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        Label {
            text: "Clip Details"
            color: theme.text
            font.pixelSize: 13
            font.bold: true
            Layout.fillWidth: true
        }

        Label {
            visible: !root.hasClip()
            text: "Select a clip to view details."
            color: theme.muted
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        ColumnLayout {
            visible: root.hasClip()
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            Label {
                text: clipData.filename || "Untitled clip"
                color: theme.text
                font.pixelSize: 12
                font.bold: true
                elide: Text.ElideRight
                maximumLineCount: 2
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            DetailLine { label: "Size"; value: clipData.size_display || "Unknown"; theme: root.theme }
            DetailLine { label: "Status"; value: clipData.friendly_status || clipData.statusLabel || "Ready"; theme: root.theme }
            Item { Layout.fillHeight: true }
            SmallButton { text: "Upload"; theme: root.theme; enabled: clipData.uploadable === true; onClicked: root.uploadRequested(root.jobId()) }
            SmallButton { text: "Delete"; theme: root.theme; danger: true; enabled: clipData.deletable === true; onClicked: root.deleteRequested(root.jobId()) }
        }
    }

    component DetailLine: RowLayout {
        property string label
        property string value
        property var theme
        Layout.fillWidth: true
        Label { text: label; color: theme.muted; font.pixelSize: 11; Layout.preferredWidth: 52; elide: Text.ElideRight }
        Label { text: value; color: theme.text; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
    }

    component SmallButton: Button {
        id: buttonRoot
        property var theme
        property bool danger: false
        Layout.fillWidth: true
        implicitHeight: 30
        hoverEnabled: true
        contentItem: Text {
            text: parent.text
            color: parent.enabled ? "#ffffff" : "#697282"
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: !buttonRoot.enabled ? "#202631" : (buttonRoot.danger ? (buttonRoot.hovered ? "#8f3d45" : "#693039") : (buttonRoot.hovered ? "#59c4a3" : theme.accent))
        }
    }
}
