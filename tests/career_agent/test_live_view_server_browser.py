import os
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def test_screencast_emits_frames_and_pointer_reaches_page():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.live_view.cdp_bridge import (
        start_screencast, forward_pointer, stop_screencast,
    )
    frames = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        page.set_content(
            "<button id='b' style='position:absolute;left:0;top:0;width:100vw;height:100vh'"
            " onclick=\"window.__hit=1\">tap</button>")
        cdp = start_screencast(page, lambda data: frames.append(data))
        page.wait_for_timeout(500)
        forward_pointer(page, 0.5, 0.5, "click",
                        page.viewport_size["width"], page.viewport_size["height"])
        page.wait_for_timeout(200)
        hit = page.evaluate("window.__hit")
        stop_screencast(cdp); b.close()
    assert frames, "expected at least one screencast frame"
    assert hit == 1, "forwarded pointer should have clicked the page button"


def _free_port():
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_remote_solve_session_streams_frame_and_applies_tap():
    """Full round-trip: the threaded live-view server streams a frame to a
    WebSocket client, and a tap sent by that client is applied to the real
    page by the main-thread pump (proving the sync/async bridge)."""
    import threading, asyncio, aiohttp
    from playwright.sync_api import sync_playwright
    from career_agent.integrations.live_view.session import RemoteSolveSession

    port = _free_port()
    frames = []

    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page()
        # Include an hcaptcha iframe so classify_gate sees a live gate -> the
        # session clears ONLY via is_cleared (the tap setting __hit), keeping
        # this a real test of the pointer path rather than the gone-debounce.
        page.set_content(
            "<iframe src='https://hcaptcha.com/1/api.js' style='display:none'></iframe>"
            "<button style='position:absolute;left:0;top:0;width:100vw;height:100vh'"
            " onclick='window.__hit=1'>tap</button>")
        sess = RemoteSolveSession(
            page, host="127.0.0.1", port=port, ttl_s=300, allow_public=False,
            is_cleared=lambda p: p.evaluate("window.__hit === 1") is True,
            poll_interval_s=0.2)
        url = sess.start()

        def client():
            async def run():
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(url.replace("http", "ws") + "/ws") as ws:
                        msg = await asyncio.wait_for(ws.receive(), timeout=8)
                        frames.append(msg)
                        await ws.send_json({"x": 0.5, "y": 0.5, "kind": "click"})
                        await asyncio.sleep(2)
            asyncio.run(run())

        t = threading.Thread(target=client); t.start()
        cleared = sess.wait_until_cleared(timeout_s=8)
        t.join(timeout=5)
        sess.close(); b.close()

    assert frames, "client never received a screencast frame"
    assert cleared is True, "the client's tap never reached the page"
