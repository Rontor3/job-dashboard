"""CDP screencast out / pointer in. Forwards only events handed to it — never
synthesizes input."""
from __future__ import annotations

from ...integrations.live_view.coords import norm_to_px


def start_screencast(page, on_frame):
    cdp = page.context.new_cdp_session(page)

    def _on(params):
        on_frame(params["data"])           # base64 jpeg
        cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    cdp.on("Page.screencastFrame", _on)
    cdp.send("Page.startScreencast",
             {"format": "jpeg", "quality": 60, "maxWidth": 900, "maxHeight": 1600})
    return cdp


def forward_pointer(page, nx, ny, kind, width, height):
    # Use Playwright's mouse API (move -> down -> up) rather than a raw CDP
    # press/release. The move establishes the pointer position and hit-test,
    # which is what routes the click into out-of-process iframes (reCAPTCHA /
    # hCaptcha live in cross-origin frames — a bare press/release never reached
    # them, so taps did nothing). Relays only the human's coordinates; no
    # synthetic movement or timing.
    x, y = norm_to_px(nx, ny, width, height)
    page.mouse.move(x, y)
    if kind in ("click", "down"):
        page.mouse.down()
    if kind in ("click", "up"):
        page.mouse.up()


def forward_keys(page, kind, value):
    """Relay the human's typed input into whatever field they focused (via a tap).
    Only forwards what it's handed — no synthetic input. kind is the queue
    sentinel: '__text__' types the value, '__key__' presses a named key
    (Backspace/Enter/Tab/…), '__clear__' selects-all and deletes the field."""
    kb = page.keyboard
    if kind == "__clear__":
        kb.press("Meta+A")           # server runs on macOS Chromium; select-all
        kb.press("Backspace")
    elif kind == "__key__":
        kb.press(value)
    else:                             # __text__
        kb.type(value)


def stop_screencast(cdp):
    try:
        cdp.send("Page.stopScreencast")
    finally:
        cdp.detach()
