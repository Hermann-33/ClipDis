from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import requests

from app.config import AppConfig, WatchFolderProfile, get_watch_folder_profile, path_is_within
from app.secrets import DISCORD_WEBHOOK_KEY, HENRIK_API_KEY, get_secret, redact
from app.valorant_stats import fetch_valorant_stats


logger = logging.getLogger(__name__)

_WEBHOOK_RE = re.compile(r"^https://(?:discord(?:app)?\.com)/api/webhooks/\d+/[A-Za-z0-9_\-]+/?$")
DISCORD_CONTENT_LIMIT = 2000


@dataclass(frozen=True)
class DiscordClassification:
    success: bool
    retryable: bool
    category: str
    message: str
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class DiscordUploadResult:
    ok: bool
    category: str
    message: str
    response_code: int | None = None
    message_id: str | None = None
    attempts: int = 0
    retryable: bool = False


class DiscordUploadError(Exception):
    def __init__(self, result: DiscordUploadResult) -> None:
        super().__init__(result.message)
        self.result = result


def validate_webhook_url(webhook_url: str | None) -> tuple[bool, str]:
    if not webhook_url:
        return False, "Discord webhook is not configured."
    if not _WEBHOOK_RE.match(webhook_url.strip()):
        return False, "Discord webhook URL is not valid."
    return True, "Discord webhook URL looks valid."


def redact_webhook_url(webhook_url: str | None) -> str:
    if not webhook_url:
        return "Not configured"
    value = webhook_url.strip()
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"https://discord.com/api/webhooks/...{tail}"


def build_webhook_payload(
    job: dict[str, Any],
    config: AppConfig,
    stats: dict[str, Any] | None = None,
    profile: WatchFolderProfile | None = None,
) -> str:
    profile = profile or _resolve_job_profile(job, config)
    sections: list[str] = []

    if profile and profile.caption_enabled:
        caption = _normalize_caption(profile.caption_text)
        if caption:
            sections.append(caption)

    stats_enabled = bool(profile.show_valorant_stats) if profile else bool(getattr(config, "use_henrik_stats", False))
    if stats_enabled:
        if stats and stats.get("available"):
            rank = stats.get("rank") or "Unknown"
            level = stats.get("account_level")
            if level is None:
                level = stats.get("level")
            sections.append(
                f"Rank: **{_discord_bold_value(rank)}**\n"
                f"Level: **{_discord_bold_value(level if level is not None else 'Unknown')}**"
            )
        else:
            sections.append("Valorant stats unavailable.")

    return "\n\n".join(section for section in sections if section)


def upload_file_to_webhook(
    webhook_url: str,
    file_path: str | Path,
    content: str,
    timeout_seconds: float,
    wait: bool = True,
) -> requests.Response:
    params = {"wait": "true"} if wait else None
    payload: dict[str, Any] = {"allowed_mentions": {"parse": []}}
    if content:
        payload["content"] = content
    with Path(file_path).open("rb") as handle:
        files = {"file": (Path(file_path).name, handle, "video/mp4")}
        # Discord accepts payload_json alongside multipart files. Keeping
        # allowed_mentions empty prevents arbitrary profile captions from
        # pinging @everyone, users, or roles.
        data = {"payload_json": json.dumps(payload, separators=(",", ":"))}
        return requests.post(webhook_url, params=params, data=data, files=files, timeout=timeout_seconds)


def classify_discord_response(
    status_code: int,
    response_text: str | None,
    headers: dict[str, Any] | requests.structures.CaseInsensitiveDict[str] | None,
) -> DiscordClassification:
    headers = headers or {}
    if status_code in (200, 204):
        return DiscordClassification(True, False, "success", "Discord upload succeeded.")
    if status_code == 400:
        return DiscordClassification(False, False, "discord_bad_request", _safe_response_summary(response_text))
    if status_code in (401, 403):
        return DiscordClassification(False, False, "discord_webhook_forbidden_or_invalid", "Discord webhook is forbidden or invalid.")
    if status_code == 404:
        return DiscordClassification(False, False, "discord_webhook_not_found", "Discord webhook was not found.")
    if status_code == 413:
        return DiscordClassification(False, False, "discord_payload_too_large", "Discord rejected the payload as too large.")
    if status_code == 429:
        retry_after = parse_retry_after(headers, response_text)
        return DiscordClassification(False, True, "discord_rate_limited", "Discord rate limit hit.", retry_after)
    if 500 <= status_code <= 599:
        return DiscordClassification(False, True, "discord_server_error", f"Discord server error HTTP {status_code}.")
    return DiscordClassification(False, False, "discord_unexpected_response", f"Unexpected Discord HTTP {status_code}.")


def upload_processed_job(
    job: dict[str, Any],
    config: AppConfig,
    secrets: dict[str, str] | None = None,
    upload_func: Callable[..., Any] = upload_file_to_webhook,
    sleep_func: Callable[[float], None] = time.sleep,
) -> DiscordUploadResult:
    webhook_url = (secrets or {}).get(DISCORD_WEBHOOK_KEY) or get_secret(DISCORD_WEBHOOK_KEY)
    valid, validation_message = validate_webhook_url(webhook_url)
    if not valid:
        category = "discord_webhook_missing" if not webhook_url else "discord_webhook_invalid"
        return DiscordUploadResult(False, category, validation_message)

    compressed_path = Path(str(job.get("compressed_path") or ""))
    if not compressed_path.is_file():
        return DiscordUploadResult(False, "compressed_file_missing", "Compressed file is missing.")
    compressed_size = compressed_path.stat().st_size
    if compressed_size <= 0:
        return DiscordUploadResult(False, "compressed_file_missing", "Compressed file is empty.")
    max_bytes = int(config.max_upload_size_mb) * 1024 * 1024
    if compressed_size > max_bytes:
        return DiscordUploadResult(
            False,
            "discord_payload_too_large",
            f"Compressed file is too large for configured limit: {compressed_size} > {max_bytes}.",
        )

    profile = _resolve_job_profile(job, config)
    stats_enabled = bool(profile.show_valorant_stats) if profile else bool(getattr(config, "use_henrik_stats", False))
    stats = None
    message_mode = "no_stats_disabled"
    if stats_enabled:
        logger.info(
            "Discord upload stats config for job %s: enabled=True profile_id=%s name_present=%s tag_present=%s region=%s api_key_present=%s.",
            job.get("id"),
            profile.id if profile else "legacy",
            bool((config.riot_username or "").strip()),
            bool((config.riot_tagline or "").strip()),
            (config.valorant_region or "ap").strip().lower(),
            bool(get_secret(HENRIK_API_KEY)),
        )
        # fetch_valorant_stats retains a legacy global enable guard. Supply a
        # temporary enabled view when this specific profile has stats enabled.
        stats_config = replace(config, use_henrik_stats=True)
        stats_result = fetch_valorant_stats(stats_config)
        if stats_result.available:
            message_mode = "stats_success" if stats_result.category == "success" else "stats_partial"
        else:
            message_mode = "stats_unavailable"
            logger.info("Valorant stats unavailable for job %s: %s", job.get("id"), stats_result.category)
        stats = stats_result.to_payload()

    content = build_webhook_payload(job, config, stats, profile)
    if len(content) > DISCORD_CONTENT_LIMIT:
        return DiscordUploadResult(
            False,
            "discord_content_too_long",
            f"Discord message content exceeds {DISCORD_CONTENT_LIMIT} characters.",
            retryable=False,
        )
    logger.info(
        "Discord upload message mode for job %s: %s caption_enabled=%s profile_id=%s.",
        job.get("id"),
        message_mode,
        bool(profile.caption_enabled) if profile else False,
        profile.id if profile else "legacy",
    )
    max_attempts = int(config.discord_max_retries) + 1
    last_result = DiscordUploadResult(False, "discord_upload_failed", "Discord upload failed.", attempts=0, retryable=True)

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Uploading job %s to Discord, attempt %s/%s, file=%s, size=%s.",
            job.get("id"),
            attempt,
            max_attempts,
            compressed_path,
            compressed_size,
        )
        try:
            response = upload_func(
                webhook_url,
                compressed_path,
                content,
                float(config.discord_timeout_seconds),
                bool(config.discord_wait_for_response),
            )
            classification = classify_discord_response(response.status_code, getattr(response, "text", ""), response.headers)
            logger.info("Discord response for job %s: HTTP %s category=%s.", job.get("id"), response.status_code, classification.category)
            message_id = _message_id_from_response(response) if classification.success else None
            if classification.success:
                return DiscordUploadResult(True, "success", "Discord upload succeeded.", response.status_code, message_id, attempt)
            last_result = DiscordUploadResult(
                False,
                classification.category,
                classification.message,
                response.status_code,
                attempts=attempt,
                retryable=classification.retryable,
            )
            if not classification.retryable or attempt >= max_attempts:
                return last_result
            sleep_func(_retry_delay(config, attempt, classification.retry_after_seconds))
        except requests.Timeout as exc:
            last_result = DiscordUploadResult(False, "discord_timeout", redact(str(exc)), attempts=attempt, retryable=True)
        except requests.ConnectionError as exc:
            last_result = DiscordUploadResult(False, "discord_network_error", redact(str(exc)), attempts=attempt, retryable=True)
        except requests.RequestException as exc:
            last_result = DiscordUploadResult(False, "discord_request_error", redact(str(exc)), attempts=attempt, retryable=True)
        except Exception as exc:
            last_result = DiscordUploadResult(False, "discord_unexpected_error", redact(str(exc)), attempts=attempt, retryable=True)

        logger.warning("Discord upload attempt %s failed for job %s: %s", attempt, job.get("id"), last_result.category)
        if attempt < max_attempts:
            sleep_func(_retry_delay(config, attempt, None))

    return last_result


def parse_retry_after(headers: dict[str, Any], response_json_or_text: Any = None) -> float | None:
    value = None
    for key in ("Retry-After", "retry-after"):
        if key in headers:
            value = headers[key]
            break
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    if response_json_or_text:
        try:
            data = response_json_or_text if isinstance(response_json_or_text, dict) else json.loads(str(response_json_or_text))
            if "retry_after" in data:
                return max(0.0, float(data["retry_after"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


def _retry_delay(config: AppConfig, attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(float(config.discord_retry_max_seconds), retry_after)
    base = float(config.discord_retry_base_seconds)
    delay = base * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0, min(base, 1.0)) if base > 0 else 0.0
    return min(float(config.discord_retry_max_seconds), delay + jitter)


def _message_id_from_response(response: requests.Response) -> str | None:
    try:
        data = response.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    message_id = data.get("id")
    return str(message_id) if message_id else None


def _safe_response_summary(response_text: str | None, limit: int = 300) -> str:
    if not response_text:
        return "Discord request failed."
    text = redact(str(response_text)).strip()
    return text[:limit]


def _discord_bold_value(value: Any) -> str:
    text = str(value if value is not None else "Unknown").strip() or "Unknown"
    return text.replace("*", "\\*").replace("_", "\\_")


def _normalize_caption(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _resolve_job_profile(job: dict[str, Any], config: AppConfig) -> WatchFolderProfile | None:
    profile_id = str(job.get("watch_folder_id") or "").strip()
    if profile_id:
        profile = get_watch_folder_profile(config, profile_id)
        if profile is not None:
            return profile

    source_path = str(job.get("source_path") or "").strip()
    if source_path:
        matches = [profile for profile in config.watch_folders if profile.path and path_is_within(source_path, profile.path)]
        if len(matches) == 1:
            return matches[0]
    return None
