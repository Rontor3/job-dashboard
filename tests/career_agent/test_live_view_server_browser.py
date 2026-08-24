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
        forward_pointer(cdp, 0.5, 0.5, "click",
                        page.viewport_size["width"], page.viewport_size["height"])
        page.wait_for_timeout(200)
        hit = page.evaluate("window.__hit")
        stop_screencast(cdp); b.close()
    assert frames, "expected at least one screencast frame"
    assert hit == 1, "forwarded pointer should have clicked the page button"
