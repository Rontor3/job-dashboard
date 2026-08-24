"""Minimal aiohttp live-view server: token-gated page + WebSocket that streams
screencast frames and relays viewer pointer events into the page via CDP.
Binds to the given host (the tailnet iface), never 0.0.0.0 unless a public
tunnel was explicitly enabled by the caller."""
from __future__ import annotations

_PAGE = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>
<canvas id=c style='width:100vw'></canvas><script>
const ws=new WebSocket(location.href.replace('http','ws')+'/ws');
const c=document.getElementById('c'),x=c.getContext('2d'),img=new Image();
ws.onmessage=e=>{const m=JSON.parse(e.data);img.onload=()=>{c.width=m.w;c.height=m.h;
 x.drawImage(img,0,0);};img.src='data:image/jpeg;base64,'+m.f;};
function send(ev,k){const r=c.getBoundingClientRect();
 ws.send(JSON.stringify({x:(ev.clientX-r.left)/r.width,y:(ev.clientY-r.top)/r.height,kind:k}));}
c.addEventListener('touchend',e=>{const t=e.changedTouches[0];send(t,'click');e.preventDefault();});
c.addEventListener('click',e=>send(e,'click'));
</script>"""


class LiveViewServer:
    def __init__(self, page, token, host, port):
        self.page, self.token, self.host, self.port = page, token, host, port
        self._runner = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/s/{self.token.value}"

    async def start(self):
        from aiohttp import web
        from career_agent.browser.live_view.cdp_bridge import (
            start_screencast, forward_pointer, stop_screencast)
        from career_agent.integrations.live_view.token import check_and_consume
        import time

        vp = self.page.viewport_size or {"width": 900, "height": 1600}

        async def page_handler(request):
            if request.match_info["tok"] != self.token.value:
                return web.Response(status=404)
            return web.Response(text=_PAGE, content_type="text/html")

        async def ws_handler(request):
            if not check_and_consume(self.token, request.match_info["tok"], time.time()):
                return web.Response(status=403)
            ws = web.WebSocketResponse(); await ws.prepare(request)
            cdp = start_screencast(
                self.page, lambda data: ws.send_json({"f": data, "w": vp["width"], "h": vp["height"]}))
            try:
                async for msg in ws:
                    d = msg.json()
                    forward_pointer(cdp, d["x"], d["y"], d["kind"], vp["width"], vp["height"])
            finally:
                stop_screencast(cdp)
            return ws

        app = web.Application()
        app.add_routes([web.get("/s/{tok}", page_handler),
                        web.get("/s/{tok}/ws", ws_handler)])
        self._runner = web.AppRunner(app); await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
