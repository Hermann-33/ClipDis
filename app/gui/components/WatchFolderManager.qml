import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var appBridge
    property var theme
    property var profiles: []
    property var editing: ({})
    property string message: ""
    property bool messageOk: true
    spacing: 8
    function reload() {
        if (!appBridge) return
        var r = appBridge.getWatchFolders()
        if (r.ok) profiles = r.data
        else showResult(r)
    }
    function showResult(r) { message = r.message || ""; messageOk = r.ok === true }
    function add() {
        var picked = appBridge.browseForFolder("", "Add watch folder")
        if (!picked.ok) return
        var r = appBridge.addWatchFolder(picked.path)
        showResult(r)
        reload()
        if (r.ok) edit(r.data)
    }
    function edit(profile) {
        editing = profile
        nameField.text = profile.name
        pathField.text = profile.path
        stats.checked = profile.showValorantStats
        caption.checked = profile.captionEnabled
        captionText.text = profile.captionText
        editorError.text = ""
        editor.open()
    }
    Component.onCompleted: reload()
    RowLayout {
        Layout.fillWidth: true
        Label { text: "Watch Folders"; color: theme.text; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true }
        ModernButton { theme: root.theme; compact: true; secondary: true; text: "+ Add Folder"; onClicked: root.add() }
    }
    Label {
        visible: profiles.length === 0
        text: "No watch folders yet\nAdd the folder where your recorder saves clips."
        color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true
    }
    Repeater {
        model: root.profiles
        delegate: Rectangle {
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: row.implicitHeight + 20
            color: theme.panelSoft; radius: 8; border.color: theme.border
            ColumnLayout {
                id: row
                anchors.fill: parent; anchors.margins: 10; spacing: 5
                RowLayout {
                    Label { text: modelData.name; color: theme.text; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                    Label { text: modelData.exists ? "Available" : "Missing"; color: modelData.exists ? theme.accent : theme.warning }
                }
                Label { text: modelData.path; color: theme.muted; Layout.fillWidth: true; elide: Text.ElideMiddle; ToolTip.visible: pathHover.hovered; ToolTip.text: text; HoverHandler { id: pathHover } }
                RowLayout {
                    Label { text: "Valorant Stats: " + (modelData.showValorantStats ? "On" : "Off") + "  ·  Caption: " + (modelData.captionEnabled ? "On" : "Off"); color: theme.muted; font.pixelSize: 11; Layout.fillWidth: true }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Open"; onClicked: root.showResult(appBridge.openWatchFolder(modelData.id)) }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Edit"; onClicked: root.edit(modelData) }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Remove"; onClicked: actions.remove(modelData) }
                }
            }
        }
    }
    Label { text: root.message; visible: text.length > 0; color: root.messageOk ? theme.accent : theme.danger; wrapMode: Text.Wrap; Layout.fillWidth: true }
    WatchFolderActions {
        id: actions; appBridge: root.appBridge; theme: root.theme
        onFinished: function(r) { root.showResult(r); root.reload(); if (r.ok && actions.removing) editor.close() }
    }
    Dialog {
        id: editor
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(640, parent.width - 40)
        height: Math.min(570, parent.height - 40)
        modal: true
        title: "Edit watch folder"
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: theme.panel; radius: 12; border.color: theme.border }
        header: Label { text: editor.title; color: theme.text; padding: 16; font.bold: true; font.pixelSize: 18 }
        contentItem: ScrollView {
            clip: true
            ColumnLayout {
                width: editor.availableWidth - 12
                spacing: 8
                Label { text: "Name"; color: theme.muted }
                TextField { id: nameField; Layout.fillWidth: true; selectByMouse: true }
                Label { text: "Watch folder"; color: theme.muted }
                RowLayout {
                    TextField { id: pathField; Layout.fillWidth: true; selectByMouse: true }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Browse"; onClicked: { var r = appBridge.browseForFolder(pathField.text, "Select watch folder"); if (r.ok) pathField.text = r.path } }
                }
                Label { text: "Uploaded folder (automatic)"; color: theme.muted }
                Label { text: pathField.text.replace(/[\\\/]+$/, "") + "\\ClipDis Uploaded"; color: theme.text; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                CheckBox { id: stats; text: "Show Valorant rank & level" }
                Label { visible: stats.checked; text: "Uses shared Riot/Henrik credentials in Configuration. Missing credentials do not block uploads."; color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                CheckBox { id: caption; text: "Include custom caption" }
                ScrollView {
                    Layout.fillWidth: true; Layout.preferredHeight: 100; clip: true
                    enabled: caption.checked; opacity: caption.checked ? 1 : 0.45
                    TextArea { id: captionText; placeholderText: "Caption"; wrapMode: Text.Wrap; selectByMouse: true }
                }
                Label { text: captionText.text.length + " / 1800"; color: captionText.text.length > 1800 ? theme.danger : theme.muted }
                Flow {
                    Layout.fillWidth: true; spacing: 6
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Open Watch Folder"; onClicked: root.showResult(appBridge.openWatchFolder(editing.id)) }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Open Uploaded Folder"; onClicked: root.showResult(appBridge.openUploadedFolder(editing.id)) }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Clear Uploaded…"; onClicked: actions.clear(editing.id) }
                    ModernButton { theme: root.theme; compact: true; secondary: true; text: "Remove Watch Folder…"; onClicked: actions.remove(editing) }
                }
                Label { id: editorError; color: theme.danger; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            ModernButton { theme: root.theme; compact: true; secondary: true; text: "Cancel"; onClicked: editor.close() }
            ModernButton { theme: root.theme; compact: true; secondary: false;
                text: "Save folder"
                enabled: captionText.text.length <= 1800
                onClicked: {
                    var r = appBridge.updateWatchFolder(editing.id, {name: nameField.text, path: pathField.text, show_valorant_stats: stats.checked, caption_enabled: caption.checked, caption_text: captionText.text})
                    root.showResult(r)
                    if (r.ok) { editor.close(); root.reload() } else editorError.text = r.message
                }
            }
        }
    }
}
