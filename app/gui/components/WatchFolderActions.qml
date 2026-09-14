import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var appBridge
    property var theme
    property string profileId: ""
    property bool removing: false
    signal finished(var result)

    function bytes(value) {
        if (value >= 1073741824) return (value / 1073741824).toFixed(1) + " GB"
        if (value >= 1048576) return (value / 1048576).toFixed(1) + " MB"
        if (value >= 1024) return (value / 1024).toFixed(1) + " KB"
        return value + " B"
    }
    function clear(id) {
        profileId = id
        removing = false
        var r = id ? appBridge.previewClearUploaded(id) : appBridge.previewClearAllUploaded()
        if (!r.ok) { finished(r); return }
        var d = r.data
        confirmation.title = id ? 'Clear uploaded clips from “' + d.profileName + '”?' : "Clear uploaded clips from all watch folders?"
        scope.text = (id ? "" : d.profiles + " folders\n") + d.fileCount + " archived clips (" + bytes(d.totalBytes) + ") will be permanently deleted.\n\n"
            + (id ? d.archivePath : "Safe archived files in each ClipDis Uploaded folder.")
            + "\n\nThe Discord uploads are not affected."
            + (d.unexpectedCount ? "\n" + d.unexpectedCount + " unexpected entries will be skipped." : "")
            + (d.profilesWithErrors ? "\n" + d.profilesWithErrors + " folders could not be previewed and will be reported as failed." : "")
        confirmButton.text = id ? "Clear uploaded clips" : "Clear all uploaded clips"
        confirmation.open()
    }
    function remove(profile) {
        removing = true
        profileId = profile.id
        confirmation.title = 'Remove “' + profile.name + '” from ClipDis?'
        scope.text = "This removes the watch configuration.\nIt does not delete the watch folder or uploaded clips."
        confirmButton.text = "Remove watch folder"
        confirmation.open()
    }
    Dialog {
        id: confirmation
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(560, parent.width - 40)
        height: Math.min(implicitHeight, parent.height - 40)
        modal: true
        closePolicy: Popup.CloseOnEscape
        onOpened: cancelButton.forceActiveFocus()
        background: Rectangle { color: root.theme.panel; radius: 12; border.color: root.theme.border }
        header: Label { text: confirmation.title; color: root.theme.text; font.bold: true; font.pixelSize: 17; padding: 18; wrapMode: Text.Wrap }
        contentItem: ScrollView {
            implicitHeight: scope.implicitHeight
            clip: true
            Label { id: scope; width: confirmation.availableWidth; color: root.theme.muted; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText; font.pixelSize: 13 }
        }
        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            ModernButton { theme: root.theme; compact: true; secondary: true; id: cancelButton; text: "Cancel"; onClicked: confirmation.close() }
            ModernButton { theme: root.theme; compact: true; danger: true;
                id: confirmButton
                onClicked: {
                    confirmation.close()
                    var r = removing ? appBridge.removeWatchFolder(profileId) : (profileId ? appBridge.clearUploaded(profileId) : appBridge.clearAllUploaded())
                    if (!removing && r.data && r.data.bytesFreed !== undefined)
                        r.message += " Freed " + root.bytes(r.data.bytesFreed) + "."
                    root.finished(r)
                }
            }
        }
    }
}
