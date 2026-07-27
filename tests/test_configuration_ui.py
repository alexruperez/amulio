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

    install_link = page.get_by_role("link", name="Install in Stremio")
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
