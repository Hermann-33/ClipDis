from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppConfig, work_dir
from app.secrets import redact


logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


@dataclass(frozen=True)
class FfmpegResult:
    ok: bool
    message: str
    category: str = ""
    ffmpeg_path: str = ""
    returncode: int | None = None


@dataclass(frozen=True)
class CompressionResult:
    ok: bool
    output_path: str = ""
    output_size: int | None = None
    attempts: int = 0
    category: str = ""
    message: str = ""
    stderr: str = ""
    returncode: int | None = None


def validate_ffmpeg(ffmpeg_path: str | None) -> FfmpegResult:
    executable = ffmpeg_path.strip() if ffmpeg_path else resolve_ffmpeg_path(AppConfig())
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            startupinfo=_startupinfo(),
            creationflags=_creationflags("normal"),
        )
    except FileNotFoundError:
        return FfmpegResult(False, "FFmpeg executable was not found.", "ffmpeg_missing", executable)
    except subprocess.TimeoutExpired:
        return FfmpegResult(False, "FFmpeg validation timed out.", "ffmpeg_validation_timeout", executable)
    except OSError as exc:
        return FfmpegResult(False, redact(str(exc)), "ffmpeg_validation_error", executable)

    if result.returncode != 0:
        return FfmpegResult(
            False,
            _stderr_summary(result.stderr) or "FFmpeg validation failed.",
            "ffmpeg_validation_error",
            executable,
            result.returncode,
        )
    first_line = (result.stdout or "FFmpeg is available.").splitlines()[0]
    logger.info("FFmpeg validation succeeded: %s", first_line)
    return FfmpegResult(True, first_line, ffmpeg_path=executable, returncode=result.returncode)


def build_ffmpeg_command(input_path: str | Path, output_path: str | Path, config: AppConfig) -> list[str]:
    preset, crf = _mode_settings(config.compression_mode)
    return _build_command(input_path, output_path, config, config.target_resolution, preset, crf)


def compress_clip(input_path: str | Path, output_dir: str | Path | None, config: AppConfig) -> CompressionResult:
    validation = validate_ffmpeg(resolve_ffmpeg_path(config))
    if not validation.ok:
        return CompressionResult(False, category=validation.category, message=validation.message)

    source = Path(input_path)
    if not source.is_file():
        return CompressionResult(False, category="ffmpeg_input_missing", message="Input clip does not exist.")

    requested_target_dir = Path(output_dir) if output_dir else work_dir()
    watch_folder = Path(config.watch_folder).resolve(strict=False) if config.watch_folder else None
    if watch_folder and _is_inside(requested_target_dir, watch_folder):
        logger.warning("Refusing to write FFmpeg output inside watch folder; using app work directory instead.")
        requested_target_dir = work_dir()

    target_result = _prepare_output_dir(requested_target_dir)
    if not target_result.ok:
        return CompressionResult(False, category=target_result.category, message=target_result.message)
    target_dir = target_result.path
    max_bytes = int(config.max_upload_size_mb) * 1024 * 1024
    attempts = _attempt_plan(config)
    last_error = CompressionResult(False, category="ffmpeg_failed", message="FFmpeg did not run.")

    for attempt_number, attempt in enumerate(attempts, start=1):
        output_path = _unique_output_path(source, target_dir, attempt_number)
        command = _build_command(
            source,
            output_path,
            config,
            attempt["resolution"],
            attempt["preset"],
            attempt["crf"],
        )
        logger.info("Starting FFmpeg attempt %s for %s -> %s", attempt_number, source, output_path)
        logger.debug("FFmpeg command: %s", [redact(part) for part in command])
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=None,
                startupinfo=_startupinfo(),
                creationflags=_creationflags(config.ffmpeg_priority),
            )
        except FileNotFoundError:
            return CompressionResult(False, attempts=attempt_number, category="ffmpeg_missing", message="FFmpeg executable was not found.")
        except OSError as exc:
            return CompressionResult(
                False,
                attempts=attempt_number,
                category="ffmpeg_launch_error",
                message=_concise_ffmpeg_message("ffmpeg_launch_error", str(exc)),
            )

        stderr_detail = _stderr_summary(result.stderr, limit=4000)
        logger.info("FFmpeg attempt %s finished with return code %s.", attempt_number, result.returncode)
        if result.returncode != 0:
            cleanup_temp_file(output_path)
            category = classify_ffmpeg_error(result.returncode, result.stderr)
            logger.warning("FFmpeg failed for %s: %s", source, stderr_detail)
            last_error = CompressionResult(
                False,
                attempts=attempt_number,
                category=category,
                message=_concise_ffmpeg_message(category, result.stderr),
                stderr=stderr_detail,
                returncode=result.returncode,
            )
            break

        if not output_path.exists() or output_path.stat().st_size <= 0:
            cleanup_temp_file(output_path)
            last_error = CompressionResult(
                False,
                attempts=attempt_number,
                category="ffmpeg_no_output",
                message="FFmpeg completed but did not create a usable output.",
                returncode=result.returncode,
            )
            break

        output_size = output_path.stat().st_size
        logger.info("FFmpeg output size: %s bytes.", output_size)
        if output_size <= max_bytes:
            return CompressionResult(True, str(output_path), output_size, attempt_number, message="Compression succeeded.")

        cleanup_temp_file(output_path)
        last_error = CompressionResult(
            False,
            attempts=attempt_number,
            category="ffmpeg_output_too_large",
            message=f"Compressed output is too large: {output_size} bytes > {max_bytes} bytes.",
            output_size=output_size,
            returncode=result.returncode,
        )

    return last_error


def probe_video(input_path: str | Path) -> dict[str, Any]:
    return {"path": str(input_path), "duration": get_video_duration(input_path)}


def get_video_duration(input_path: str | Path) -> float | None:
    return None


def get_bundle_base_dir() -> Path:
    """Return the app bundle base for source and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / "app"
            if candidate.exists():
                return candidate
            return Path(meipass)
    return Path(__file__).resolve().parent


def get_bundled_ffmpeg_path() -> Path:
    return get_bundle_base_dir() / "ffmpeg" / "bin" / "ffmpeg.exe"


def get_bundled_ffprobe_path() -> Path:
    return get_bundle_base_dir() / "ffmpeg" / "bin" / "ffprobe.exe"


def resolve_ffmpeg_path(config: AppConfig | None = None) -> str:
    """Resolve the FFmpeg executable used by the app.

    Normal users always use the bundled executable. A legacy custom path is
    kept only for hidden development override scenarios and is not exposed in
    the UI.
    """
    config = config or AppConfig()
    if (
        os.getenv("CLIPBOT_ALLOW_CUSTOM_FFMPEG") == "1"
        and getattr(config, "ffmpeg_source_mode", "bundled") == "custom"
        and getattr(config, "ffmpeg_path", "")
    ):
        return str(config.ffmpeg_path).strip()
    return str(get_bundled_ffmpeg_path())


def classify_ffmpeg_error(returncode: int, stderr: str | None) -> str:
    text = (stderr or "").lower()
    output_error = "error opening output file" in text or "error opening output files" in text
    input_error = "error opening input" in text or "error opening input file" in text

    if output_error and "permission denied" in text:
        return "ffmpeg_output_permission_error"
    if input_error and "permission denied" in text:
        return "ffmpeg_input_permission_error"
    if output_error and ("no such file or directory" in text or "cannot find" in text):
        return "ffmpeg_output_missing_or_invalid"
    if output_error:
        return "ffmpeg_output_error"
    if input_error and ("no such file or directory" in text or "cannot find" in text):
        return "ffmpeg_input_missing"
    if "no such file or directory" in text or "cannot find" in text:
        return "ffmpeg_input_missing"
    if "invalid data" in text or "moov atom not found" in text:
        return "ffmpeg_invalid_input"
    if "permission denied" in text:
        return "ffmpeg_output_permission_error" if output_error else "ffmpeg_input_permission_error"
    return "ffmpeg_failed"


def cleanup_temp_file(path: str | Path) -> None:
    candidate = Path(path)
    try:
        if candidate.exists() and _is_inside(candidate, work_dir()):
            candidate.unlink()
    except OSError as exc:
        logger.warning("Could not clean temp output %s: %s", candidate, redact(str(exc)))


def _build_command(
    input_path: str | Path,
    output_path: str | Path,
    config: AppConfig,
    resolution: str,
    preset: str,
    crf: int,
) -> list[str]:
    executable = resolve_ffmpeg_path(config)
    scale = "scale=-2:1080" if resolution == "1080p" else "scale=-2:720"
    command = [
        executable,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
    ]
    if config.ffmpeg_threads in {"1", "2"}:
        command.extend(["-threads", config.ffmpeg_threads])
    command.append(str(output_path))
    return command


def _attempt_plan(config: AppConfig) -> list[dict[str, Any]]:
    preset, crf = _mode_settings(config.compression_mode)
    attempts = [{"resolution": config.target_resolution, "preset": preset, "crf": crf}]
    if config.target_resolution == "1080p":
        attempts.append({"resolution": "720p", "preset": "slow", "crf": max(crf + 2, 32)})
    attempts.append({"resolution": "720p", "preset": "slow", "crf": max(crf + 4, 34)})
    return attempts[: int(config.max_ffmpeg_attempts)]


def _mode_settings(mode: str) -> tuple[str, int]:
    if mode == "fast":
        return "veryfast", 30
    if mode == "smallest":
        return "slow", 32
    return "medium", 28


def _unique_output_path(source: Path, output_dir: Path, attempt_number: int) -> Path:
    stem = _safe_output_stem(source.stem)
    return output_dir / f"{stem}_{uuid.uuid4().hex[:12]}_attempt{attempt_number}.mp4"


@dataclass(frozen=True)
class _OutputDirResult:
    ok: bool
    path: Path
    category: str = ""
    message: str = ""


def _prepare_output_dir(output_dir: Path) -> _OutputDirResult:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create FFmpeg work directory %s: %s", output_dir, redact(str(exc)))
        return _OutputDirResult(False, output_dir, "ffmpeg_workdir_unwritable", f"Could not create FFmpeg work folder: {redact(str(exc))}")

    if not output_dir.is_dir():
        return _OutputDirResult(False, output_dir, "ffmpeg_workdir_unwritable", "FFmpeg work path exists but is not a folder.")

    probe_path = output_dir / f".write_test_{uuid.uuid4().hex}.tmp"
    try:
        probe_path.write_bytes(b"ok")
        probe_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("FFmpeg work directory is not writable %s: %s", output_dir, redact(str(exc)))
        return _OutputDirResult(False, output_dir, "ffmpeg_workdir_unwritable", f"FFmpeg work folder is not writable: {redact(str(exc))}")
    return _OutputDirResult(True, output_dir)


def _safe_output_stem(stem: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    if not safe:
        safe = "clip"
    return safe[:90].rstrip(" .") or "clip"


def _concise_ffmpeg_message(category: str, stderr: str | None, limit: int = 420) -> str:
    friendly = {
        "ffmpeg_missing": "FFmpeg executable was not found.",
        "ffmpeg_output_error": "FFmpeg could not open the compressed output file.",
        "ffmpeg_output_missing_or_invalid": "FFmpeg output folder or filename was missing or invalid.",
        "ffmpeg_output_permission_error": "FFmpeg cannot write to the output folder.",
        "ffmpeg_input_missing": "Input clip file was missing.",
        "ffmpeg_input_permission_error": "FFmpeg cannot read the input clip.",
        "ffmpeg_invalid_input": "Input clip appears corrupted or unsupported.",
        "ffmpeg_workdir_unwritable": "FFmpeg work folder is not writable.",
        "ffmpeg_launch_error": "FFmpeg could not be started.",
    }
    base = friendly.get(category, "FFmpeg compression failed.")
    detail = _stderr_summary(stderr, limit=limit) if stderr else ""
    detail = " ".join(detail.split())
    if not detail:
        return base
    return f"{base} {detail[:limit]}".strip()


def _startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def _creationflags(priority: str) -> int:
    if os.name != "nt":
        return 0
    flags = CREATE_NO_WINDOW
    if priority == "idle":
        return flags | IDLE_PRIORITY_CLASS
    if priority == "low":
        return flags | BELOW_NORMAL_PRIORITY_CLASS
    return flags


def _stderr_summary(stderr: str | None, limit: int = 2000) -> str:
    if not stderr:
        return ""
    text = redact(stderr.strip())
    if len(text) <= limit:
        return text
    return text[-limit:]


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False
