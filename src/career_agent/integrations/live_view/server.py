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
import os
import secrets
import threading
import time

_DEBUG = bool(os.getenv("CAREER_AGENT_LIVEVIEW_DEBUG"))

_PAGE = """<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>
<style>body{margin:0;font-family:system-ui,sans-serif}
#bar{position:fixed;top:0;left:0;right:0;display:flex;align-items:center;gap:8px;
 padding:8px 10px;background:#0f172a;color:#fff;z-index:9}
#bar span{flex:1;font-size:13px;line-height:1.2}
#done{padding:11px 16px;font-size:15px;font-weight:700;background:#16a34a;color:#fff;
 border:0;border-radius:9px;white-space:nowrap}#done:disabled{background:#64748b}
#c{width:100vw;display:block;margin-top:52px}
#edit{position:fixed;bottom:0;left:0;right:0;display:flex;flex-wrap:wrap;gap:6px;padding:8px;
 background:#0f172a;z-index:9}
#t{flex:1 1 100%;font-size:16px;padding:9px;border-radius:8px;border:0;
 min-height:44px;max-height:38vh;resize:vertical;font-family:inherit;line-height:1.35}
#edit button{flex:1;font-size:14px;font-weight:700;border:0;border-radius:8px;padding:11px 8px;color:#fff}
#snd{background:#2563eb}#clr{background:#64748b}#ent{background:#334155}</style>
<div id=bar><span>Tap a field to focus it, type below, Send. Captcha? solve on screen, then Done.</span>
 <button id=done>&#10003; Done</button></div>
<canvas id=c></canvas>
<div id=edit><textarea id=t rows=2 placeholder='type a value (multi-line ok), then Send' autocapitalize=off autocomplete=off></textarea>
 <button id=snd>Send</button><button id=clr>Clear</button><button id=ent>&#9166;</button></div>
<script>
const ws=new WebSocket(location.href.replace('http','ws')+'/ws');
const c=document.getElementById('c'),x=c.getContext('2d'),img=new Image();
const tb=document.getElementById('t');
ws.onmessage=e=>{const m=JSON.parse(e.data);
 if(m.fv!==undefined){tb.value=m.fv;tb.focus();return;}   // tapped field's text -> edit box
 img.onload=()=>{c.width=img.naturalWidth||m.w;c.height=img.naturalHeight||m.h;
 x.drawImage(img,0,0);};img.src='data:image/jpeg;base64,'+m.f;};
function send(ev,k){const r=c.getBoundingClientRect();
 ws.send(JSON.stringify({x:(ev.clientX-r.left)/r.width,y:(ev.clientY-r.top)/r.height,kind:k}));}
// A short touch is a TAP (click); a drag is a SCROLL (wheel). This lets you
// reach fields lower on a long form.
let _sy=null,_moved=false;
c.addEventListener('touchstart',e=>{_sy=e.touches[0].clientY;_moved=false;},{passive:true});
c.addEventListener('touchmove',e=>{const y=e.touches[0].clientY,dy=_sy-y;
 if(Math.abs(dy)>3){_moved=true;ws.send(JSON.stringify({kind:'scroll',dy:dy*2.2}));_sy=y;}
 e.preventDefault();},{passive:false});
c.addEventListener('touchend',e=>{if(!_moved){const t=e.changedTouches[0];send(t,'click');}
 e.preventDefault();});
c.addEventListener('click',e=>send(e,'click'));   // desktop viewers
const d=document.getElementById('done');
d.addEventListener('click',()=>{ws.send(JSON.stringify({kind:'done'}));
 d.disabled=true;d.textContent='closing...';});
// Send REPLACES the focused field: clear it, then type the new value.
document.getElementById('snd').addEventListener('click',()=>{
 ws.send(JSON.stringify({kind:'clear'}));
 ws.send(JSON.stringify({kind:'text',text:tb.value}));tb.value='';});
document.getElementById('clr').addEventListener('click',()=>ws.send(JSON.stringify({kind:'clear'})));
document.getElementById('ent').addEventListener('click',()=>ws.send(JSON.stringify({kind:'key',key:'Enter'})));
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

    def push_field_value(self, val) -> None:
        # Main thread -> server loop: hand the phone the focused field's current
        # text so it loads into the edit box (read + iterate the draft).
        loop, q = self._loop, self._fv_q
        if loop is None or q is None:
            return
        def _put():
            if q.full():
                try: q.get_nowait()
                except asyncio.QueueEmpty: pass
            q.put_nowait(val)
        loop.call_soon_threadsafe(_put)

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
        self._fv_q = asyncio.Queue(maxsize=8)
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
        self._ws_clients = set()

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
            self._ws_clients.add(ws)
            sender = asyncio.create_task(self._pump_frames(ws, vp))
            fvsender = asyncio.create_task(self._pump_fieldvals(ws))
            try:
                async for msg in ws:
                    if msg.type == web.WSMsgType.TEXT:
                        d = msg.json()
                        k = d.get("kind")
                        if k == "done":
                            self.pointer_sink.put((0.0, 0.0, "__done__"))
                        elif k == "text":
                            self.pointer_sink.put((d.get("text", ""), None, "__text__"))
                        elif k == "key":
                            self.pointer_sink.put((d.get("key", ""), None, "__key__"))
                        elif k == "clear":
                            self.pointer_sink.put(("", None, "__clear__"))
                        elif k == "scroll":
                            self.pointer_sink.put((d.get("dy", 0), None, "__scroll__"))
                        else:
                            self.pointer_sink.put((d["x"], d["y"], d["kind"]))
                        if _DEBUG:
                            print(f"[lv] recv {d}", flush=True)
            except asyncio.CancelledError:
                pass
            finally:
                sender.cancel()
                fvsender.cancel()
                self._ws_clients.discard(ws)
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

    async def _pump_fieldvals(self, ws) -> None:
        try:
            while not ws.closed:
                val = await self._fv_q.get()
                await ws.send_json({"fv": val})       # focused field's text -> phone edit box
        except (asyncio.CancelledError, ConnectionResetError):
            pass

    async def _cleanup(self) -> None:
        # Close live sockets gracefully first so their handlers exit on their
        # own, rather than being force-cancelled mid-request (which threw
        # InvalidStateError from aiohttp's internals during shutdown).
        for ws in list(getattr(self, "_ws_clients", ())):
            try:
                await ws.close(code=1001)
            except Exception:
                pass
        if self._runner:
            await self._runner.cleanup()
