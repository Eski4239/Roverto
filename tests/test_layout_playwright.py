"""Phase 5b layout visual/structural checks (docs/03b §6 acceptance checks).

Requires requirements-dev.txt (playwright, pytest-playwright) -- never part of
ground_station/requirements.txt. Install once, then:

    pip install -r requirements-dev.txt
    playwright install chromium
    pytest -q tests/test_layout_playwright.py

Skipped automatically (collection-time, not at runtime) when playwright isn't
installed, so plain `pytest -q` from CLAUDE.md's Commands section is
unaffected either way.
"""
from __future__ import annotations

import asyncio
import socket
from typing import AsyncIterator

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
pytest_plugins = ("pytest_asyncio",)

import uvicorn  # noqa: E402

from ground_station.app.__main__ import parse_args as gs_parse_args  # noqa: E402
from ground_station.app.main import create_app  # noqa: E402
from simulator.fake_rover import parse_args as sim_parse_args, run_server  # noqa: E402

SCREENSHOT_DIR = "tests/screenshots"
VIEWPORT = {"width": 1366, "height": 768}
PRESETS = ("systems", "science", "drive")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_simulator(*, silent_after_s: float | None = None):
    argv = ["--encoders", "--ina219"]
    if silent_after_s is not None:
        argv += ["--rover-silent-after", str(silent_after_s), "--rover-silent-for", "30"]
    args = sim_parse_args(argv)
    args.host = "127.0.0.1"
    args.port = 0
    server = await run_server(args)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _start_backend(sim_port: int) -> uvicorn.Server:
    args = gs_parse_args(["--link", f"socket://127.0.0.1:{sim_port}"])
    app = create_app(args)
    gs_port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=gs_port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    server._gs_task = task  # keep a reference alive for the caller to cancel
    server._gs_port = gs_port
    return server


async def _stop(server: uvicorn.Server) -> None:
    server.should_exit = True
    await server._gs_task


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    async def _poll():
        while not predicate():
            await asyncio.sleep(0.05)

    await asyncio.wait_for(_poll(), timeout=timeout)


def _has_internal_scroll(page) -> list[str]:
    """Elements other than <html>/<body> whose content overflows their box --
    docs/03b §1 "no inner scrollbars at 1366x768+"."""
    return page.evaluate(
        """() => {
            const offenders = [];
            document.querySelectorAll('*').forEach(el => {
                if (el === document.documentElement || el === document.body) return;
                if (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1) {
                    const style = getComputedStyle(el);
                    if (style.overflow === 'hidden' || style.overflowY === 'hidden') return;
                    offenders.push(el.id || el.className || el.tagName);
                }
            });
            return offenders;
        }"""
    )


@pytest.fixture
async def running_backend() -> AsyncIterator[tuple[str, object]]:
    sim_server, sim_port = await _start_simulator()
    backend = await _start_backend(sim_port)
    base_url = f"http://127.0.0.1:{backend._gs_port}"
    try:
        yield base_url, backend
    finally:
        await _stop(backend)
        sim_server.close()
        await sim_server.wait_closed()


@pytest.fixture
async def silent_rover_backend() -> AsyncIterator[str]:
    """--rover-silent-after 2: LOST kicks in 2 s after the fixture starts."""
    sim_server, sim_port = await _start_simulator(silent_after_s=2.0)
    backend = await _start_backend(sim_port)
    base_url = f"http://127.0.0.1:{backend._gs_port}"
    try:
        yield base_url
    finally:
        await _stop(backend)
        sim_server.close()
        await sim_server.wait_closed()


def test_no_inner_scroll_and_no_console_errors_per_preset(running_backend, playwright):
    base_url, _ = running_backend
    console_errors: list[str] = []
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport=VIEWPORT)
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))
    page.goto(base_url)
    page.wait_for_timeout(500)  # let the first WS snapshot land

    for preset in PRESETS:
        page.click(f'[data-preset="{preset}"]')
        page.wait_for_timeout(200)
        offenders = _has_internal_scroll(page)
        page.screenshot(path=f"{SCREENSHOT_DIR}/{preset}.png")
        assert offenders == [], f"{preset}: unexpected inner scroll on {offenders}"

    browser.close()
    assert console_errors == [], f"console errors: {console_errors}"


def test_lost_state_no_inner_scroll_and_no_console_errors(silent_rover_backend, playwright):
    base_url = silent_rover_backend
    console_errors: list[str] = []
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport=VIEWPORT)
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))
    page.goto(base_url)
    page.wait_for_timeout(500)

    page.wait_for_selector("#lost-banner.visible", timeout=10_000)
    offenders = _has_internal_scroll(page)
    page.screenshot(path=f"{SCREENSHOT_DIR}/lost.png")
    browser.close()

    assert offenders == [], f"LOST state: unexpected inner scroll on {offenders}"
    assert console_errors == [], f"console errors: {console_errors}"
