from __future__ import annotations

import logging
import hashlib
import time
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import quote

import requests

from app.config import AppConfig
from app.secrets import HENRIK_API_KEY, get_secret, redact

logger = logging.getLogger(__name__)

REGIONS = {"ap", "eu", "na", "kr", "latam", "br"}
PLATFORM = "pc"
_CACHE_TTL_SECONDS = 60.0
_CACHE: dict[tuple[str, str, str, str], tuple[float, "ValorantStatsResult"]] = {}


@dataclass(frozen=True)
class ValorantStatsResult:
    ok: bool
    category: str
    message: str
    rank: str | None = None
    account_level: int | None = None
    player_name: str = ""
    player_tag: str = ""
    region: str = ""
    status_code: int | None = None
    rank_category: str = ""
    level_category: str = ""

    @property
    def available(self) -> bool:
        return self.ok and bool(self.rank or self.account_level is not None)

    @property
    def level(self) -> int | None:
        # Backward-compatible alias for older message-building code/tests.
        return self.account_level

    def to_payload(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "rank": self.rank,
            "account_level": self.account_level,
            "level": self.account_level,
            "player_name": self.player_name,
            "player_tag": self.player_tag,
            "region": self.region,
            "category": self.category,
            "message": self.message,
            "status_code": self.status_code,
            "rank_category": self.rank_category,
            "level_category": self.level_category,
        }


def fetch_valorant_stats(config: AppConfig, timeout_seconds: float = 8.0) -> ValorantStatsResult:
    if not getattr(config, "use_henrik_stats", False):
        logger.info("Valorant stats skipped: enabled=False.")
        return ValorantStatsResult(False, "stats_disabled", "Henrik/Valorant stats are disabled.")

    name = (config.riot_username or "").strip()
    tag = (config.riot_tagline or "").strip().lstrip("#")
    region = (config.valorant_region or "ap").strip().lower()
    logger.info(
        "Valorant stats requested: enabled=True name_present=%s tag_present=%s region=%s.",
        bool(name),
        bool(tag),
        region,
    )
    if not name or not tag:
        return ValorantStatsResult(False, "stats_missing_player", "Riot username/tagline are required for stats.")
    if region not in REGIONS:
        return ValorantStatsResult(False, "stats_invalid_region", "Valorant region is invalid.")
    api_key = get_secret(HENRIK_API_KEY)
    logger.info("Valorant stats Henrik key present=%s.", bool(api_key))
    if not api_key:
        return ValorantStatsResult(False, "stats_api_key_missing", "Henrik API key is not configured.")

    cache_key = (region, name.lower(), tag.lower(), hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12])
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] <= _CACHE_TTL_SECONDS:
        return cached[1]

    headers = {"Authorization": api_key}
    rank_result = _fetch_mmr(name, tag, region, headers, timeout_seconds)
    level_result = _fetch_account(name, tag, region, headers, timeout_seconds)
    result = _merge_results(rank_result, level_result, name, tag, region)
    logger.info(
        "Valorant stats result: mmr_attempted=True account_attempted=True mmr_category=%s account_category=%s rank=%s account_level=%s final=%s.",
        rank_result.category,
        level_result.category,
        rank_result.rank or "",
        "" if level_result.account_level is None else level_result.account_level,
        result.category,
    )

    _CACHE[cache_key] = (now, result)
    return result


def clear_valorant_stats_cache() -> None:
    _CACHE.clear()


def _fetch_mmr(name: str, tag: str, region: str, headers: dict[str, str], timeout_seconds: float) -> ValorantStatsResult:
    url = "https://api.henrikdev.xyz/valorant/v3/mmr/{region}/{platform}/{name}/{tag}".format(
        region=quote(region, safe=""),
        platform=PLATFORM,
        name=quote(name, safe=""),
        tag=quote(tag, safe=""),
    )
    response = _safe_get(url, headers, timeout_seconds, "rank")
    if isinstance(response, ValorantStatsResult):
        return response
    return _classify_mmr_response(response)


def _fetch_account(name: str, tag: str, region: str, headers: dict[str, str], timeout_seconds: float) -> ValorantStatsResult:
    url = "https://api.henrikdev.xyz/valorant/v2/account/{name}/{tag}".format(
        name=quote(name, safe=""),
        tag=quote(tag, safe=""),
    )
    response = _safe_get(url, headers, timeout_seconds, "level")
    if isinstance(response, ValorantStatsResult):
        return response
    return _classify_account_response(response, region)


def _safe_get(
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
    kind: str,
) -> requests.Response | ValorantStatsResult:
    try:
        return requests.get(url, headers=headers, timeout=timeout_seconds)
    except requests.Timeout as exc:
        return ValorantStatsResult(False, f"stats_{kind}_timeout", redact(str(exc)))
    except requests.ConnectionError as exc:
        return ValorantStatsResult(False, f"stats_{kind}_network_error", redact(str(exc)))
    except requests.RequestException as exc:
        return ValorantStatsResult(False, f"stats_{kind}_request_error", redact(str(exc)))
    except Exception as exc:
        return ValorantStatsResult(False, f"stats_{kind}_unexpected_error", redact(str(exc)))


def _classify_mmr_response(response: requests.Response) -> ValorantStatsResult:
    status = int(response.status_code)
    if status == 200:
        try:
            data = response.json()
        except ValueError:
            return ValorantStatsResult(False, "stats_rank_invalid_response", "Henrik MMR returned invalid JSON.", status_code=status)
        rank = _extract_rank(data)
        if rank:
            return ValorantStatsResult(True, "success", "Valorant rank fetched.", rank=rank, status_code=status)
        return ValorantStatsResult(False, "stats_rank_missing_field", "Henrik MMR response did not include rank.", status_code=status)
    return _classify_http_status(status, "rank")


def _classify_account_response(response: requests.Response, region: str) -> ValorantStatsResult:
    status = int(response.status_code)
    if status == 200:
        try:
            data = response.json()
        except ValueError:
            return ValorantStatsResult(False, "stats_level_invalid_response", "Henrik account returned invalid JSON.", status_code=status)
        level = _extract_account_level(data)
        player_name, player_tag = _extract_account_identity(data)
        if level is not None:
            return ValorantStatsResult(
                True,
                "success",
                "Valorant account level fetched.",
                account_level=level,
                player_name=player_name,
                player_tag=player_tag,
                region=region,
                status_code=status,
            )
        return ValorantStatsResult(False, "stats_level_missing_field", "Henrik account response did not include account_level.", status_code=status)
    return _classify_http_status(status, "level")


def _classify_http_status(status: int, kind: str) -> ValorantStatsResult:
    if status in (401, 403):
        return ValorantStatsResult(False, f"stats_{kind}_forbidden_or_invalid_key", "Henrik API key is invalid or forbidden.", status_code=status)
    if status == 404:
        return ValorantStatsResult(False, f"stats_{kind}_player_not_found", "Valorant player was not found.", status_code=status)
    if status == 408:
        return ValorantStatsResult(False, f"stats_{kind}_timeout", "Henrik request timed out.", status_code=status)
    if status == 429:
        return ValorantStatsResult(False, f"stats_{kind}_rate_limited", "Henrik rate limit reached.", status_code=status)
    if 500 <= status <= 599:
        return ValorantStatsResult(False, f"stats_{kind}_server_error", f"Henrik server error HTTP {status}.", status_code=status)
    return ValorantStatsResult(False, f"stats_{kind}_unexpected_response", f"Unexpected Henrik HTTP {status}.", status_code=status)


def _merge_results(
    rank_result: ValorantStatsResult,
    level_result: ValorantStatsResult,
    requested_name: str,
    requested_tag: str,
    region: str,
) -> ValorantStatsResult:
    rank = rank_result.rank
    account_level = level_result.account_level
    player_name = level_result.player_name or requested_name
    player_tag = level_result.player_tag or requested_tag
    ok = bool(rank or account_level is not None)
    if ok:
        missing: list[str] = []
        if not rank:
            missing.append("rank unavailable")
        if account_level is None:
            missing.append("level unavailable")
        message = "Valorant stats fetched."
        if missing:
            message = "Valorant stats partially fetched: " + ", ".join(missing) + "."
        return ValorantStatsResult(
            True,
            "success" if not missing else "partial_success",
            message,
            rank=rank,
            account_level=account_level,
            player_name=player_name,
            player_tag=player_tag,
            region=region,
            status_code=rank_result.status_code or level_result.status_code,
            rank_category=rank_result.category,
            level_category=level_result.category,
        )
    categories = [rank_result.category, level_result.category]
    return replace(
        rank_result,
        ok=False,
        category="stats_unavailable",
        message="Valorant stats unavailable.",
        rank_category=categories[0],
        level_category=categories[1],
        player_name=requested_name,
        player_tag=requested_tag,
        region=region,
    )


def _extract_rank(payload: dict[str, Any]) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend([
            data.get("currenttierpatched"),
            data.get("current_tier_patched"),
        ])
        current_data = data.get("current_data")
        if isinstance(current_data, dict):
            candidates.extend([current_data.get("currenttierpatched"), current_data.get("current_tier_patched")])
        current = data.get("current")
        if isinstance(current, dict):
            tier = current.get("tier")
            if isinstance(tier, dict):
                candidates.extend([tier.get("name"), tier.get("patched")])
            candidates.extend([current.get("tier_name"), current.get("rank")])
        peak = data.get("peak")
        if isinstance(peak, dict):
            tier = peak.get("tier")
            if isinstance(tier, dict):
                candidates.append(tier.get("name"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _extract_account_level(payload: dict[str, Any]) -> int | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    candidate: Any = None
    if isinstance(data, dict):
        candidate = data.get("account_level")
    try:
        if candidate is not None:
            return int(candidate)
    except (TypeError, ValueError):
        return None
    return None


def _extract_account_identity(payload: dict[str, Any]) -> tuple[str, str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return "", ""
    name = data.get("name") or data.get("username") or ""
    tag = data.get("tag") or data.get("tagline") or ""
    return str(name) if name else "", str(tag).lstrip("#") if tag else ""
