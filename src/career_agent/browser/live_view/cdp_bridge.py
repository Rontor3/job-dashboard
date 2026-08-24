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


def forward_pointer(cdp, nx, ny, kind, width, height):
    x, y = norm_to_px(nx, ny, width, height)
    seq = {"click": ["mousePressed", "mouseReleased"],
           "down": ["mousePressed"], "up": ["mouseReleased"],
           "move": ["mouseMoved"]}.get(kind, ["mouseMoved"])
    for t in seq:
        cdp.send("Input.dispatchMouseEvent",
                 {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})


def stop_screencast(cdp):
    try:
        cdp.send("Page.stopScreencast")
    finally:
        cdp.detach()
