from pathlib import Path

from amulio.status_videos import status_video

ASSET_DIRECTORY = Path(__file__).parents[1] / "src" / "amulio" / "assets"


def test_status_video_source_artwork_uses_english_as_the_default_language():
    assert "Download started in aMule" in (ASSET_DIRECTORY / "download-started.svg").read_text()
    assert "Downloading in aMule" in (ASSET_DIRECTORY / "downloading.svg").read_text()
    assert "aMule is unavailable" in (ASSET_DIRECTORY / "amule-unavailable.svg").read_text()
    assert "No matching files found" in (ASSET_DIRECTORY / "no-results.svg").read_text()


def test_status_videos_have_spanish_variants():
    assert "Descarga iniciada en aMule" in (ASSET_DIRECTORY / "download-started.es.svg").read_text()
    assert "Descargando en aMule" in (ASSET_DIRECTORY / "downloading.es.svg").read_text()
    assert "aMule no está disponible" in (ASSET_DIRECTORY / "amule-unavailable.es.svg").read_text()
    assert (
        "No se encontraron archivos coincidentes"
        in (ASSET_DIRECTORY / "no-results.es.svg").read_text()
    )
    assert status_video("started", locale="es").path.name == "download-started.es.mp4"
    assert status_video("no_results", locale="es").path.name == "no-results.es.mp4"
    assert status_video("started", locale="unsupported").path.name == "download-started.mp4"
