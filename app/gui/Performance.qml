import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var appBridge
    property var theme
    property var navigate
    property var cfg: ({})
    property string message: ""
    property bool messageOk: true
    Component.onCompleted: load()

    function load() {
        if (appBridge === null || appBridge === undefined)
            return
        cfg = appBridge.getConfig()
        maxSizeSpin.value = cfg.max_upload_size_mb || 8
        attemptsSpin.value = cfg.max_ffmpeg_attempts || 3
        pauseFailuresCheck.checked = cfg.pause_on_repeated_failures === true
        failureLimitSpin.value = cfg.repeated_failure_limit || 3
    }

    function save() {
        if (appBridge === null || appBridge === undefined)
            return
        var result = appBridge.saveConfig({
            max_upload_size_mb: maxSizeSpin.value,
            max_ffmpeg_attempts: attemptsSpin.value,
            pause_on_repeated_failures: pauseFailuresCheck.checked,
            repeated_failure_limit: failureLimitSpin.value
        })
        messageOk = result.ok
        message = result.message || "Performance settings saved."
        load()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        Label { text: "Performance"; color: theme.text; font.pixelSize: 24; font.bold: true }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: theme.panel
            border.color: theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    ColumnLayout {
                        width: parent.width
                        spacing: 12

                        Label {
                            text: "Auto Upload is controlled from the dashboard. When it is on, ClipDis keeps processing eligible clips until the watch folder is clear. Failed clips stay failed until you retry them manually."
                            color: theme.muted
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }

                        SectionTitle { text: "Compression"; theme: root.theme }
                        FormRow { label: "Max upload size MB"; theme: root.theme; ModernSpin { id: maxSizeSpin; theme: root.theme; from: 1; to: 500; value: 8 } }
                        FormRow { label: "Max FFmpeg attempts"; theme: root.theme; ModernSpin { id: attemptsSpin; theme: root.theme; from: 1; to: 5; value: 3 } }

                        SectionTitle { text: "Failure Safety"; theme: root.theme }
                        FormRow { label: "Pause on repeated failures"; theme: root.theme; SwitchPill { id: pauseFailuresCheck; theme: root.theme; text: checked ? "On" : "Off" } }
                        FormRow { label: "Repeated failure limit"; theme: root.theme; ModernSpin { id: failureLimitSpin; theme: root.theme; from: 1; to: 20; value: 3 } }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    SmallButton { text: "Save Performance Settings"; theme: root.theme; primary: true; onClicked: save() }
                    Label {
                        text: message
                        visible: message.length > 0
                        color: messageOk ? theme.accent : theme.danger
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    component SectionTitle: Label {
        property var theme
        color: theme.text
        font.pixelSize: 13
        font.bold: true
        Layout.topMargin: 4
    }

    component FormRow: RowLayout {
        property string label
        property var theme
        default property alias rowContent: slot.data
        Layout.fillWidth: true
        spacing: 14
        Label {
            text: parent.label
            color: theme.muted
            font.pixelSize: 12
            Layout.preferredWidth: Math.min(220, root.width * 0.38)
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        Item {
            id: slot
            Layout.preferredWidth: 230
            Layout.maximumWidth: 230
            Layout.preferredHeight: 34
        }
        Item { Layout.fillWidth: true }
    }

    component ModernCombo: ComboBox {
        property var theme
        width: 220
        height: 34
        font.pixelSize: 12
        contentItem: Text {
            text: parent.displayText
            color: theme.text
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            leftPadding: 10
            elide: Text.ElideRight
        }
        background: Rectangle { radius: 8; color: theme.field; border.color: parent.hovered || parent.activeFocus ? theme.accent : theme.border }
        indicator: Text { text: "v"; color: theme.muted; font.bold: true; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter }
        delegate: ItemDelegate {
            width: parent ? parent.width : 220
            height: 32
            contentItem: Text { text: modelData; color: theme.text; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { color: highlighted ? "#2d685c" : theme.panelSoft }
        }
        popup: Popup {
            y: parent.height + 4
            width: parent.width
            implicitHeight: contentItem.implicitHeight
            padding: 1
            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: parent.parent.popup.visible ? parent.parent.delegateModel : null; currentIndex: parent.parent.highlightedIndex }
            background: Rectangle { color: theme.panelSoft; border.color: theme.border; radius: 8 }
        }
    }

    component ModernSpin: SpinBox {
        property var theme
        width: 220
        height: 34
        editable: true
        font.pixelSize: 12
        contentItem: TextInput {
            text: parent.textFromValue(parent.value, parent.locale)
            color: theme.text
            font.pixelSize: 12
            horizontalAlignment: Qt.AlignHCenter
            verticalAlignment: Qt.AlignVCenter
            readOnly: !parent.editable
            validator: parent.validator
            inputMethodHints: Qt.ImhFormattedNumbersOnly
        }
        up.indicator: Rectangle {
            x: parent.width - width
            height: parent.height
            width: 34
            radius: 8
            color: parent.up.pressed ? "#344051" : theme.panelSoft
            Text { text: "+"; anchors.centerIn: parent; color: theme.text; font.pixelSize: 18 }
        }
        down.indicator: Rectangle {
            height: parent.height
            width: 34
            radius: 8
            color: parent.down.pressed ? "#344051" : theme.panelSoft
            Text { text: "-"; anchors.centerIn: parent; color: theme.text; font.pixelSize: 18 }
        }
        background: Rectangle { radius: 8; color: theme.field; border.color: theme.border }
    }

    component SwitchPill: Button {
        property var theme
        checkable: true
        implicitHeight: 32
        implicitWidth: 84
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
            radius: 16
            color: parent.checked ? theme.accent : "#323946"
            Rectangle {
                width: 24
                height: 24
                radius: 12
                y: 4
                x: parent.parent.checked ? parent.width - width - 5 : 5
                color: "#ffffff"
                opacity: 0.92
                Behavior on x { NumberAnimation { duration: 120 } }
            }
        }
    }

    component SmallButton: Button {
        property var theme
        property bool primary: false
        implicitHeight: 34
        implicitWidth: Math.max(contentItem.implicitWidth + 24, 120)
        hoverEnabled: true
        contentItem: Text { text: parent.text; color: "#ffffff"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 8; color: parent.primary ? (parent.hovered ? "#59c4a3" : theme.accent) : (parent.hovered ? "#2b3442" : theme.panelSoft); border.color: parent.primary ? "transparent" : theme.border }
    }
}
