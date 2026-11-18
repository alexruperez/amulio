import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def configuration_server(tmp_path: Path) -> Iterator[str]:
    """Run the real ASGI app so browser tests cover its JavaScript too."""
    port = _free_port()
    public_url = f"http://127.0.0.1:{port}"
    environment = os.environ | {
        "AMULIO_PUBLIC_URL": public_url,
        "AMULIO_INSTALL_TOKEN": "i" * 24,
        "AMULIO_TOKEN_SECRET": "s" * 32,
        "AMULIO_ADMIN_PASSWORD": "a" * 32,
        "AMULIO_ADMIN_BOOTSTRAP_TOKEN": "b" * 32,
        "AMULIO_TRUSTED_INGRESS_PROXY_SOURCES": "127.0.0.1/32",
        "AMULIO_ALLOWED_MEDIA_ROOTS": str(tmp_path),
        "AMULE_API_ADMIN_PASSWORD": "test-password",
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "amulio.app:app", "--port", str(port)],
        cwd=Path(__file__).parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    configuration_url = f"{public_url}/{'i' * 24}/configure"
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(configuration_url, timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("Timed out waiting for the configuration test server")
        yield configuration_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.mark.ui
def test_configuration_page_is_responsive_keyboard_accessible_and_creates_profiles(
    configuration_server: str, browser: Browser
):
    page: Page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(configuration_server)

    install_link = page.get_by_role("link", name="Open in Stremio app")
    assert (
        install_link.get_attribute("href")
        == configuration_server.replace("http://", "stremio://").removesuffix("/configure")
        + "/manifest.json"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    profile_summary = page.locator(".profile-settings summary")
    profile_summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".profile-settings")).to_have_attribute("open", "")
    page.keyboard.press("Tab")
    expect(page.locator("#admin-password")).to_be_focused()

    page.locator("#result-limit").fill("51")
    page.locator("#profile-submit").click()
    assert page.locator("#result-limit").evaluate("element => !element.checkValidity()")

    page.locator("#result-limit").fill("10")
    page.locator('input[name="show_stream_sources"]').uncheck()
    page.locator("#admin-password").fill("a" * 32)
    with page.expect_response(
        lambda response: (
            response.url.endswith("/admin/profiles") and response.request.method == "POST"
        )
    ) as profile_response:
        page.locator("#profile-submit").click()
    expect(page.locator("#profile-feedback")).to_contain_text("Profile manifest created")
    expect(page.locator("#manifest-url")).to_contain_text("/profile/")
    assert "/profile/" in (install_link.get_attribute("href") or "")
    assert profile_response.value.json()["preferences"]["show_stream_sources"] is False

    page.set_viewport_size({"width": 375, "height": 812})
    page.reload()
    page.locator(".profile-settings summary").click()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    first_label = page.locator(".profile-grid label").nth(0).bounding_box()
    second_label = page.locator(".profile-grid label").nth(1).bounding_box()
    assert first_label is not None and second_label is not None
    assert first_label["x"] == second_label["x"]


@pytest.mark.ui
def test_download_manager_mobile_states_are_localized_and_safe(
    configuration_server: str, browser: Browser
):
    page: Page = browser.new_page(viewport={"width": 375, "height": 812})
    queue = {"downloads": [], "shared": []}
    mutations: list[str] = []
    library_mutations: list[str] = []
    cancel_dialogs: list[str] = []
    delete_dialogs: list[str] = []

    def mock_downloads(route):
        if route.request.method == "GET":
            route.fulfill(status=200, json=queue)
            return
        mutations.append(route.request.method)
        route.fulfill(status=200, json={"results": []})

    def mock_library(route):
        library_mutations.append(route.request.method)
        route.fulfill(status=200, json={"results": []})

    def accept_library_delete(dialog):
        delete_dialogs.append(dialog.message)
        dialog.accept()

    def accept_download_cancel(dialog):
        cancel_dialogs.append(dialog.message)
        dialog.accept()

    page.route("**/admin/downloads", mock_downloads)
    page.route("**/admin/library", mock_library)

    page.set_extra_http_headers(
        {
            "X-Remote-User-ID": "owner",
            "X-Ingress-Path": "/api/hassio_ingress/test",
        }
    )
    ingress_url = configuration_server.rsplit("/", 2)[0] + "/configure?lang=es"
    page.goto(ingress_url)
    page.locator("#download-manager > summary").click()
    expect(page.locator("#manager-session")).to_be_visible()
    expect(page.locator("#manager-feedback")).to_have_attribute("aria-live", "polite")
    expect(page.locator(".manager-empty")).to_contain_text("No hay descargas activas")
    expect(page.locator("#manager-toolbar")).to_be_hidden()

    queue.update(
        {
            "downloads": [
                {
                    "hash": "a" * 32,
                    "name": "Una-descarga-muy-larga-para-comprobar-el-ajuste-en-movil.mkv",
                    "size": 2048,
                    "size_done": 1024,
                    "status": "downloading",
                }
            ],
            "shared": [{"hash": "b" * 32, "name": "Original.Release.Name.mkv", "size": 1024}],
        }
    )
    page.locator("#manager-refresh").click()
    expect(page.locator(".manager-download")).to_have_count(1)
    progress = page.locator(".manager-download-row progress")
    expect(progress).to_have_attribute("value", "1024")
    expect(progress).to_have_attribute("max", "2048")
    expect(progress).to_have_attribute("aria-label", "50% completado")
    expect(page.locator(".manager-progress")).to_contain_text("50% completado")
    expect(page.locator('[data-manager-action="pause"]')).to_be_disabled()
    expect(page.locator("#manager-cancel-open")).to_be_disabled()
    expect(page.locator(".manager-library-card")).to_contain_text("1 KiB")
    expect(page.locator(".manager-library-name")).to_have_text("Original Release Name")
    expect(page.locator(".manager-library-card details")).to_contain_text(
        "Original.Release.Name.mkv"
    )
    expect(page.locator(".manager-library")).to_have_count(1)
    expect(page.locator("#manager-library-delete")).to_be_disabled()

    page.locator(".manager-download").check()
    expect(page.locator('[data-manager-action="pause"]')).to_be_enabled()
    expect(page.locator("#manager-cancel-open")).to_be_enabled()
    expect(page.locator("#manager-selection-count")).to_contain_text("1 seleccionadas")
    assert mutations == []
    page.once("dialog", accept_download_cancel)
    with page.expect_request(
        lambda request: request.url.endswith("/admin/downloads") and request.method == "DELETE"
    ) as delete_request:
        page.locator("#manager-cancel-open").click()
    request = delete_request.value
    expect(page.locator("#manager-feedback")).to_contain_text("Cancelación completada")
    assert mutations == ["DELETE"]
    assert len(cancel_dialogs) == 1
    assert "Cancelar descargas seleccionadas" in cancel_dialogs[0]
    assert "1 seleccionadas" in cancel_dialogs[0]
    assert request.header_value("X-CSRF-Token")
    assert request.post_data_json == {"hashes": ["a" * 32]}

    page.locator(".manager-library").check()
    expect(page.locator("#manager-library-selection-count")).to_contain_text(
        "1 archivos seleccionados (1 KiB)"
    )
    page.on("dialog", accept_library_delete)
    with page.expect_request(
        lambda request: request.url.endswith("/admin/library") and request.method == "DELETE"
    ) as library_delete_request:
        page.locator("#manager-library-delete").click()
    library_request = library_delete_request.value
    expect(page.locator("#manager-feedback")).to_contain_text("Archivos completados eliminados")
    expect(page.locator(".manager-library")).to_have_count(0)
    expect(page.locator("#manager-library-toolbar")).to_be_hidden()
    assert library_mutations == ["DELETE"]
    assert len(delete_dialogs) == 1
    assert "1 archivos seleccionados (1 KiB)" in delete_dialogs[0]
    assert library_request.header_value("X-CSRF-Token")
    assert library_request.post_data_json == {"hashes": ["b" * 32]}
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.ui
def test_download_manager_polls_open_sessions_and_stops_when_closed(
    configuration_server: str, browser: Browser
):
    page: Page = browser.new_page(viewport={"width": 375, "height": 812})
    queue = {
        "downloads": [
            {
                "hash": "c" * 32,
                "name": "active.mkv",
                "size": 2048,
                "size_done": 512,
                "status": "downloading",
            }
        ],
        "shared": [],
    }
    download_requests = 0

    def mock_downloads(route):
        nonlocal download_requests
        download_requests += 1
        route.fulfill(status=200, json=queue)

    page.route("**/admin/downloads", mock_downloads)
    page.route(
        "**/configure/status",
        lambda route: route.fulfill(status=200, json={"ed2k": "connected", "kad": "connected"}),
    )
    page.set_extra_http_headers(
        {
            "X-Remote-User-ID": "owner",
            "X-Ingress-Path": "/api/hassio_ingress/test",
        }
    )
    page.goto(configuration_server.rsplit("/", 2)[0] + "/configure")
    page.locator("#download-manager > summary").click()
    expect(page.locator(".manager-progress")).to_contain_text("25% complete")
    queue["downloads"][0]["size_done"] = 4096

    expect(page.locator(".manager-progress")).to_contain_text("100% complete", timeout=6500)
    progress = page.locator(".manager-download-row progress")
    expect(progress).to_have_attribute("value", "2048")
    expect(progress).to_have_attribute("max", "2048")
    assert download_requests >= 2

    page.locator("#download-manager > summary").click()
    requests_when_closed = download_requests
    page.wait_for_timeout(5500)
    assert download_requests == requests_when_closed
