from __future__ import annotations

import os
import site
from pathlib import Path


def configure_qt_runtime() -> None:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    candidates = [Path(path) / "PySide6" for path in site.getsitepackages()]
    candidates.append(Path(site.getusersitepackages()) / "PySide6")
    for candidate in candidates:
        if candidate.exists():
            os.add_dll_directory(str(candidate))

