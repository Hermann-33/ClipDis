from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.secrets import redact


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ClipDis"


@dataclass(frozen=True)
class StartupResult:
    ok: bool
    supported: bool
    enabled: bool
    message: str
    command: str = ""


def is_supported() -> bool:
    return os.name == "nt"


def get_startup_command() -> str:
    """Return the HKCU Run command for source and PyInstaller modes."""
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable])
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    return subprocess.list2cmdline([sys.executable, str(main_path)])


def is_startup_enabled() -> bool:
    if not is_supported():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable_startup() -> StartupResult:
    if not is_supported():
        return StartupResult(False, False, False, "Start with Windows is only supported on Windows.")
    command = get_startup_command()
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        return StartupResult(True, True, True, "ClipDis will start with Windows.", command)
    except OSError as exc:
        return StartupResult(False, True, is_startup_enabled(), f"Could not enable startup: {redact(str(exc))}", command)


def disable_startup() -> StartupResult:
    if not is_supported():
        return StartupResult(False, False, False, "Start with Windows is only supported on Windows.")
    command = get_startup_command()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        return StartupResult(True, True, False, "ClipDis startup entry removed.", command)
    except OSError as exc:
        return StartupResult(False, True, is_startup_enabled(), f"Could not disable startup: {redact(str(exc))}", command)
