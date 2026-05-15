from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import logs_dir
from app.secrets import redact


LOG_FILE_NAME = "clipdis.log"


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    log_dir = log_dir or logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = RedactingFormatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    return log_path


def recent_logs(limit: int = 300, log_path: Path | None = None) -> list[str]:
    path = log_path or logs_dir() / LOG_FILE_NAME
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return [redact(line.rstrip("\n")) for line in lines[-limit:]]

