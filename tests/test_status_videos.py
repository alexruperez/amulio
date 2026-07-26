from pathlib import Path

ASSET_DIRECTORY = Path(__file__).parents[1] / "src" / "amulio" / "assets"


def test_status_video_source_artwork_uses_english_as_the_default_language():
    assert "Download started in aMule" in (ASSET_DIRECTORY / "download-started.svg").read_text()
    assert "Downloading in aMule" in (ASSET_DIRECTORY / "downloading.svg").read_text()
    assert "aMule is unavailable" in (ASSET_DIRECTORY / "amule-unavailable.svg").read_text()
    assert "No matching files found" in (ASSET_DIRECTORY / "no-results.svg").read_text()
