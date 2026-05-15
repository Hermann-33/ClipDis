import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var bridge
    property var theme
    property var jobs: []
    property string message: ""

    function refresh() {
        if (bridge)
            jobs = bridge.getClipHistory()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            Label { text: "Clips"; color: theme.text; font.pixelSize: 30; font.bold: true; Layout.fillWidth: true }
            Button { text: "Refresh"; onClicked: refresh() }
            Button { text: "Clear Old Completed"; onClicked: { var r = bridge.clearCompletedHistory(); message = r.message; refresh() } }
        }

        Label {
            text: message
            visible: message.length > 0
            color: theme.muted
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 10
            color: theme.panel
            border.color: theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    HeaderCell { text: "Filename"; weight: 2; theme: root.theme }
                    HeaderCell { text: "Status"; weight: 1; theme: root.theme }
                    HeaderCell { text: "Size"; weight: 1; theme: root.theme }
                    HeaderCell { text: "Detected"; weight: 2; theme: root.theme }
                    HeaderCell { text: "Compressed"; weight: 1; theme: root.theme }
                    HeaderCell { text: "Discord"; weight: 1; theme: root.theme }
                    HeaderCell { text: "Cleanup"; weight: 1; theme: root.theme }
                    HeaderCell { text: "Error"; weight: 2; theme: root.theme }
                    HeaderCell { text: "Action"; weight: 1; theme: root.theme }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: theme.border }

                Label {
                    text: "No clip history yet."
                    visible: jobs.length === 0
                    color: theme.muted
                    font.pixelSize: 18
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 80
                }

                ScrollView {
                    visible: jobs.length > 0
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ListView {
                        id: listView
                        model: jobs
                        spacing: 4
                        clip: true

                        delegate: Rectangle {
                            width: listView.width
                            height: 46
                            radius: 6
                            color: index % 2 === 0 ? "#202630" : "#1a1f27"

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 10

                                Cell { text: modelData.filename; weight: 2; theme: root.theme }
                                Cell { text: modelData.status; weight: 1; theme: root.theme }
                                Cell { text: modelData.originalSize; weight: 1; theme: root.theme }
                                Cell { text: modelData.detectedAt || modelData.createdAt; weight: 2; theme: root.theme }
                                Cell { text: modelData.compressedSize || ""; weight: 1; theme: root.theme }
                                Cell { text: modelData.discordResponseCode || modelData.discordMessageId || ""; weight: 1; theme: root.theme }
                                Cell { text: modelData.cleanupStatus || ""; weight: 1; theme: root.theme }
                                Cell { text: modelData.errorSummary || ""; weight: 2; theme: root.theme }
                                Item {
                                    property int weight: 1
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: weight * 90
                                    Button {
                                        visible: modelData.status === "failed"
                                        text: "Retry"
                                        anchors.verticalCenter: parent.verticalCenter
                                        onClicked: {
                                            var r = bridge.retryFailedJob(modelData.id)
                                            message = r.message
                                            refresh()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    component HeaderCell: Label {
        property int weight: 1
        property var theme
        Layout.fillWidth: true
        Layout.preferredWidth: weight * 90
        text: ""
        color: theme.muted
        font.bold: true
        font.pixelSize: 12
        elide: Text.ElideRight
    }

    component Cell: Label {
        property int weight: 1
        property var theme
        Layout.fillWidth: true
        Layout.preferredWidth: weight * 90
        color: theme.text
        font.pixelSize: 12
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }
}
