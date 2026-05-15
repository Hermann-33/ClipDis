from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.config import app_data_dir


SERVICE_NAME = "ValorantClipUploader"
DISCORD_WEBHOOK_KEY = "discord_webhook_url"
HENRIK_API_KEY = "henrik_api_key"
FALLBACK_SECRETS_FILE = "secrets.local.json"

_DISCORD_WEBHOOK_RE = re.compile(
    r"https://discord(?:app)?\.com/api/webhooks/[A-Za-z0-9_\-./]+",
    re.IGNORECASE,
)
_HENRIK_KEY_RE = re.compile(r"HDEV-[A-Za-z0-9-]+", re.IGNORECASE)


def get_secret(name: str) -> str:
    env_value = _env_secret(name)
    if env_value:
        return env_value

    keyring_value = _get_keyring_secret(name)
    if keyring_value:
        return keyring_value

    return _load_fallback_secrets().get(name, "")


def set_secret(name: str, value: str) -> None:
    if _set_keyring_secret(name, value):
        _remove_fallback_secret(name)
        return

    secrets = _load_fallback_secrets()
    if value:
        secrets[name] = value
    else:
        secrets.pop(name, None)
    _save_fallback_secrets(secrets)


def has_secret(name: str) -> bool:
    return bool(get_secret(name))


def secret_backend(name: str) -> str:
    if _env_secret(name):
        return "environment"
    if _get_keyring_secret(name):
        return "keyring"
    if _load_fallback_secrets().get(name):
        return "fallback_file"
    return "none"


def secrets_backend_summary() -> str:
    backends = {secret_backend(name) for name in (DISCORD_WEBHOOK_KEY, HENRIK_API_KEY)}
    if len(backends) == 1:
        return next(iter(backends))
    return "mixed:" + ",".join(sorted(backends))


def redact(value: str) -> str:
    if not value:
        return value
    redacted = _DISCORD_WEBHOOK_RE.sub("[REDACTED_DISCORD_WEBHOOK]", value)
    redacted = _HENRIK_KEY_RE.sub("[REDACTED_HENRIK_API_KEY]", redacted)
    for secret_value in _known_secret_values():
        if secret_value:
            redacted = redacted.replace(secret_value, "[REDACTED_SECRET]")
    return redacted


def fallback_secrets_path() -> Path:
    return app_data_dir() / FALLBACK_SECRETS_FILE


def _env_secret(name: str) -> str:
    env_names = {
        DISCORD_WEBHOOK_KEY: "HERMANN_DISCORD_WEBHOOK_URL",
        HENRIK_API_KEY: "HERMANN_HENRIK_API_KEY",
    }
    return os.getenv(env_names.get(name, ""), "")


def _get_keyring_secret(name: str) -> str:
    try:
        import keyring  # type: ignore

        return keyring.get_password(SERVICE_NAME, name) or ""
    except Exception:
        return ""


def _set_keyring_secret(name: str, value: str) -> bool:
    try:
        import keyring  # type: ignore

        if value:
            keyring.set_password(SERVICE_NAME, name, value)
        else:
            try:
                keyring.delete_password(SERVICE_NAME, name)
            except Exception:
                pass
        return True
    except Exception:
        return False


def _load_fallback_secrets() -> dict[str, str]:
    path = fallback_secrets_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {str(key): str(value) for key, value in raw.items()}


def _save_fallback_secrets(secrets: dict[str, str]) -> None:
    path = fallback_secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(secrets, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _remove_fallback_secret(name: str) -> None:
    secrets = _load_fallback_secrets()
    if name in secrets:
        secrets.pop(name, None)
        _save_fallback_secrets(secrets)


def _known_secret_values() -> list[str]:
    values: list[str] = []
    for name in (DISCORD_WEBHOOK_KEY, HENRIK_API_KEY):
        env_value = _env_secret(name)
        if env_value:
            values.append(env_value)
    values.extend(_load_fallback_secrets().values())
    return values
