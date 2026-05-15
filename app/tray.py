from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.qt_runtime import configure_qt_runtime

configure_qt_runtime()

from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PySide6.QtCore import Qt

from app.gui_bridge import GuiBridge


class TrayController:
    def __init__(
        self,
        app: QApplication,
        bridge: GuiBridge,
        open_dashboard: Callable[[], None],
        icon_path: str | Path | None = None,
    ) -> None:
        self.app = app
        self.bridge = bridge
        self.open_dashboard = open_dashboard
        self.tray = QSystemTrayIcon(_load_icon(icon_path), app)
        self.tray.setToolTip("ClipDis")
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

    def show(self) -> None:
        self.tray.show()

    def _build_menu(self) -> None:
        self._add_action("Open Dashboard", self.open_dashboard)
        self.menu.addSeparator()
        self._add_action("Exit", self.bridge.exitApp)

    def _add_action(self, label: str, callback: Callable[[], object]) -> None:
        action = QAction(label, self.menu)
        action.triggered.connect(lambda checked=False: callback())
        self.menu.addAction(action)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_dashboard()


def _load_icon(icon_path: str | Path | None) -> QIcon:
    if icon_path and Path(icon_path).is_file():
        return QIcon(str(icon_path))
    fallback = QPixmap(64, 64)
    fallback.fill(Qt.GlobalColor.transparent)
    painter = QPainter(fallback)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.GlobalColor.white)
    painter.setPen(Qt.GlobalColor.transparent)
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(fallback)
