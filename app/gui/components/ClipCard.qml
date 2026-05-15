import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var clipData: ({})
    property var theme
    property bool checked: false
    property bool active: false
    property bool hovered: cardMouse.containsMouse || checkboxMouse.containsMouse
    signal opened(var clipData)
    signal toggled(int jobId)
    signal thumbnailRequested(int jobId)

    width: 178
    height: 172
    radius: 14
    color: active ? "#223a36" : (hovered ? "#27303d" : theme.panelSoft)
    border.color: checked ? theme.accent : (active ? theme.accent : (hovered ? "#465365" : theme.border))
    border.width: active || checked ? 2 : 1

    Component.onCompleted: requestMissingThumbnail()
    onClipDataChanged: requestMissingThumbnail()

    function requestMissingThumbnail() {
        var status = clipData.thumbnail_status || "missing"
        if ((clipData.thumbnail_url || "") || status === "generating" || status === "failed")
            return
        var jobId = Number(clipData.job_id || clipData.id || 0)
        if (jobId > 0)
            root.thumbnailRequested(jobId)
    }

    MouseArea {
        id: cardMouse
        anchors.fill: parent
        z: 0
        hoverEnabled: true
        onClicked: root.opened(root.clipData)
        cursorShape: Qt.PointingHandCursor
    }

    ColumnLayout {
        z: 1
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(76, Math.round(width * 9 / 16))
            radius: 10
            color: "#10151d"
            clip: true
            border.color: "#293241"

            Image {
                anchors.fill: parent
                source: clipData.thumbnail_url || ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                visible: status === Image.Ready
            }

            Text {
                anchors.centerIn: parent
                text: (clipData.thumbnail_status || "") === "generating" ? "Making preview..." : "No preview"
                color: theme.muted
                font.pixelSize: 11
                visible: !(clipData.thumbnail_url || "")
            }

            Rectangle {
                visible: root.hovered || root.checked
                width: 24
                height: 24
                radius: 7
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 8
                color: root.checked ? theme.accent : "#141a23"
                border.color: root.checked ? theme.accent : "#4a5566"
                z: 4

                Text {
                    anchors.centerIn: parent
                    text: root.checked ? "✓" : ""
                    color: "#ffffff"
                    font.pixelSize: 14
                    font.bold: true
                }

                MouseArea {
                    id: checkboxMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                        mouse.accepted = true
                        root.toggled(Number(clipData.job_id || clipData.id || 0))
                    }
                }
            }

            Rectangle {
                visible: badgeText(clipData.raw_status || clipData.status || "").length > 0
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 8
                radius: 9
                height: 20
                width: Math.min(statusText.implicitWidth + 18, parent.width - 16)
                color: statusColor(clipData.raw_status || clipData.status || "")
                Text {
                    id: statusText
                    anchors.centerIn: parent
                    text: badgeText(clipData.raw_status || clipData.status || "")
                    color: "#ffffff"
                    font.pixelSize: 10
                    font.bold: true
                    elide: Text.ElideRight
                    width: parent.width - 10
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: clipData.filename || "Unnamed clip"
            color: theme.text
            font.pixelSize: 12
            font.bold: true
            maximumLineCount: 2
            elide: Text.ElideRight
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Text {
                Layout.fillWidth: true
                text: clipData.size_display || clipData.originalSize || ""
                color: theme.muted
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            Text {
                visible: (clipData.summary || clipData.errorSummary || "").length > 0
                Layout.maximumWidth: 82
                text: clipData.summary || clipData.errorSummary || ""
                color: (clipData.raw_status || clipData.status) === "failed" ? theme.danger : theme.muted
                font.pixelSize: 11
                elide: Text.ElideRight
            }
        }
    }

    function statusColor(status) {
        if (status === "failed")
            return theme.danger
        if (status === "uploaded")
            return theme.accent
        if (status === "processing" || status === "uploading")
            return "#4f7db5"
        if (status === "processed")
            return "#7c64c8"
        return "#596475"
    }

    function badgeText(status) {
        if (status === "processing")
            return "Compressing"
        if (status === "processed")
            return "Ready"
        if (status === "uploading")
            return "Uploading"
        if (status === "uploaded")
            return "Uploaded"
        if (status === "failed")
            return "Failed"
        if (status === "skipped")
            return "Skipped"
        return ""
    }
}
