"""Typed application exceptions and API error response mapping.

Spec: references/02-architecture-and-data-contracts.md section 9; docs/FILE-MAP.md row 49.
"""

from __future__ import annotations


class AppError(Exception):
    """Base application exception with error code, human message, and optional hint."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.hint = hint


class InvalidUrl(AppError):
    def __init__(self, message: str = "Invalid YouTube URL", hint: str | None = "Paste a standard YouTube video link (e.g., https://www.youtube.com/watch?v=...)") -> None:
        super().__init__("INVALID_URL", message, hint)


class SourceBlocked(AppError):
    def __init__(self, channel: str, reason: str = "Channel blocked by source policy") -> None:
        super().__init__("SOURCE_BLOCKED", f"Channel '{channel}' is blocked: {reason}", "Check config/source_policy.yaml")


class SourceUnavailable(AppError):
    def __init__(self, message: str = "Video is private, deleted, or unavailable") -> None:
        super().__init__("SOURCE_UNAVAILABLE", message, "Ensure the video is publicly viewable without login")


class LiveNotFinished(AppError):
    def __init__(self, message: str = "Livestream is currently in progress") -> None:
        super().__init__("LIVE_NOT_FINISHED", message, "Wait for the livestream to conclude and process as a VOD")


class TooLong(AppError):
    def __init__(self, duration_s: float, max_hours: int) -> None:
        super().__init__(
            "TOO_LONG",
            f"Video duration ({duration_s / 3600:.1f}h) exceeds maximum allowed ({max_hours}h)",
            "Adjust MAX_SOURCE_HOURS in .env if needed",
        )


class DiskSpace(AppError):
    def __init__(self, needed_gb: float, have_gb: float) -> None:
        super().__init__(
            "DISK_SPACE",
            f"Not enough disk space: need about {needed_gb:.1f} GB free, have {have_gb:.1f} GB",
            "Delete old jobs from data/work or change DATA_DIR in .env",
        )


class DownloadFailed(AppError):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__("DOWNLOAD_FAILED", message, hint)


class TranscribeFailed(AppError):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__("TRANSCRIBE_FAILED", message, hint)


class GeminiUnavailable(AppError):
    def __init__(self, message: str = "Gemini API unavailable after max retries") -> None:
        super().__init__("GEMINI_UNAVAILABLE", message, "Check internet connectivity and Gemini status")


class GeminiQuotaExceeded(AppError):
    def __init__(self, message: str = "Gemini daily API quota reached") -> None:
        super().__init__("GEMINI_QUOTA_EXCEEDED", message, "Resume job tomorrow or switch API key")


class BadModelOutput(AppError):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__("BAD_MODEL_OUTPUT", message, hint)


class FfmpegFailed(AppError):
    def __init__(self, message: str, stderr_tail: str | None = None) -> None:
        hint = f"FFmpeg stderr tail:\n{stderr_tail}" if stderr_tail else None
        super().__init__("FFMPEG_FAILED", message, hint)


class NoCandidates(AppError):
    def __init__(self, message: str = "No viral candidate clips nominated from transcript") -> None:
        super().__init__("NO_CANDIDATES", message, "Try relaxing selection criteria or choosing a different video")


class Canceled(AppError):
    def __init__(self, message: str = "Job was canceled by user") -> None:
        super().__init__("CANCELED", message)


def to_api(err: AppError) -> dict[str, str]:
    """Format an AppError into standard API error dictionary:

    { "code": "...", "message": "...", "hint": "..." }
    """
    error_dict = {
        "code": err.code,
        "message": err.message,
    }
    if err.hint:
        error_dict["hint"] = err.hint
    return error_dict
