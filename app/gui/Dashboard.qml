import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

Item {
    id: root
    objectName: "DashboardPage"

    property var appBridge
    property var theme
    property var navigate
    property int refreshToken: 0
    property var status: readStatus(refreshToken)
    property var clips: readClips(refreshToken)
    property var selectedIds: []
    property int detailJobId: 0
    property var focusedClip: ({})
    property bool refreshing: false
    property var thumbnailRequestedIds: []
    property string message: ""
    property bool messageOk: true
    property string pendingConfirm: ""
    property int pendingDeleteJobId: 0
    signal clipOpened(var clip)
    signal clipUpdated(var clip)

    function load() { deepRefresh(false) }
    Component.onCompleted: deepRefresh(false)

    Connections {
        target: root.appBridge
        ignoreUnknownSignals: true
        function onThumbnailsChanged() {
            root.silentRefresh()
        }
        function onDashboardDataChanged() {
            root.silentRefresh()
        }
    }

    function readStatus(token) {
        if (appBridge === null || appBridge === undefined)
            return ({})
        return appBridge.getCompactDashboardStatus()
    }

    function readClips(token) {
        if (appBridge === null || appBridge === undefined)
            return []
        try {
            return JSON.parse(appBridge.getDashboardClipsJson())
        } catch (error) {
            messageOk = false
            message = "Could not load clip grid."
            return []
        }
    }

    function refresh() {
        manualRefresh()
    }

    function manualRefresh() {
        refreshing = true
        thumbnailRequestedIds = []
        deepRefresh(true)
        refreshTimer.restart()
    }

    function deepRefresh(showMessage) {
        if (appBridge !== null && appBridge !== undefined) {
            var result = appBridge.refreshAppState()
            if (result.ok !== true) {
                messageOk = false
                message = result.message || "Refresh failed."
            } else if (showMessage === true) {
                messageOk = true
                message = "Dashboard refreshed."
            }
        }
        refreshLocalOnly()
    }

    function refreshLocalOnly() {
        refreshToken += 1
        pruneSelection()
        pruneThumbnailRequests()
        syncDetailClip()
    }

    function silentRefresh() {
        refreshLocalOnly()
    }

    function pruneSelection() {
        selectedIds = selectedIds.filter(function(id) {
            for (var i = 0; i < clips.length; i++) {
                if (Number(clips[i].job_id || clips[i].id || 0) === id && isSafeSelectable(clips[i]))
                    return true
            }
            return false
        })
    }

    function pruneThumbnailRequests() {
        thumbnailRequestedIds = thumbnailRequestedIds.filter(function(id) {
            for (var i = 0; i < clips.length; i++) {
                if (Number(clips[i].job_id || clips[i].id || 0) === id)
                    return true
            }
            return false
        })
    }

    function syncDetailClip() {
        if (detailJobId <= 0) {
            focusedClip = ({})
            return
        }
        for (var i = 0; i < clips.length; i++) {
            if (Number(clips[i].job_id || clips[i].id || 0) === detailJobId) {
                focusedClip = clips[i]
                clipUpdated(clips[i])
                return
            }
        }
        detailJobId = 0
        focusedClip = ({})
        clipUpdated({})
    }

    function clearSelection() {
        selectedIds = []
    }

    function isSafeSelectable(clip) {
        var status = clip.raw_status || clip.status || ""
        var id = Number(clip.job_id || clip.id || 0)
        if (id <= 0)
            return false
        if (status === "processing" || status === "uploading" || status === "uploaded" || status === "archived")
            return false
        return clip.uploadable === true || clip.deletable === true
    }

    function visibleSelectableIds() {
        var ids = []
        for (var i = 0; i < clips.length; i++) {
            if (isSafeSelectable(clips[i]))
                ids.push(Number(clips[i].job_id || clips[i].id || 0))
        }
        return ids
    }

    function allVisibleSelected() {
        var ids = visibleSelectableIds()
        if (ids.length === 0)
            return false
        for (var i = 0; i < ids.length; i++) {
            if (!isSelected(ids[i]))
                return false
        }
        return true
    }

    function selectAllVisible() {
        var ids = visibleSelectableIds()
        if (allVisibleSelected())
            clearSelection()
        else
            selectedIds = ids
    }

    function isSelected(id) {
        return selectedIds.indexOf(id) !== -1
    }

    function toggleSelected(id, selectable) {
        if (selectable !== true || id <= 0)
            return
        var next = selectedIds.slice()
        var index = next.indexOf(id)
        if (index === -1)
            next.push(id)
        else
            next.splice(index, 1)
        selectedIds = next
    }

    function openClip(clip) {
        detailJobId = Number(clip.job_id || clip.id || 0)
        focusedClip = clip || ({})
        clipOpened(clip)
    }

    function requestThumbnail(jobId) {
        var id = Number(jobId)
        if (appBridge === null || appBridge === undefined || id <= 0)
            return
        if (thumbnailRequestedIds.indexOf(id) !== -1)
            return
        var next = thumbnailRequestedIds.slice()
        next.push(id)
        thumbnailRequestedIds = next
        var result = appBridge.ensureThumbnail(id)
        if (result.ok === true && result.data && result.data.thumbnail_status === "ready")
            silentRefresh()
        else if (result.ok === true)
            thumbnailRefreshTimer.restart()
    }

    function runDeleteSelected() {
        console.log("Delete Selected ids=" + JSON.stringify(selectedIds))
        var result = appBridge.deleteSelectedClips(JSON.stringify(selectedIds))
        messageOk = result.ok === true
        message = result.message || "Delete complete."
        silentRefresh()
        return result
    }

    function runUploadSelected() {
        console.log("Upload Selected ids=" + JSON.stringify(selectedIds))
        var result = appBridge.uploadSelectedClips(JSON.stringify(selectedIds))
        messageOk = result.ok === true
        message = result.message || "Selected upload started."
        silentRefresh()
        return result
    }

    function runClearUploaded() {
        var result = appBridge.clearUploadedFolder()
        messageOk = result.ok === true
        message = result.message || "Uploaded folder cleared."
        silentRefresh()
    }

    function runUploadFocused() {
        if (detailJobId <= 0)
            return
        var result = appBridge.uploadClip(detailJobId)
        messageOk = result.ok === true
        message = result.message || "Upload started."
        silentRefresh()
    }

    function runDeleteFocused() {
        if (detailJobId <= 0)
            return
        var result = appBridge.deleteClip(detailJobId)
        messageOk = result.ok === true
        message = result.message || "Delete complete."
        if (result.ok === true) {
            detailJobId = 0
            focusedClip = ({})
        }
        silentRefresh()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        Rectangle {
            visible: status.mainStatus === "Needs Setup"
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            radius: 10
            color: "#2b2417"
            border.color: "#5a4726"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                Label {
                    text: status.setupMessage || "Setup required: choose folders and webhook in Settings."
                    color: "#f1d99a"
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                ModernButton {
                    text: "Open Settings"
                    compact: true
                    theme: root.theme
                    onClicked: if (navigate) navigate("Settings")
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.width < 780 ? 118 : 84
            radius: 12
            color: theme.panel
            border.color: theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.width < 560 ? 2 : (root.width < 780 ? 3 : 6)
                    columnSpacing: 8
                    rowSpacing: 8

                    ModernButton {
                        text: refreshing ? "Refreshing..." : "Refresh"
                        theme: root.theme
                        compact: true
                        Layout.fillWidth: true
                        pulse: refreshing
                        onClicked: manualRefresh()
                    }
                    ModernButton {
                        text: status.autoModeEnabled ? "Auto Upload On" : "Auto Upload Off"
                        theme: root.theme
                        compact: true
                        active: status.autoModeEnabled === true
                        secondary: status.autoModeEnabled !== true
                        Layout.fillWidth: true
                        onClicked: {
                            var result = appBridge.enableAutoMode(!(status.autoModeEnabled === true))
                            messageOk = result.ok === true
                            message = result.message || "Auto upload updated."
                            silentRefresh()
                        }
                    }
                    ModernButton {
                        text: allVisibleSelected() ? "Clear Selection" : "Select All"
                        theme: root.theme
                        compact: true
                        secondary: !allVisibleSelected()
                        active: allVisibleSelected()
                        Layout.fillWidth: true
                        enabled: visibleSelectableIds().length > 0
                        onClicked: selectAllVisible()
                    }
                    ModernButton {
                        text: "Upload Selected"
                        theme: root.theme
                        compact: true
                        Layout.fillWidth: true
                        enabled: selectedIds.length > 0
                        onClicked: runUploadSelected()
                    }
                    ModernButton {
                        text: "Delete Selected"
                        theme: root.theme
                        compact: true
                        danger: true
                        Layout.fillWidth: true
                        enabled: selectedIds.length > 0
                        onClicked: { pendingConfirm = "delete"; confirmDialog.open() }
                    }
                    ModernButton {
                        text: "Clear Uploaded"
                        theme: root.theme
                        compact: true
                        Layout.fillWidth: true
                        secondary: true
                        onClicked: { pendingConfirm = "clear"; confirmDialog.open() }
                    }
                }

                Label {
                    text: "Last uploaded: " + (status.lastUploaded || "None")
                    color: theme.muted
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        Label {
            text: message
            visible: message.length > 0
            color: messageOk ? theme.accent : theme.danger
            font.pixelSize: 12
            Layout.fillWidth: true
            elide: Text.ElideRight
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Clips in Watch Folder"
                theme: root.theme

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    anchors.topMargin: 38
                    spacing: 8

                    Label {
                        visible: clips.length === 0
                        text: "No manageable clips in the watch folder."
                        color: theme.muted
                        font.pixelSize: 14
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 58
                    }

                    GridView {
                        id: clipGrid
                        visible: clips.length > 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: clips
                        cellWidth: Math.max(158, Math.floor(width / Math.max(1, Math.floor(width / 178))))
                        cellHeight: 184
                        boundsBehavior: Flickable.StopAtBounds

                        delegate: ClipCard {
                            width: Math.min(184, clipGrid.cellWidth - 10)
                            height: 174
                            clipData: modelData
                            theme: root.theme
                            checked: root.isSelected(Number(modelData.job_id || modelData.id || 0))
                            active: Number(modelData.job_id || modelData.id || 0) === root.detailJobId
                            onOpened: function(clip) { root.openClip(clip) }
                            onToggled: function(jobId) { root.toggleSelected(jobId, root.isSafeSelectable(modelData)) }
                            onThumbnailRequested: function(jobId) { root.requestThumbnail(jobId) }
                        }
                    }
                }
            }

            Card {
                Layout.preferredWidth: Math.min(240, Math.max(210, root.width * 0.26))
                Layout.maximumWidth: 250
                Layout.fillHeight: true
                title: "Clip Details"
                theme: root.theme

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    anchors.topMargin: 38
                    spacing: 8

                    Label {
                        visible: detailJobId <= 0
                        text: "Select a clip to view details."
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                    }

                    ColumnLayout {
                        visible: detailJobId > 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 8

                        Label {
                            text: focusedClip.filename || "Untitled clip"
                            color: theme.text
                            font.pixelSize: 13
                            font.bold: true
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            maximumLineCount: 2
                            wrapMode: Text.Wrap
                        }
                        DetailLine { label: "Size"; value: focusedClip.size_display || "Unknown"; theme: root.theme }
                        DetailLine { label: "Status"; value: focusedClip.friendly_status || focusedClip.statusLabel || "Ready"; theme: root.theme }
                        Label {
                            visible: (focusedClip.summary || "").length > 0 && (focusedClip.raw_status || "") === "failed"
                            text: focusedClip.summary || ""
                            color: theme.danger
                            font.pixelSize: 12
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            maximumLineCount: 1
                        }
                        Item { Layout.fillHeight: true }
                        ModernButton {
                            text: "Upload"
                            theme: root.theme
                            compact: true
                            Layout.fillWidth: true
                            enabled: detailJobId > 0 && focusedClip.uploadable === true
                            onClicked: runUploadFocused()
                        }
                        ModernButton {
                            text: "Delete"
                            theme: root.theme
                            compact: true
                            danger: true
                            Layout.fillWidth: true
                            enabled: detailJobId > 0 && focusedClip.deletable === true
                            onClicked: { pendingDeleteJobId = detailJobId; pendingConfirm = "single-delete"; confirmDialog.open() }
                        }
                    }
                }
            }
        }
    }

    Timer {
        id: thumbnailRefreshTimer
        interval: 2600
        repeat: false
        onTriggered: refreshLocalOnly()
    }

    Timer {
        id: silentRefreshTimer
        interval: 1500
        repeat: true
        running: root.visible
        onTriggered: silentRefresh()
    }

    Timer {
        id: refreshTimer
        interval: 650
        repeat: false
        onTriggered: refreshing = false
    }

    ConfirmDialog {
        id: confirmDialog
        anchors.fill: parent
        theme: root.theme
        danger: true
        title: pendingConfirm === "delete" ? "Delete selected clips?" : (pendingConfirm === "single-delete" ? "Delete clip?" : "Clear uploaded folder?")
        message: pendingConfirm === "delete"
            ? "This will delete " + selectedIds.length + " selected clip" + (selectedIds.length === 1 ? "" : "s") + " from the watch folder when safe. This cannot be undone."
            : (pendingConfirm === "single-delete"
                ? "This will delete this clip from the watch folder. This cannot be undone."
                : "This will remove files from the uploaded folder. This cannot be undone.")
        confirmText: pendingConfirm === "clear" ? "Clear" : "Delete"
        onAccepted: {
            if (pendingConfirm === "delete")
                runDeleteSelected()
            else if (pendingConfirm === "single-delete")
                runDeleteFocused()
            else if (pendingConfirm === "clear")
                runClearUploaded()
            pendingConfirm = ""
            pendingDeleteJobId = 0
        }
        onRejected: {
            pendingConfirm = ""
            pendingDeleteJobId = 0
        }
    }

    component Card: Rectangle {
        property string title
        property var theme
        radius: 12
        color: theme.panel
        border.color: theme.border
        Label {
            text: title
            color: theme.text
            font.pixelSize: 14
            font.bold: true
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 12
            anchors.topMargin: 10
        }
    }

    component ModernButton: Button {
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

    component DetailLine: RowLayout {
        property string label
        property string value
        property var theme
        property bool danger: false
        Layout.fillWidth: true
        Label { text: label; color: theme.muted; font.pixelSize: 12; Layout.preferredWidth: 78; elide: Text.ElideRight }
        Label { text: value; color: danger ? theme.danger : theme.text; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
    }
}
