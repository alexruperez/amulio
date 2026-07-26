from pathlib import Path
from typing import Literal

from fastapi.responses import FileResponse

ASSET_DIRECTORY = Path(__file__).with_name("assets")
StatusVideoKind = Literal["started", "downloading", "unavailable"]

STATUS_VIDEO_FILES: dict[str, dict[StatusVideoKind, str]] = {
    "en": {
        "started": "download-started.mp4",
        "downloading": "downloading.mp4",
        "unavailable": "amule-unavailable.mp4",
    },
    "es": {
        "started": "download-started.es.mp4",
        "downloading": "downloading.es.mp4",
        "unavailable": "amule-unavailable.es.mp4",
    },
}


def status_video(kind: StatusVideoKind, *, locale: str = "en") -> FileResponse:
    filename = STATUS_VIDEO_FILES.get(locale, STATUS_VIDEO_FILES["en"])[kind]
    return FileResponse(
        ASSET_DIRECTORY / filename,
        media_type="video/mp4",
        filename=filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )
