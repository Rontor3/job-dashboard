"""Live-view server for remote solve.

Runs aiohttp in its OWN thread/loop, because the rest of the codebase drives
Playwright through its SYNC API on the main thread and the two event loops
cannot share a thread. The bridge is deliberately one-directional per hop:

- frames  (main thread -> server loop): the sync CDP screencast callback calls
  `push_frame`, which hands the frame to the server loop via
  `loop.call_soon_threadsafe`; a per-connection coroutine awaits it and does
  `await ws.send_json(...)`.
- pointers (server loop -> main thread): the WS handler drops each viewer tap
  onto a thread-safe queue; the MAIN thread drains it (see RemoteSolveSession)
  and applies it with sync Playwright. The server never touches Playwright.

Binds to the caller-supplied host (the tailnet interface), never 0.0.0.0.
"""
from __future__ import annotations

import asyncio
import secrets
import threading
import time

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
    def __init__(self, page, token, host, port, pointer_sink):
        # `pointer_sink` is a thread-safe queue.Queue drained by the main thread.
        self.page = page
        self.token = token
        self.host = host
        self.port = port
        self.pointer_sink = pointer_sink
        self._loop = None
        self._thread = None
        self._frame_q = None          # asyncio.Queue, created in the server loop
        self._runner = None
        self._ready = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/s/{self.token.value}"

    # --- lifecycle (called from the main thread) ---
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("live-view server failed to start within 10s")

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._cleanup(), loop)
            fut.result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    def push_frame(self, data) -> None:
        # Called from the MAIN (Playwright) thread by the screencast callback.
        loop, q = self._loop, self._frame_q
        if loop is None or q is None:
            return

        def _put():
            if q.full():                      # keep only the freshest frame
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(data)

        loop.call_soon_threadsafe(_put)

    # --- server-thread internals ---
    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._frame_q = asyncio.Queue(maxsize=2)
        try:
            self._loop.run_until_complete(self._start_site())
            self._ready.set()
            self._loop.run_forever()
        finally:
            # Drain pending tasks (ws handler, frame pump) before closing, so we
            # don't emit "Task destroyed / Event loop is closed" noise on stop.
            try:
                pending = list(asyncio.all_tasks(self._loop))
                for t in pending:
                    t.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True))
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            finally:
                self._loop.close()

    async def _start_site(self) -> None:
        from aiohttp import web
        vp = self.page.viewport_size or {"width": 900, "height": 1600}

        async def page_handler(request):
            if not secrets.compare_digest(request.match_info["tok"], self.token.value):
                return web.Response(status=404)
            return web.Response(text=_PAGE, content_type="text/html")

        async def ws_handler(request):
            from career_agent.integrations.live_view.token import is_valid
            # Non-consuming: allow the phone to RECONNECT within the TTL (a
            # reflexive back/reload must not lock the user out). Still gated by
            # match + expiry; the session revokes the token on close.
            if not is_valid(self.token, request.match_info["tok"], time.time()):
                return web.Response(status=403)
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            sender = asyncio.create_task(self._pump_frames(ws, vp))
            try:
                async for msg in ws:
                    if msg.type == web.WSMsgType.TEXT:
                        d = msg.json()
                        self.pointer_sink.put((d["x"], d["y"], d["kind"]))
            finally:
                sender.cancel()
            return ws

        app = web.Application()
        app.add_routes([web.get("/s/{tok}", page_handler),
                        web.get("/s/{tok}/ws", ws_handler)])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()

    async def _pump_frames(self, ws, vp) -> None:
        try:
            while not ws.closed:
                data = await self._frame_q.get()
                await ws.send_json({"f": data, "w": vp["width"], "h": vp["height"]})
        except (asyncio.CancelledError, ConnectionResetError):
            pass

    async def _cleanup(self) -> None:
        if self._runner:
            await self._runner.cleanup()
