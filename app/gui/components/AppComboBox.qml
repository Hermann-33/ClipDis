import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ComboBox {
    id: control

    property var theme: ({
        field: "#11151c",
        panelSoft: "#222936",
        border: "#2c3542",
        text: "#edf1f5",
        muted: "#99a4b3",
        accent: "#4fb595"
    })

    implicitWidth: 148
    implicitHeight: 34
    Layout.preferredWidth: 148
    Layout.preferredHeight: 34
    font.pixelSize: 12
    hoverEnabled: true
    spacing: 0
    leftPadding: 10
    rightPadding: 32

    contentItem: Text {
        text: control.displayText
        color: control.enabled ? theme.text : "#697282"
        font.pixelSize: 12
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        leftPadding: 10
        rightPadding: 30
    }

    indicator: Item {
        width: 28
        height: control.height
        x: control.width - width
        y: 0

        Canvas {
            id: chevron
            width: 10
            height: 7
            anchors.centerIn: parent
            rotation: control.popup.visible ? 180 : 0

            Behavior on rotation {
                NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
            }

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.strokeStyle = control.popup.visible || control.hovered ? theme.accent : theme.muted
                ctx.lineWidth = 1.8
                ctx.lineCap = "round"
                ctx.lineJoin = "round"
                ctx.beginPath()
                ctx.moveTo(1, 1.5)
                ctx.lineTo(width / 2, height - 1)
                ctx.lineTo(width - 1, 1.5)
                ctx.stroke()
            }

            Connections {
                target: control
                function onHoveredChanged() { chevron.requestPaint() }
            }

            Connections {
                target: control.popup
                function onVisibleChanged() { chevron.requestPaint() }
            }
        }
    }

    background: Rectangle {
        radius: 8
        color: control.enabled ? theme.field : "#171c25"
        border.width: 1
        border.color: control.popup.visible || control.activeFocus || control.hovered ? theme.accent : theme.border
    }

    delegate: ItemDelegate {
        id: option
        width: control.width - 8
        height: 32
        hoverEnabled: true
        highlighted: control.highlightedIndex === index

        function optionText() {
            if (control.textRole && typeof model !== "undefined" && model[control.textRole] !== undefined)
                return model[control.textRole]
            if (typeof modelData === "object" && modelData !== null && modelData.label !== undefined)
                return modelData.label
            return modelData
        }

        contentItem: Text {
            text: option.optionText()
            color: option.highlighted || option.hovered ? "#ffffff" : theme.text
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            leftPadding: 12
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: 7
            color: option.highlighted || option.hovered ? "#2d685c" : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 6
        width: control.width
        implicitHeight: Math.min(listView.contentHeight + 10, 220)
        padding: 5
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        contentItem: ListView {
            id: listView
            clip: true
            implicitHeight: contentHeight
            boundsBehavior: Flickable.StopAtBounds
            spacing: 2
            currentIndex: control.highlightedIndex
            model: control.popup.visible ? control.delegateModel : null
            ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Rectangle {
            radius: 10
            color: theme.panelSoft
            border.width: 1
            border.color: theme.border
        }
    }
}
