from pathlib import Path
from typing import Literal

from fastapi.responses import FileResponse

ASSET_DIRECTORY = Path(__file__).with_name("assets")
StatusVideoKind = Literal["started", "downloading", "unavailable", "no_results"]

STATUS_VIDEO_FILES: dict[str, dict[StatusVideoKind, str]] = {
    "en": {
        "started": "download-started.mp4",
        "downloading": "downloading.mp4",
        "unavailable": "amule-unavailable.mp4",
        "no_results": "no-results.mp4",
    },
    "es": {
        "started": "download-started.es.mp4",
        "downloading": "downloading.es.mp4",
        "unavailable": "amule-unavailable.es.mp4",
        "no_results": "no-results.es.mp4",
    },
}


def status_video_filename(kind: StatusVideoKind, *, locale: str = "en") -> str:
    return STATUS_VIDEO_FILES.get(locale, STATUS_VIDEO_FILES["en"])[kind]


def status_video(kind: StatusVideoKind, *, locale: str = "en") -> FileResponse:
    filename = status_video_filename(kind, locale=locale)
    return FileResponse(
        ASSET_DIRECTORY / filename,
        media_type="video/mp4",
        filename=filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )
