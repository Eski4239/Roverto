"""Phase 5b layout visual/structural checks (docs/03b §6 acceptance checks).

Requires requirements-dev.txt (playwright) -- never part of
ground_station/requirements.txt. Install once, then:

    pip install -r requirements-dev.txt
    playwright install chromium
    pytest -q -m layout

Skipped automatically (collection-time, not at runtime) when playwright isn't
installed, so plain `pytest -q` from CLAUDE.md's Commands section is
unaffected either way. The pytest-playwright plugin is disabled repo-wide
(see pytest.ini `-p no:playwright`) because its sync fixtures collide with
pytest-asyncio's `asyncio_mode = auto` used by every other test file; this
file drives Playwright's async API directly instead.
"""
from __future__ import annotations

import asyncio
import socket
from typing import AsyncIterator

import pytest

playwright_async = pytest.importorskip("playwright.async_api")

import uvicorn  # noqa: E402

from ground_station.app.__main__ import parse_args as gs_parse_args  # noqa: E402
from ground_station.app.main import create_app  # noqa: E402
from simulator.fake_rover import parse_args as sim_parse_args, run_server  # noqa: E402

pytestmark = pytest.mark.layout

SCREENSHOT_DIR = "tests/screenshots"
VIEWPORT = {"width": 1366, "height": 768}
PRESETS = ("systems", "science", "drive")
TEARDOWN_TIMEOUT_S = 5.0


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
    try:
        await asyncio.wait_for(server._gs_task, timeout=TEARDOWN_TIMEOUT_S)
    except asyncio.TimeoutError:
        server._gs_task.cancel()


async def _overflow_report(page) -> dict:
    """docs/03b §1 "no inner scrollbars at 1366x768+", split per F14:
    - scroll: overflow auto/scroll with content bigger than the box (a real
      inner scrollbar the user could see/use).
    - clipped: overflow hidden/clip with content bigger than the box (text
      cut off, no scrollbar -- docs/03b's "clip by design" is only OK where
      intentional, so still worth surfacing, just separately from `scroll`).
    Elements that are hidden (display:none), have zero rendered size, or
    have no offsetParent (e.g. an inactive <section hidden> preset panel)
    are skipped entirely -- they are not visible overflow bugs."""
    return await page.evaluate(
        """() => {
            const scroll = [];
            const clipped = [];
            document.querySelectorAll('*').forEach(el => {
                if (el === document.documentElement || el === document.body) return;
                if (el.offsetParent === null && el !== document.body) return;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                const style = getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return;
                const overflows = el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1;
                if (!overflows) return;
                const id = el.id || el.className || el.tagName;
                const ov = style.overflow;
                const ovY = style.overflowY;
                const ovX = style.overflowX;
                const isHidden = [ov, ovY, ovX].some(v => v === 'hidden' || v === 'clip');
                const isScrollable = [ov, ovY, ovX].some(v => v === 'auto' || v === 'scroll');
                if (isScrollable) scroll.push(id);
                else if (isHidden) clipped.push(id);
                else scroll.push(id); // default (visible) overflow still shows a scrollbar in practice
            });
            return { scroll, clipped };
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
        try:
            await asyncio.wait_for(sim_server.wait_closed(), timeout=TEARDOWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            pass


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
        try:
            await asyncio.wait_for(sim_server.wait_closed(), timeout=TEARDOWN_TIMEOUT_S)
        except asyncio.TimeoutError:
            pass


async def _run_no_scroll_per_preset(base_url: str) -> None:
    console_errors: list[str] = []
    async with playwright_async.async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(viewport=VIEWPORT)
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))
            await page.goto(base_url)
            await page.wait_for_timeout(500)  # let the first WS snapshot land

            for preset in PRESETS:
                await page.click(f'[data-preset="{preset}"]')
                await page.wait_for_timeout(200)
                report = await _overflow_report(page)
                await page.screenshot(path=f"{SCREENSHOT_DIR}/{preset}.png")
                assert report["scroll"] == [], f"{preset}: inner scroll on {report['scroll']}"
                assert report["clipped"] == [], f"{preset}: clipped content on {report['clipped']}"
        finally:
            await browser.close()
    assert console_errors == [], f"console errors: {console_errors}"


async def test_no_inner_scroll_and_no_console_errors_per_preset(running_backend):
    base_url, _ = running_backend
    await asyncio.wait_for(_run_no_scroll_per_preset(base_url), timeout=60.0)


async def _run_only_selected_preset_visible(base_url: str) -> None:
    """F18: .preset-panel had no [hidden] CSS rule, so its `display: flex`
    beat the UA default and all three presets rendered stacked at once."""
    async with playwright_async.async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(viewport=VIEWPORT)
            await page.goto(base_url)
            await page.wait_for_timeout(500)

            for preset in PRESETS:
                await page.click(f'[data-preset="{preset}"]')
                await page.wait_for_timeout(200)
                visible = await page.evaluate(
                    """() => Array.from(document.querySelectorAll('.preset-panel'))
                        .filter(el => el.offsetParent !== null || el === document.body)
                        .map(el => el.dataset.preset)"""
                )
                assert visible == [preset], f"after selecting {preset}, visible panels were {visible}"
        finally:
            await browser.close()


async def test_only_selected_preset_is_visible(running_backend):
    base_url, _ = running_backend
    await asyncio.wait_for(_run_only_selected_preset_visible(base_url), timeout=60.0)


async def _run_lost_state_no_scroll(base_url: str) -> None:
    console_errors: list[str] = []
    async with playwright_async.async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(viewport=VIEWPORT)
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))
            await page.goto(base_url)
            await page.wait_for_timeout(500)

            await page.wait_for_selector("#lost-banner.visible", timeout=10_000)
            report = await _overflow_report(page)
            await page.screenshot(path=f"{SCREENSHOT_DIR}/lost.png")
            assert report["scroll"] == [], f"LOST state: inner scroll on {report['scroll']}"
            assert report["clipped"] == [], f"LOST state: clipped content on {report['clipped']}"
        finally:
            await browser.close()
    assert console_errors == [], f"console errors: {console_errors}"


async def test_lost_state_no_inner_scroll_and_no_console_errors(silent_rover_backend):
    base_url = silent_rover_backend
    await asyncio.wait_for(_run_lost_state_no_scroll(base_url), timeout=60.0)
