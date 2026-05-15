import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: root
    width: 960
    height: 620
    minimumWidth: 760
    minimumHeight: 520
    visible: true
    title: "ClipDis"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint
    color: theme.bg

    property var appBridge: bridge
    property bool settingsOpen: false
    property int settingsTabIndex: 0

    function openSettings(tabIndex) {
        settingsTabIndex = Math.max(0, Math.min(2, tabIndex || 0))
        settingsOpen = true
    }

    onClosing: function(close) {
        close.accepted = false
        root.hide()
    }

    QtObject {
        id: theme
        property color bg: "#0f1216"
        property color sidebar: "#151922"
        property color panel: "#1b2029"
        property color panelSoft: "#222936"
        property color field: "#11151c"
        property color border: "#2c3542"
        property color text: "#edf1f5"
        property color muted: "#99a4b3"
        property color accent: "#4fb595"
        property color warning: "#d7ad5c"
        property color danger: "#e26d6d"
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TitleBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            theme: theme
            windowRef: root
            appBridge: root.appBridge
            onSettingsRequested: root.openSettings(0)
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: theme.bg

            Dashboard {
                id: dashboardPage
                anchors.fill: parent
                anchors.margins: 16
                appBridge: root.appBridge
                theme: theme
                navigate: function(page) {
                    if (page === "Settings")
                        root.openSettings(0)
                    else if (page === "Performance")
                        root.openSettings(1)
                    else if (page === "Logs")
                        root.openSettings(2)
                }
                onVisibleChanged: if (visible) silentRefresh()
            }
        }
    }

    Rectangle {
        id: settingsOverlay
        anchors.fill: parent
        visible: root.settingsOpen
        z: 20
        color: "#aa080b10"
        opacity: visible ? 1 : 0

        MouseArea { anchors.fill: parent; onClicked: root.settingsOpen = false }

        Rectangle {
            id: settingsCard
            width: Math.min(parent.width - 40, 880)
            height: Math.min(parent.height - 40, 560)
            anchors.centerIn: parent
            radius: 16
            color: theme.panel
            border.color: theme.border

            MouseArea { anchors.fill: parent; onClicked: function(mouse) { mouse.accepted = true } }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Label {
                        text: "Settings"
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        Layout.fillWidth: true
                    }
                    TopButton {
                        text: "Close"
                        theme: theme
                        secondary: true
                        onClicked: root.settingsOpen = false
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TabButtonLite { text: "Configuration"; active: root.settingsTabIndex === 0; theme: theme; onClicked: root.settingsTabIndex = 0 }
                    TabButtonLite { text: "Performance"; active: root.settingsTabIndex === 1; theme: theme; onClicked: root.settingsTabIndex = 1 }
                    TabButtonLite { text: "Logs"; active: root.settingsTabIndex === 2; theme: theme; onClicked: root.settingsTabIndex = 2 }
                    Item { Layout.fillWidth: true }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: root.settingsTabIndex

                    Settings {
                        appBridge: root.appBridge
                        theme: theme
                        navigate: function(page) {
                            if (page === "Dashboard")
                                root.settingsOpen = false
                        }
                        onVisibleChanged: if (visible) load()
                    }
                    Performance {
                        appBridge: root.appBridge
                        theme: theme
                        navigate: function(page) {
                            if (page === "Dashboard")
                                root.settingsOpen = false
                        }
                        onVisibleChanged: if (visible) load()
                    }
                    Logs {
                        appBridge: root.appBridge
                        theme: theme
                        navigate: function(page) {
                            if (page === "Dashboard")
                                root.settingsOpen = false
                        }
                        onVisibleChanged: if (visible) refresh()
                    }
                }
            }
        }
    }

    ResizeHandle { edge: Qt.LeftEdge; anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 6; cursorShape: Qt.SizeHorCursor }
    ResizeHandle { edge: Qt.RightEdge; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 6; cursorShape: Qt.SizeHorCursor }
    ResizeHandle { edge: Qt.TopEdge; anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right; height: 6; cursorShape: Qt.SizeVerCursor }
    ResizeHandle { edge: Qt.BottomEdge; anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 6; cursorShape: Qt.SizeVerCursor }
    ResizeHandle { edge: Qt.LeftEdge | Qt.TopEdge; anchors.left: parent.left; anchors.top: parent.top; width: 10; height: 10; cursorShape: Qt.SizeFDiagCursor }
    ResizeHandle { edge: Qt.RightEdge | Qt.TopEdge; anchors.right: parent.right; anchors.top: parent.top; width: 10; height: 10; cursorShape: Qt.SizeBDiagCursor }
    ResizeHandle { edge: Qt.LeftEdge | Qt.BottomEdge; anchors.left: parent.left; anchors.bottom: parent.bottom; width: 10; height: 10; cursorShape: Qt.SizeBDiagCursor }
    ResizeHandle { edge: Qt.RightEdge | Qt.BottomEdge; anchors.right: parent.right; anchors.bottom: parent.bottom; width: 10; height: 10; cursorShape: Qt.SizeFDiagCursor }


    component TopButton: Button {
        id: buttonRoot
        property var theme
        property bool active: false
        property bool secondary: false
        property bool square: false
        property string tooltip: ""
        implicitHeight: 34
        implicitWidth: square ? 38 : Math.max(contentItem.implicitWidth + 22, 76)
        hoverEnabled: true
        ToolTip.visible: hovered && tooltip.length > 0
        ToolTip.text: tooltip
        contentItem: Text {
            text: parent.text
            color: parent.enabled ? "#ffffff" : "#697282"
            font.pixelSize: parent.square ? 17 : 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 9
            color: !buttonRoot.enabled ? "#202631" : (buttonRoot.active ? theme.accent : (buttonRoot.secondary ? (buttonRoot.hovered ? "#2b3442" : "#222936") : (buttonRoot.hovered ? "#59c4a3" : theme.accent)))
            border.color: buttonRoot.secondary ? theme.border : "transparent"
        }
    }

    component ResizeHandle: MouseArea {
        property int edge: 0
        visible: root.visibility !== Window.Maximized && !root.settingsOpen
        z: 10
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        onPressed: function(mouse) {
            if (mouse.button === Qt.LeftButton && root.startSystemResize)
                root.startSystemResize(edge)
        }
    }


    component TabButtonLite: Button {
        id: tabRoot
        property var theme
        property bool active: false
        implicitHeight: 34
        implicitWidth: Math.max(contentItem.implicitWidth + 24, 110)
        hoverEnabled: true
        contentItem: Text {
            text: parent.text
            color: tabRoot.active ? "#ffffff" : theme.muted
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 9
            color: tabRoot.active ? "#2d685c" : (tabRoot.hovered ? "#202734" : "transparent")
            border.color: tabRoot.active ? "transparent" : theme.border
        }
    }
}
