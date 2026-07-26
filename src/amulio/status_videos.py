from pathlib import Path

from fastapi.responses import FileResponse

ASSET_DIRECTORY = Path(__file__).with_name("assets")
STATUS_VIDEO_FILES = {
    "started": "download-started.mp4",
    "downloading": "downloading.mp4",
    "unavailable": "amule-unavailable.mp4",
}


def status_video(kind: str) -> FileResponse:
    filename = STATUS_VIDEO_FILES[kind]
    return FileResponse(
        ASSET_DIRECTORY / filename,
        media_type="video/mp4",
        filename=filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )
