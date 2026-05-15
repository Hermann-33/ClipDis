from __future__ import annotations

import logging
from collections.abc import Callable

from app.qt_runtime import configure_qt_runtime

configure_qt_runtime()

from PySide6.QtCore import QIODevice, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket


logger = logging.getLogger(__name__)


INSTANCE_NAME = "ClipDisSingleInstance"


def notify_existing_instance(name: str = INSTANCE_NAME, message: str = "show", timeout_ms: int = 500) -> bool:
    """Tell an already-running ClipDis instance to show its dashboard."""
    socket = QLocalSocket()
    socket.connectToServer(name, QIODevice.OpenModeFlag.WriteOnly)
    if not socket.waitForConnected(timeout_ms):
        socket.abort()
        return False
    socket.write(message.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


class SingleInstanceServer(QObject):
    def __init__(self, on_show_requested: Callable[[], object], name: str = INSTANCE_NAME) -> None:
        super().__init__()
        self._name = name
        self._on_show_requested = on_show_requested
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_connection)

    def listen(self) -> bool:
        if self._server.listen(self._name):
            logger.info("Single-instance server listening: %s", self._name)
            return True

        # If no peer answered notify_existing_instance(), a leftover local
        # server name can remain after a crash. Remove it once and retry.
        logger.warning("Single-instance listen failed; removing stale server name: %s", self._name)
        QLocalServer.removeServer(self._name)
        if self._server.listen(self._name):
            logger.info("Single-instance server listening after stale cleanup: %s", self._name)
            return True

        logger.error("Could not start single-instance server: %s", self._server.errorString())
        return False

    def close(self) -> None:
        self._server.close()
        QLocalServer.removeServer(self._name)

    def _handle_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(lambda sock=socket: self._read_message(sock))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read_message(socket)

    def _read_message(self, socket: QLocalSocket) -> None:
        message = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip().lower()
        logger.info("Single-instance message received: %s", message or "<empty>")
        if message in {"show", "open", ""}:
            self._on_show_requested()
        socket.disconnectFromServer()
