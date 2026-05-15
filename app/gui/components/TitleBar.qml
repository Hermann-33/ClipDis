import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var theme
    property var windowRef
    property var appBridge
    signal settingsRequested()

    height: 44
    color: "#141922"
    border.color: theme.border

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: function(mouse) {
            if (mouse.button === Qt.LeftButton && root.windowRef && root.windowRef.startSystemMove)
                root.windowRef.startSystemMove()
        }
        onDoubleClicked: root.toggleMaximize()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 6
        spacing: 8

        Image {
            source: "../assets/app_icon.png"
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
            fillMode: Image.PreserveAspectFit
            mipmap: true
        }

        Label {
            text: "ClipDis"
            color: theme.text
            font.pixelSize: 14
            font.bold: true
            elide: Text.ElideRight
            Layout.preferredWidth: 110
        }

        Item { Layout.fillWidth: true }

        RowLayout {
            Layout.alignment: Qt.AlignVCenter
            spacing: 6
            Label {
                text: "Developed by Hermann"
                color: theme.muted
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            LinkButton {
                text: "D"
                iconSource: "../assets/discord-white-icon.png"
                tooltip: "Discord"
                theme: root.theme
                onClicked: root.openUrl("https://discord.com/users/697845788851568722")
            }
            LinkButton {
                text: "G"
                iconSource: "../assets/github-white-icon.png"
                tooltip: "GitHub"
                theme: root.theme
                onClicked: root.openUrl("https://github.com/Hermann-33")
            }
        }

        Item { Layout.fillWidth: true }

        IconButton {
            tooltip: "Settings"
            theme: root.theme
            iconSource: "../assets/settings.png"
            onClicked: root.settingsRequested()
        }

        WindowButton {
            text: "−"
            tooltip: "Minimize"
            theme: root.theme
            onClicked: if (root.windowRef) root.windowRef.showMinimized()
        }
        WindowButton {
            text: root.windowRef && root.windowRef.visibility === Window.Maximized ? "❐" : "□"
            tooltip: root.windowRef && root.windowRef.visibility === Window.Maximized ? "Restore" : "Maximize"
            theme: root.theme
            onClicked: root.toggleMaximize()
        }
        WindowButton {
            text: "×"
            tooltip: "Close to tray"
            theme: root.theme
            danger: true
            onClicked: if (root.windowRef) root.windowRef.hide()
        }
    }

    function openUrl(url) {
        if (root.appBridge && root.appBridge.openExternalUrl)
            root.appBridge.openExternalUrl(url)
        else
            Qt.openUrlExternally(url)
    }

    function toggleMaximize() {
        if (!root.windowRef)
            return
        if (root.windowRef.visibility === Window.Maximized)
            root.windowRef.showNormal()
        else
            root.windowRef.showMaximized()
    }

    component WindowButton: Button {
        id: buttonRoot
        property var theme
        property bool danger: false
        property string tooltip: ""
        Layout.preferredWidth: 38
        Layout.preferredHeight: 32
        hoverEnabled: true
        ToolTip.visible: hovered && tooltip.length > 0
        ToolTip.text: tooltip
        contentItem: Text {
            text: parent.text
            color: "#edf1f5"
            font.pixelSize: 16
            font.bold: parent.text === "×"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: buttonRoot.hovered ? (buttonRoot.danger ? theme.danger : "#202734") : "transparent"
            border.color: "transparent"
        }
    }

    component LinkButton: Button {
        id: buttonRoot
        property var theme
        property string tooltip: ""
        property string iconSource: ""
        Layout.preferredWidth: 24
        Layout.preferredHeight: 24
        hoverEnabled: true
        ToolTip.visible: hovered && tooltip.length > 0
        ToolTip.text: tooltip
        contentItem: Item {
            Image {
                anchors.centerIn: parent
                source: buttonRoot.iconSource
                sourceSize.width: 18
                sourceSize.height: 18
                fillMode: Image.PreserveAspectFit
                opacity: buttonRoot.hovered ? 1.0 : 0.82
            }
        }
        background: Rectangle {
            radius: 7
            color: buttonRoot.hovered ? "#202734" : "transparent"
            border.color: buttonRoot.hovered ? theme.border : "transparent"
        }
    }

    component IconButton: Button {
        id: buttonRoot
        property var theme
        property string iconSource: ""
        property string tooltip: ""
        Layout.preferredWidth: 38
        Layout.preferredHeight: 32
        hoverEnabled: true
        ToolTip.visible: hovered && tooltip.length > 0
        ToolTip.text: tooltip
        contentItem: Image {
            source: buttonRoot.iconSource
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 20
            sourceSize.height: 20
            anchors.centerIn: parent
            opacity: buttonRoot.enabled ? 0.88 : 0.45
        }
        background: Rectangle {
            radius: 8
            color: buttonRoot.hovered ? "#202734" : "transparent"
            border.color: buttonRoot.hovered ? theme.border : "transparent"
        }
    }
}
