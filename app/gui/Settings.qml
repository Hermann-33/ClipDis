import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

Item {
    id: root
    property var appBridge
    property var theme
    property var navigate
    property var cfg: ({})
    property var setup: ({})
    property string statsRank: "Unknown"
    property string statsLevel: "Unknown"
    property string statsError: ""
    property string message: ""
    property bool messageOk: true
    Component.onCompleted: load()

    function cfgValue(snakeName, camelName, fallback) {
        if (cfg && cfg[snakeName] !== undefined && cfg[snakeName] !== null)
            return cfg[snakeName]
        if (cfg && cfg[camelName] !== undefined && cfg[camelName] !== null)
            return cfg[camelName]
        return fallback
    }

    function regionIndex(value) {
        var wanted = (value || "ap").toString().toLowerCase()
        for (var i = 0; i < regionBox.model.length; i++) {
            if ((regionBox.model[i].value || "").toLowerCase() === wanted)
                return i
        }
        return 0
    }

    function load() {
        if (appBridge === null || appBridge === undefined)
            return
        cfg = appBridge.getConfig()
        setup = appBridge.getSetupStatus()
        webhookField.text = setup.webhookDisplay || "Not configured"
        henrikField.text = setup.henrikDisplay || "Not configured"
        watchField.text = cfgValue("watch_folder", "watchFolder", "")
        uploadedField.text = cfgValue("uploaded_folder", "uploadedFolder", "")
        startupToggle.checked = setup.startupSupported !== false ? setup.startupEnabled === true : cfgValue("start_with_windows", "startWithWindows", false) === true
        startupToggle.enabled = setup.startupSupported !== false
        useStatsToggle.checked = cfgValue("use_henrik_stats", "useHenrikStats", false) === true
        riotNameField.text = cfgValue("riot_username", "riotUsername", "")
        riotTagField.text = cfgValue("riot_tagline", "riotTagline", "")
        regionBox.currentIndex = regionIndex(cfgValue("valorant_region", "valorantRegion", "ap"))
    }

    function secretToSave(value, display) {
        if (!value || value === "Not configured" || value === display)
            return ""
        return value
    }

    function save() {
        if (appBridge === null || appBridge === undefined)
            return
        var result = appBridge.saveConfig({
            watch_folder: watchField.text,
            uploaded_folder: uploadedField.text,
            ffmpeg_source_mode: "bundled",
            ffmpeg_path: "",
            start_with_windows: startupToggle.checked,
            use_henrik_stats: useStatsToggle.checked,
            riot_username: riotNameField.text,
            riot_tagline: riotTagField.text,
            valorant_region: regionBox.currentValue || "ap"
        })
        var secretResult = appBridge.saveSecrets(
            secretToSave(webhookField.text, setup.webhookDisplay),
            secretToSave(henrikField.text, setup.henrikDisplay)
        )
        messageOk = result.ok && secretResult.ok
        message = result.message + " " + secretResult.message
        appBridge.refreshAppState()
        if (result.ok === true || result.config !== undefined)
            load()
    }

    function testStats() {
        if (appBridge === null || appBridge === undefined)
            return
        var result = appBridge.testValorantStats()
        var data = result.data || ({})
        statsRank = data.rank || "Unknown"
        statsLevel = data.level || "Unknown"
        statsError = result.ok === true ? "" : (result.message || "Valorant stats unavailable.")
        messageOk = result.ok === true
        message = result.ok === true ? ("Valorant stats OK. Rank: " + statsRank + ". Level: " + statsLevel + ".") : statsError
    }

    function browseInto(field, title) {
        var result = appBridge.browseForFolder(field.text, title)
        if (result.ok === true && result.path && result.path.length > 0) {
            field.text = result.path
            messageOk = true
            message = result.message
        } else if (result.message && result.message.indexOf("cancelled") === -1) {
            messageOk = false
            message = result.message
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        Label { text: "Configuration"; color: theme.text; font.pixelSize: 24; font.bold: true }

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
                        spacing: 10

                        SettingRow {
                            label: "Watch folder"
                            theme: root.theme
                            ModernField { id: watchField; placeholderText: "Select your clips folder"; theme: root.theme }
                            SmallButton { text: root.width < 620 ? "..." : "Browse"; theme: root.theme; onClicked: browseInto(watchField, "Select clips watch folder") }
                            StatusBadge { ok: setup.watchFolderOk === true; text: setup.watchFolderOk === true ? "OK" : "Missing"; theme: root.theme }
                        }

                        SettingRow {
                            label: "Uploaded folder"
                            theme: root.theme
                            ModernField { id: uploadedField; placeholderText: "Select archive/uploaded folder"; theme: root.theme }
                            SmallButton { text: root.width < 620 ? "..." : "Browse"; theme: root.theme; onClicked: browseInto(uploadedField, "Select uploaded/archive folder") }
                            StatusBadge { ok: setup.uploadedFolderOk === true; text: setup.uploadedFolderOk === true ? "OK" : "Missing"; theme: root.theme }
                        }

                        SettingRow {
                            label: "Start with Windows"
                            theme: root.theme
                            SwitchPill {
                                id: startupToggle
                                theme: root.theme
                                text: checked ? "On" : "Off"
                                enabled: setup.startupSupported !== false
                            }
                            Label {
                                visible: setup.startupSupported === false || (setup.startupMessage || "").indexOf("Error") >= 0
                                text: setup.startupSupported === false ? "Unsupported on this OS" : setup.startupMessage
                                color: theme.warning
                                font.pixelSize: 11
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                        }

                        SettingRow {
                            label: "Discord webhook"
                            theme: root.theme
                            ModernField { id: webhookField; echoMode: TextInput.PasswordEchoOnEdit; placeholderText: "https://discord.com/api/webhooks/..."; theme: root.theme }
                            Item { Layout.preferredWidth: 78 }
                            StatusBadge { ok: setup.webhookOk === true; text: setup.webhookOk === true ? "OK" : "Missing"; theme: root.theme }
                        }

                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: theme.border; Layout.topMargin: 4; Layout.bottomMargin: 2 }

                        SettingRow {
                            label: "FFmpeg"
                            theme: root.theme
                            Label {
                                text: setup.ffmpegDisplay || "Bundled FFmpeg: Missing"
                                color: theme.text
                                font.pixelSize: 13
                                Layout.fillWidth: true
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                            StatusBadge { ok: setup.ffmpegOk === true; text: setup.ffmpegOk === true ? "OK" : "Missing"; theme: root.theme }
                        }

                        Label {
                            text: setup.ffmpegOk === true ? (setup.ffmpegResolvedPath || "Bundled FFmpeg is available.") : "Expected bundled path: app/ffmpeg/bin/ffmpeg.exe"
                            color: theme.muted
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                            Layout.leftMargin: 130
                        }

                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: theme.border; Layout.topMargin: 4; Layout.bottomMargin: 2 }

                        SettingRow {
                            label: "Use Valorant stats"
                            theme: root.theme
                            SwitchPill { id: useStatsToggle; theme: root.theme; text: checked ? "On" : "Off" }
                            Item { Layout.fillWidth: true }
                        }

                        Label {
                            visible: !useStatsToggle.checked
                            text: "Stats are off. Discord uploads will not call Henrik, and Riot/Henrik fields can stay empty."
                            color: theme.muted
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                            Layout.leftMargin: 130
                        }

                        SettingRow {
                            visible: useStatsToggle.checked
                            label: "Riot username"
                            theme: root.theme
                            ModernField { id: riotNameField; theme: root.theme }
                            Item { Layout.preferredWidth: 78 }
                            StatusBadge { ok: riotNameField.text.length > 0; text: riotNameField.text.length > 0 ? "OK" : "Missing"; theme: root.theme }
                        }

                        SettingRow {
                            visible: useStatsToggle.checked
                            label: "Riot tagline"
                            theme: root.theme
                            ModernField { id: riotTagField; theme: root.theme }
                            Item { Layout.preferredWidth: 78 }
                            StatusBadge { ok: riotTagField.text.length > 0; text: riotTagField.text.length > 0 ? "OK" : "Missing"; theme: root.theme }
                        }

                        SettingRow {
                            visible: useStatsToggle.checked
                            label: "Valorant region"
                            theme: root.theme
                            AppComboBox {
                                id: regionBox
                                objectName: "regionBox"
                                theme: root.theme
                                textRole: "label"
                                valueRole: "value"
                                model: [
                                    { label: "AP", value: "ap" },
                                    { label: "EU", value: "eu" },
                                    { label: "NA", value: "na" },
                                    { label: "KR", value: "kr" },
                                    { label: "LATAM", value: "latam" },
                                    { label: "BR", value: "br" }
                                ]
                            }
                            Item { Layout.fillWidth: true }
                        }

                        SettingRow {
                            visible: useStatsToggle.checked
                            label: "Henrik API key"
                            theme: root.theme
                            ModernField { id: henrikField; echoMode: TextInput.PasswordEchoOnEdit; placeholderText: "Required when stats are on"; theme: root.theme }
                            Item { Layout.preferredWidth: 78 }
                            StatusBadge { ok: setup.henrikOk === true; text: setup.henrikOk === true ? "OK" : "Missing"; theme: root.theme }
                        }

                        Rectangle {
                            visible: useStatsToggle.checked
                            Layout.fillWidth: true
                            Layout.preferredHeight: statsError.length > 0 ? 138 : 112
                            radius: 10
                            color: theme.panelSoft
                            border.color: theme.border
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 4
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "Valorant stats preview"; color: theme.text; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true }
                                    SmallButton { text: "Test Valorant Stats"; theme: root.theme; onClicked: testStats() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "Rank:"; color: theme.muted; font.pixelSize: 12; Layout.preferredWidth: 46 }
                                    Label { text: statsRank; color: theme.text; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "Level:"; color: theme.muted; font.pixelSize: 12; Layout.preferredWidth: 46 }
                                    Label { text: statsLevel; color: theme.text; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                                Label { visible: statsError.length > 0; text: "Error: " + statsError; color: theme.danger; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                            }
                        }
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    SmallButton { text: "Save Configuration"; theme: root.theme; primary: true; onClicked: save() }
                    SmallButton { text: "Test Webhook"; theme: root.theme; onClicked: { var r = appBridge.testWebhook(); messageOk = r.ok; message = r.message; load() } }
                    SmallButton { text: "Test FFmpeg"; theme: root.theme; onClicked: { var r = appBridge.testFfmpeg(); messageOk = r.ok; message = r.message; load() } }
                    SmallButton { text: "Validate Folders"; theme: root.theme; onClicked: { var r = appBridge.validateFolders(); messageOk = r.ok; message = r.message; load() } }
                }

                Label {
                    text: message
                    visible: message.length > 0
                    color: messageOk ? theme.accent : theme.danger
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                    Layout.fillWidth: true
                }
            }
        }
    }

    component SettingRow: RowLayout {
        property string label
        property var theme
        default property alias rowContent: slot.data
        Layout.fillWidth: true
        spacing: 8
        Label {
            text: parent.label
            color: theme.muted
            font.pixelSize: 12
            Layout.preferredWidth: root.width < 620 ? 96 : 122
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        RowLayout { id: slot; Layout.fillWidth: true; spacing: 8 }
    }

    component ModernField: TextField {
        property var theme
        implicitHeight: 34
        Layout.preferredWidth: root.width < 620 ? 205 : 320
        Layout.maximumWidth: root.width < 620 ? 215 : 340
        Layout.minimumWidth: 120
        Layout.fillWidth: false
        color: theme.text
        placeholderTextColor: "#697282"
        selectedTextColor: theme.bg
        selectionColor: theme.accent
        font.pixelSize: 12
        leftPadding: 10
        rightPadding: 10
        background: Rectangle {
            radius: 8
            color: theme.field
            border.color: parent.activeFocus ? theme.accent : theme.border
        }
    }


    component SwitchPill: Button {
        property var theme
        checkable: true
        implicitHeight: 32
        implicitWidth: 84
        hoverEnabled: true
        contentItem: Text { text: parent.text; color: "#ffffff"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 16; color: parent.checked ? theme.accent : "#323946" }
    }

    component SmallButton: Button {
        property var theme
        property bool primary: false
        implicitHeight: 34
        implicitWidth: Math.max(contentItem.implicitWidth + 14, root.width < 620 ? 42 : 70)
        hoverEnabled: true
        contentItem: Text { text: parent.text; color: "#ffffff"; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 8; color: parent.primary ? (parent.hovered ? "#59c4a3" : theme.accent) : (parent.hovered ? "#2b3442" : theme.panelSoft); border.color: parent.primary ? "transparent" : theme.border }
    }

    component StatusBadge: Rectangle {
        property bool ok: false
        property bool optional: false
        property string text
        property var theme
        Layout.preferredWidth: root.width < 620 ? 38 : 64
        Layout.preferredHeight: 28
        radius: 14
        color: ok ? "#25463d" : (optional ? "#3b3424" : "#48282b")
        Label { anchors.centerIn: parent; text: root.width < 620 && !parent.ok ? "!" : parent.text; color: ok ? theme.accent : (parent.optional ? theme.warning : theme.danger); font.pixelSize: 10; font.bold: true }
    }
}
