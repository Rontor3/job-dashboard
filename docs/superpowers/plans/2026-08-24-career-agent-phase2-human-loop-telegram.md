# Career Agent — Phase 2: Human-Loop over Telegram (Approver + Remote Solve) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the human loop to Telegram so the user acts from their phone: a `TelegramApprover` that replaces `CliApprover` behind the same `Approver` contract, and **Remote Solve** — a live-view of the agent's browser sent as a single-use Tailscale link so the user can solve an escalated captcha by thumb, after which the agent resumes.

**Architecture:** Extends Phase 1 without changing its pure core. Telegram is a thin HTTP client (injected transport, like `resume_llm`'s `PostFn`). Remote Solve is a CDP screencast + a tiny aiohttp live-view server behind a single-use token, exposed on the tailnet only. The run loop gains one branch: an interactive `escalate` gate triggers remote solve, and the submit approval goes through Telegram. Every pointer event originates from the user's device — the agent solves nothing.

**Tech Stack:** Python 3.11 · `httpx` (already a dep) for the Telegram Bot API · `aiohttp` for the live-view server · Playwright CDP (`new_cdp_session`) · pytest · stdlib `secrets`/`time`.

## Global Constraints

Copied from the parent design (spec §7, §16) and the remote-solve spec (§4, §7). Every task's requirements include these:

- **Human-in-the-loop only.** Remote Solve forwards pointer events that arrive from the viewer; the agent generates **no** synthetic input, solves no challenge, relays no token to any third party.
- **No evasion.** No mouse-dynamics modeling, no detection-score manipulation. `gate_probe` stays detection-only; `HANDLERS` still ship `escalate` for genuine challenges.
- **Private by default.** The live-view server binds to the Tailscale interface, never `0.0.0.0`. Public tunnels require an explicit `REMOTE_SOLVE_ALLOW_PUBLIC=1`.
- **Single-use, expiring links.** ≥256-bit token, consumed on first connect, TTL default 300s, one active session at a time. Never persist frames.
- **Safe degradation.** If Remote Solve cannot start (no Tailscale, CDP error), fall back to Phase-1 escalate (stop + report) — never auto-proceed past a gate.
- **No secrets in git.** `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` come from env/`.env` only.
- **File hygiene** < 500 lines; tests under `tests/career_agent/`, **no `__init__.py`** in the test dir (repo uses flat, package-less tests — a `career_agent` test package shadows the real one).

## Interfaces carried from Phase 1

- `Approver` protocol: `request(card: str) -> bool` (`integrations/approver.py`).
- `run_once(page, profile, resume_path, meta, approver, do_submit) -> dict` (`run.py`).
- `gate_probe.classify_gate(page) -> str`, `HANDLERS: dict[str,str]`, `GATES`.
- `render_card(...) -> str` (`integrations/review_card.py`).

---

### Task 1: Extend settings for Telegram + Remote Solve

**Files:**
- Modify: `src/career_agent/config/settings.py`
- Test: `tests/career_agent/test_settings_phase2.py`

**Interfaces:**
- Produces: `Settings` gains `telegram_bot_token: str|None`, `telegram_chat_id: str|None`, `remote_solve_port: int`, `remote_solve_ttl: int`, `remote_solve_allow_public: bool`, `tailscale_host: str|None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_settings_phase2.py
from career_agent.config.settings import load_settings


def test_phase2_defaults(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "REMOTE_SOLVE_PORT",
              "REMOTE_SOLVE_TTL", "REMOTE_SOLVE_ALLOW_PUBLIC", "TAILSCALE_HOST"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.telegram_bot_token is None
    assert s.remote_solve_port == 8765
    assert s.remote_solve_ttl == 300
    assert s.remote_solve_allow_public is False


def test_phase2_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("REMOTE_SOLVE_TTL", "120")
    monkeypatch.setenv("REMOTE_SOLVE_ALLOW_PUBLIC", "1")
    s = load_settings()
    assert s.telegram_bot_token == "123:abc"
    assert s.remote_solve_ttl == 120
    assert s.remote_solve_allow_public is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_settings_phase2.py -v`
Expected: FAIL — `Settings` has no `telegram_bot_token`.

- [ ] **Step 3: Extend `Settings` and `load_settings`**

Add the fields to the frozen `Settings` dataclass, and in `load_settings()`:

```python
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        remote_solve_port=int(os.getenv("REMOTE_SOLVE_PORT", "8765")),
        remote_solve_ttl=int(os.getenv("REMOTE_SOLVE_TTL", "300")),
        remote_solve_allow_public=_as_bool(os.getenv("REMOTE_SOLVE_ALLOW_PUBLIC"), False),
        tailscale_host=os.getenv("TAILSCALE_HOST") or None,
```

Keep the existing fields; add the new ones after them (update the dataclass definition to match).

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_settings_phase2.py tests/career_agent/test_settings.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/config/settings.py tests/career_agent/test_settings_phase2.py
git commit -m "feat(career-agent): settings for telegram + remote solve"
```

---

### Task 2: Telegram client (thin, injected transport)

**Files:**
- Create: `src/career_agent/integrations/telegram/__init__.py`
- Create: `src/career_agent/integrations/telegram/client.py`
- Test: `tests/career_agent/test_telegram_client.py`

**Interfaces:**
- Produces: `TelegramClient(token, chat_id, transport=None)` where `transport(method: str, payload: dict) -> dict` defaults to a real `httpx` call to `https://api.telegram.org/bot<token>/<method>`; tests inject a fake.
  - `send_message(text, buttons: list[list[tuple[str,str]]] | None) -> int` (returns message_id); `buttons` is rows of `(label, callback_data)`.
  - `poll_callback(timeout_s, valid: set[str]) -> str | None` — long-polls `getUpdates`, returns the first `callback_data` in `valid`, or None on timeout.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_telegram_client.py
from career_agent.integrations.telegram.client import TelegramClient


class FakeTransport:
    def __init__(self, responses): self.responses = responses; self.calls = []
    def __call__(self, method, payload):
        self.calls.append((method, payload))
        return self.responses.pop(0)


def test_send_message_builds_inline_keyboard():
    t = FakeTransport([{"ok": True, "result": {"message_id": 7}}])
    c = TelegramClient("tok", "42", transport=t)
    mid = c.send_message("hi", buttons=[[("Submit", "submit")], [("Skip", "skip")]])
    assert mid == 7
    method, payload = t.calls[0]
    assert method == "sendMessage"
    assert payload["chat_id"] == "42"
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "submit"


def test_poll_callback_returns_matching_data():
    upd = {"ok": True, "result": [
        {"update_id": 1, "callback_query": {"id": "x", "data": "submit"}}]}
    t = FakeTransport([upd, {"ok": True, "result": []}])
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_callback(timeout_s=0, valid={"submit", "skip"}) == "submit"


def test_poll_callback_ignores_unknown_and_times_out():
    upd = {"ok": True, "result": [
        {"update_id": 1, "callback_query": {"id": "x", "data": "other"}}]}
    t = FakeTransport([upd])
    c = TelegramClient("tok", "42", transport=t)
    assert c.poll_callback(timeout_s=0, valid={"submit"}) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_telegram_client.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create the package init + client**

`src/career_agent/integrations/telegram/__init__.py`: `"""Telegram human-loop channel."""`

```python
# src/career_agent/integrations/telegram/client.py
"""Thin Telegram Bot API client. Transport is injected (tests fake it);
the default hits api.telegram.org via httpx."""
from __future__ import annotations

from typing import Callable

Transport = Callable[[str, dict], dict]


def _default_transport(token: str) -> Transport:
    def _t(method: str, payload: dict) -> dict:
        import httpx
        url = f"https://api.telegram.org/bot{token}/{method}"
        return httpx.post(url, json=payload, timeout=65).json()
    return _t


class TelegramClient:
    def __init__(self, token: str, chat_id: str, transport: Transport | None = None):
        self.chat_id = chat_id
        self._t = transport or _default_transport(token)
        self._offset = 0

    def send_message(self, text: str, buttons=None) -> int:
        payload = {"chat_id": self.chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [
                [{"text": label, "callback_data": data} for (label, data) in row]
                for row in buttons]}
        resp = self._t("sendMessage", payload)
        return resp.get("result", {}).get("message_id", 0)

    def poll_callback(self, timeout_s: int, valid: set[str]) -> str | None:
        payload = {"timeout": timeout_s, "offset": self._offset,
                   "allowed_updates": ["callback_query"]}
        resp = self._t("getUpdates", payload)
        for upd in resp.get("result", []):
            self._offset = max(self._offset, upd["update_id"] + 1)
            data = upd.get("callback_query", {}).get("data")
            if data in valid:
                return data
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_telegram_client.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/integrations/telegram tests/career_agent/test_telegram_client.py
git commit -m "feat(career-agent): thin telegram bot-api client"
```

---

### Task 3: TelegramApprover (implements the Approver contract)

**Files:**
- Create: `src/career_agent/integrations/telegram/approver.py`
- Test: `tests/career_agent/test_telegram_approver.py`

**Interfaces:**
- Consumes: `TelegramClient` (Task 2).
- Produces: `TelegramApprover(client, poll_interval_s=2, deadline_s=1800)` with `request(card: str) -> bool` — sends the card with `[[Submit][Skip]]` buttons, polls until a callback, returns True only for `"submit"`. `"skip"` or deadline → False. (Edit/free-text parsing is deferred to Phase 3.)

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_telegram_approver.py
from career_agent.integrations.telegram.approver import TelegramApprover


class FakeClient:
    def __init__(self, answers): self.answers = answers; self.sent = []
    def send_message(self, text, buttons=None): self.sent.append((text, buttons)); return 1
    def poll_callback(self, timeout_s, valid): return self.answers.pop(0)


def test_submit_returns_true():
    c = FakeClient(["submit"])
    ok = TelegramApprover(c, poll_interval_s=0, deadline_s=10).request("CARD")
    assert ok is True
    assert "CARD" in c.sent[0][0]


def test_skip_returns_false():
    c = FakeClient(["skip"])
    assert TelegramApprover(c, poll_interval_s=0, deadline_s=10).request("CARD") is False


def test_no_answer_before_deadline_returns_false():
    c = FakeClient([None, None, None])  # never answers
    # deadline_s=0 -> the loop makes at most one poll then gives up
    assert TelegramApprover(c, poll_interval_s=0, deadline_s=0).request("CARD") is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_telegram_approver.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `approver.py`**

```python
# src/career_agent/integrations/telegram/approver.py
"""Telegram-backed Approver: sends the review card with Submit/Skip buttons
and blocks until the user taps one (or the deadline passes)."""
from __future__ import annotations

import time

_BUTTONS = [[("✅ Submit", "submit"), ("🚫 Skip", "skip")]]
_VALID = {"submit", "skip"}


class TelegramApprover:
    def __init__(self, client, poll_interval_s: int = 2, deadline_s: int = 1800,
                 sleep=time.sleep, clock=time.monotonic):
        self.client = client
        self.poll_interval_s = poll_interval_s
        self.deadline_s = deadline_s
        self._sleep = sleep
        self._clock = clock

    def request(self, card: str) -> bool:
        self.client.send_message(card, buttons=_BUTTONS)
        start = self._clock()
        while True:
            choice = self.client.poll_callback(timeout_s=self.poll_interval_s, valid=_VALID)
            if choice == "submit":
                return True
            if choice == "skip":
                return False
            if self._clock() - start >= self.deadline_s:
                return False
            self._sleep(self.poll_interval_s)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_telegram_approver.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/integrations/telegram/approver.py tests/career_agent/test_telegram_approver.py
git commit -m "feat(career-agent): telegram approver (submit/skip, deadline)"
```

---

### Task 4: Remote-solve token & session bookkeeping (pure)

**Files:**
- Create: `src/career_agent/integrations/live_view/__init__.py`
- Create: `src/career_agent/integrations/live_view/token.py`
- Test: `tests/career_agent/test_live_view_token.py`

**Interfaces:**
- Produces: `SolveToken(value: str, expires_at: float, used: bool)`; `mint_token(ttl_s: int, now: float) -> SolveToken` (value ≥ 43 urlsafe chars = 256 bits); `check_and_consume(tok: SolveToken, presented: str, now: float) -> bool` — True only if `presented == value`, not expired, not already used; flips `used=True` on success; `build_url(host: str, port: int, token: str, allow_public: bool) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_live_view_token.py
import pytest
from career_agent.integrations.live_view.token import (
    mint_token, check_and_consume, build_url,
)


def test_token_is_high_entropy_and_unique():
    a = mint_token(300, now=1000.0)
    b = mint_token(300, now=1000.0)
    assert len(a.value) >= 43 and a.value != b.value


def test_single_use():
    t = mint_token(300, now=1000.0)
    assert check_and_consume(t, t.value, now=1001.0) is True
    assert check_and_consume(t, t.value, now=1002.0) is False  # already used


def test_expiry():
    t = mint_token(300, now=1000.0)
    assert check_and_consume(t, t.value, now=1400.0) is False  # > ttl


def test_wrong_token_rejected():
    t = mint_token(300, now=1000.0)
    assert check_and_consume(t, "nope", now=1001.0) is False
    assert t.used is False


def test_build_url_tailnet_default():
    url = build_url("mac.tailnet.ts.net", 8765, "abc", allow_public=False)
    assert url == "http://mac.tailnet.ts.net:8765/s/abc"


def test_build_url_requires_host_when_not_public():
    with pytest.raises(ValueError):
        build_url(None, 8765, "abc", allow_public=False)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_live_view_token.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the init + `token.py`**

`src/career_agent/integrations/live_view/__init__.py`: `"""Remote-solve live view."""`

```python
# src/career_agent/integrations/live_view/token.py
"""Single-use, expiring token for a remote-solve session, plus URL building.
Pure: the clock is passed in so tests are deterministic."""
from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass
class SolveToken:
    value: str
    expires_at: float
    used: bool = False


def mint_token(ttl_s: int, now: float) -> SolveToken:
    return SolveToken(value=secrets.token_urlsafe(32), expires_at=now + ttl_s)


def check_and_consume(tok: SolveToken, presented: str, now: float) -> bool:
    if tok.used or now >= tok.expires_at:
        return False
    if not secrets.compare_digest(presented, tok.value):
        return False
    tok.used = True
    return True


_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # module top, with `import ipaddress`


def _is_private_host(host: str) -> bool:
    h = host.strip().lower()
    if h == "localhost":
        return True
    if h.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip in _TAILSCALE_CGNAT or ip.is_private or ip.is_loopback


def build_url(host: str | None, port: int, token: str, allow_public: bool) -> str:
    if not host:
        raise ValueError(
            "no host for the live-view link (set TAILSCALE_HOST or enable a public tunnel)")
    if not allow_public and not _is_private_host(host):
        raise ValueError(
            f"refusing to build a public live-view link to {host!r} (not on the tailnet); "
            "set REMOTE_SOLVE_ALLOW_PUBLIC=1 to opt in")
    return f"http://{host}:{port}/s/{token}"
```

Tests must also cover: tailnet IP (100.x) accepted, a public host rejected without opt-in, the same public host accepted with `allow_public=True`, and a missing host raising even when public.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_live_view_token.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/integrations/live_view tests/career_agent/test_live_view_token.py
git commit -m "feat(career-agent): remote-solve single-use token + url builder"
```

---

### Task 5: Coordinate mapping + `is_cleared` (pure)

**Files:**
- Create: `src/career_agent/integrations/live_view/coords.py`
- Modify: `src/career_agent/browser/gate_probe.py` (add `is_cleared_from_signals`)
- Test: `tests/career_agent/test_live_view_coords.py`, `tests/career_agent/test_gate_cleared.py`

**Interfaces:**
- Produces: `norm_to_px(nx: float, ny: float, width: int, height: int) -> tuple[int,int]` (clamps to `[0,1]`, rounds).
- Produces: `gate_probe.is_cleared_from_signals(sig: dict) -> bool` — True when a challenge response token is present (reuses the `grecaptcha_response_present` signal and a new `hcaptcha_response_present`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/career_agent/test_live_view_coords.py
from career_agent.integrations.live_view.coords import norm_to_px


def test_center_and_corners():
    assert norm_to_px(0.5, 0.5, 400, 800) == (200, 400)
    assert norm_to_px(0.0, 0.0, 400, 800) == (0, 0)
    assert norm_to_px(1.0, 1.0, 400, 800) == (400, 800)


def test_clamps_out_of_range():
    assert norm_to_px(-1, 2, 400, 800) == (0, 800)
```

```python
# tests/career_agent/test_gate_cleared.py
from career_agent.browser.gate_probe import is_cleared_from_signals


def test_cleared_when_recaptcha_token_present():
    assert is_cleared_from_signals({"grecaptcha_response_present": True}) is True


def test_cleared_when_hcaptcha_token_present():
    assert is_cleared_from_signals({"hcaptcha_response_present": True}) is True


def test_not_cleared_when_absent():
    assert is_cleared_from_signals({}) is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_live_view_coords.py tests/career_agent/test_gate_cleared.py -v`
Expected: FAIL — symbols missing.

- [ ] **Step 3: Write `coords.py`**

```python
# src/career_agent/integrations/live_view/coords.py
"""Map a normalized viewer pointer (0..1) to page pixels. Pure."""
from __future__ import annotations


def norm_to_px(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    nx = min(1.0, max(0.0, nx))
    ny = min(1.0, max(0.0, ny))
    return (round(nx * width), round(ny * height))
```

- [ ] **Step 4: Add `is_cleared_from_signals` to `gate_probe.py`**

Append:

```python
def is_cleared_from_signals(sig: dict) -> bool:
    return bool(sig.get("grecaptcha_response_present")
                or sig.get("hcaptcha_response_present"))
```

Also add `hcaptcha_response_present` to the `_gather_signals` JS (alongside the reCAPTCHA token check):

```javascript
        hcaptcha_response_present: (() => { const t = q('textarea[name="h-captcha-response"]');
          return !!(t && t.value && t.value.length > 0); })(),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_live_view_coords.py tests/career_agent/test_gate_cleared.py tests/career_agent/test_gate_probe.py -v`
Expected: PASS (all — existing gate_probe tests still green).

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/integrations/live_view/coords.py src/career_agent/browser/gate_probe.py tests/career_agent/test_live_view_coords.py tests/career_agent/test_gate_cleared.py
git commit -m "feat(career-agent): pointer coord mapping + is_cleared token detection"
```

---

### Task 6: CDP bridge + live-view server (browser/network, skip-marked)

> **REVISED after review (commit supersedes the naive template below).** The
> original `server.py` template wired frames as `on_frame=lambda: ws.send_json(...)`,
> but `send_json` is async and the CDP callback is sync → the coroutine was never
> awaited and no frame reached the client. Corrected architecture, now
> round-trip-verified live:
> - **`server.py`** runs aiohttp in its **own thread/loop** (sync Playwright and
>   asyncio can't share a thread). Frames: the sync screencast callback calls
>   `push_frame` → `loop.call_soon_threadsafe` → an `asyncio.Queue` → a per-connection
>   coroutine `await ws.send_json(...)`. Pointers: the WS handler drops each tap onto a
>   thread-safe `queue.Queue`; the server never touches Playwright.
> - **`integrations/live_view/session.py` — `RemoteSolveSession`** (the piece the
>   original plan referenced but never defined): `start()` mints the token, starts the
>   screencast + threaded server, returns the single-use URL; `wait_until_cleared()`
>   runs the **main-thread pump** that drains the pointer queue → `forward_pointer`
>   (sync Playwright, on the owning thread) and polls `is_cleared(page)`; `close()`
>   tears it down. This one loop both applies taps and detects the solve.
> - **`gate_probe`** gains `is_cleared(page)` and now treats an hCaptcha response
>   token as `cleared` (so a solved hCaptcha lets the run proceed).
> - Verified by `tests/career_agent/test_live_view_server_browser.py::test_remote_solve_session_streams_frame_and_applies_tap` (skip-marked; run with `RUN_BROWSER_TESTS=1` in a venv with playwright+aiohttp+pytest — passes: frame streamed to a WS client AND the client's tap clicked the real page).
> The signatures below still hold; the frame-delivery internals are as described here.

**Files:**
- Create: `src/career_agent/browser/live_view/__init__.py`, `src/career_agent/browser/live_view/cdp_bridge.py`
- Create: `src/career_agent/integrations/live_view/server.py`
- Test: `tests/career_agent/test_live_view_server_browser.py` (skip-marked)

**Interfaces:**
- `cdp_bridge.start_screencast(page, on_frame) -> cdp`; `cdp_bridge.forward_pointer(cdp, nx, ny, kind, width, height)`; `cdp_bridge.stop_screencast(cdp)`.
- `server.LiveViewServer(page, token, host, port)` with `url -> str`, `start()`, `stop()`; binds to `host`, serves `/s/<token>` (single-use) + a WebSocket that streams frames and accepts pointer events.

- [ ] **Step 1: Write the skip-marked integration test**

```python
# tests/career_agent/test_live_view_server_browser.py
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
```

- [ ] **Step 2: Run it (skips without the env var)**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_live_view_server_browser.py -v`
Expected: SKIP.

- [ ] **Step 3: Write `cdp_bridge.py`**

```python
# src/career_agent/browser/live_view/cdp_bridge.py
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
```

- [ ] **Step 4: Write `server.py`**

```python
# src/career_agent/integrations/live_view/server.py
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
```

Add `aiohttp>=3.9` to `requirements.txt`.

- [ ] **Step 5: Run the browser test (opt-in) + full suite**

Run: `PYTHONPATH=src RUN_BROWSER_TESTS=1 python3 -m pytest tests/career_agent/test_live_view_server_browser.py -v` (needs `.jd_env` with playwright + `pip install aiohttp`).
Expected: PASS. Then `PYTHONPATH=src python3 -m pytest tests/career_agent -q` — server test SKIPS, rest green.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/live_view src/career_agent/integrations/live_view/server.py requirements.txt tests/career_agent/test_live_view_server_browser.py
git commit -m "feat(career-agent): CDP live-view bridge + token-gated server"
```

---

### Task 7: HumanLoop facade + Tailscale host detection

**Files:**
- Create: `src/career_agent/integrations/human_loop.py`
- Create: `src/career_agent/integrations/live_view/tailscale.py`
- Test: `tests/career_agent/test_human_loop.py`, `tests/career_agent/test_tailscale.py`

**Interfaces:**
- `tailscale.detect_host(settings, runner=subprocess.run) -> str|None` — returns `settings.tailscale_host` if set, else parses `tailscale ip -4`; None if unavailable.
- `HumanLoop(approver, remote_solve_factory=None)`:
  - `approve(card) -> bool` — delegates to the approver.
  - `remote_solve(page, gate, on_link) -> bool` — if a factory is configured, start a solve session, call `on_link(url)` (to Telegram), wait until cleared (or deadline), return outcome; if not configured (no Tailscale / no factory), return **False** (caller degrades to Phase-1 stop-and-report).

- [ ] **Step 1: Write the failing tests**

```python
# tests/career_agent/test_tailscale.py
from career_agent.integrations.live_view.tailscale import detect_host
from career_agent.config.settings import load_settings


def test_prefers_explicit_setting(monkeypatch):
    monkeypatch.setenv("TAILSCALE_HOST", "mac.ts.net")
    assert detect_host(load_settings()) == "mac.ts.net"


def test_parses_cli_when_unset(monkeypatch):
    monkeypatch.delenv("TAILSCALE_HOST", raising=False)
    class R: returncode = 0; stdout = "100.101.102.103\n"
    assert detect_host(load_settings(), runner=lambda *a, **k: R()) == "100.101.102.103"


def test_none_when_cli_missing(monkeypatch):
    monkeypatch.delenv("TAILSCALE_HOST", raising=False)
    def boom(*a, **k): raise FileNotFoundError()
    assert detect_host(load_settings(), runner=boom) is None
```

```python
# tests/career_agent/test_human_loop.py
from career_agent.integrations.human_loop import HumanLoop


class YesApprover:
    def request(self, card): return True


def test_approve_delegates():
    assert HumanLoop(YesApprover()).approve("card") is True


def test_remote_solve_without_factory_returns_false():
    # no live-view configured -> caller must degrade to stop-and-report
    hl = HumanLoop(YesApprover(), remote_solve_factory=None)
    assert hl.remote_solve(page=object(), gate="hcaptcha_checkbox", on_link=lambda u: None) is False


def test_remote_solve_with_factory_reports_link_and_outcome():
    seen = {}
    class FakeSession:
        def __init__(self, page): pass
        def start(self): return "http://mac.ts.net:8765/s/abc"
        def wait_until_cleared(self, timeout_s): return True
        def close(self): seen["closed"] = True
    hl = HumanLoop(YesApprover(), remote_solve_factory=lambda page: FakeSession(page))
    ok = hl.remote_solve(page=object(), gate="hcaptcha_checkbox",
                         on_link=lambda u: seen.setdefault("url", u))
    assert ok is True
    assert seen["url"].endswith("/s/abc")
    assert seen["closed"] is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_tailscale.py tests/career_agent/test_human_loop.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write `tailscale.py`**

```python
# src/career_agent/integrations/live_view/tailscale.py
"""Resolve the tailnet host for the live-view link."""
from __future__ import annotations

import subprocess


def detect_host(settings, runner=subprocess.run) -> str | None:
    if settings.tailscale_host:
        return settings.tailscale_host
    try:
        res = runner(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if getattr(res, "returncode", 1) != 0:
        return None
    line = (res.stdout or "").strip().splitlines()
    return line[0].strip() if line else None
```

- [ ] **Step 4: Write `human_loop.py`**

```python
# src/career_agent/integrations/human_loop.py
"""Facade the run loop talks to: approvals and remote-solve. Keeps the run
loop ignorant of Telegram/CDP details, and degrades safely when remote solve
is not configured."""
from __future__ import annotations


class HumanLoop:
    def __init__(self, approver, remote_solve_factory=None, deadline_s: int = 900):
        self.approver = approver
        self.remote_solve_factory = remote_solve_factory
        self.deadline_s = deadline_s

    def approve(self, card: str) -> bool:
        return self.approver.request(card)

    def remote_solve(self, page, gate: str, on_link) -> bool:
        if self.remote_solve_factory is None:
            return False  # caller degrades to Phase-1 stop-and-report
        session = self.remote_solve_factory(page)
        try:
            on_link(session.start())
            return bool(session.wait_until_cleared(self.deadline_s))
        finally:
            session.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_tailscale.py tests/career_agent/test_human_loop.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/integrations/human_loop.py src/career_agent/integrations/live_view/tailscale.py tests/career_agent/test_human_loop.py tests/career_agent/test_tailscale.py
git commit -m "feat(career-agent): human-loop facade + tailscale host detection"
```

---

### Task 8: Wire the run loop — Telegram approval + interactive-gate remote solve

**Files:**
- Modify: `src/career_agent/run.py`
- Test: `tests/career_agent/test_run_flow_phase2.py`

**Interfaces:**
- Change `run_once` to take a `human` (`HumanLoop`) instead of a bare `approver`, and an `on_link` callback:
  `run_once(page, profile, resume_path, meta, human, do_submit, on_link=None) -> dict`.
- Behavior:
  - After perceive + classify, if `HANDLERS[gate] == "escalate"` **and** gate is in `INTERACTIVE_GATES` (checkbox/image captchas), call `human.remote_solve(page, gate, on_link)`. If it returns True, **re-classify** the gate (should now be `cleared`/`none`) and continue; if False, do **not** submit — return with `remote_solve_attempted`.
  - Submit still requires `do_submit` AND a clear gate AND `human.approve(card)`.
- Add `INTERACTIVE_GATES = {"recaptcha_v2_checkbox","recaptcha_v2_image","hcaptcha_checkbox","hcaptcha_image"}`.
- `run_result` dict gains `"remote_solve_attempted": bool`, `"gate_after_solve": str|None`.

- [ ] **Step 1: Write the failing test (fakes — no browser)**

```python
# tests/career_agent/test_run_flow_phase2.py
from career_agent.browser.form_model import Field
from career_agent import run as runmod


class FakePage:
    def __init__(self): self.submitted = False
    def click_submit(self): self.submitted = True


class HumanStub:
    def __init__(self, approve, solve):
        self._a = approve
        self._s = solve
    def approve(self, card): return self._a
    def remote_solve(self, page, gate, on_link):
        if on_link: on_link("http://mac.ts.net:8765/s/abc")
        return self._s


def _form():
    return [Field("#n", "text", "Full name", True, [], None, "full_name")]


def _meta():
    return {"company": "Acme", "role": "Eng", "portal": "acme.com"}


def _patch(monkeypatch, gates):
    # gates is a list of classify_gate return values across successive calls
    seq = iter(gates)
    monkeypatch.setattr(runmod, "snapshot_form", lambda p: _form())
    monkeypatch.setattr(runmod, "classify_gate", lambda p: next(seq))
    monkeypatch.setattr(runmod, "apply_decisions", lambda p, d: None)


def test_interactive_gate_triggers_remote_solve_then_submits(monkeypatch):
    _patch(monkeypatch, ["hcaptcha_checkbox", "none"])  # after solve -> none
    page = FakePage()
    human = HumanStub(approve=True, solve=True)
    seen = {}
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human,
                          do_submit=True, on_link=lambda u: seen.setdefault("u", u))
    assert out["remote_solve_attempted"] is True
    assert out["gate_after_solve"] == "none"
    assert out["submitted"] is True and page.submitted is True
    assert seen["u"].endswith("/s/abc")


def test_failed_remote_solve_blocks_submit(monkeypatch):
    _patch(monkeypatch, ["hcaptcha_checkbox"])  # never re-classified (solve fails)
    page = FakePage()
    human = HumanStub(approve=True, solve=False)
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human, do_submit=True)
    assert out["remote_solve_attempted"] is True
    assert out["submitted"] is False and page.submitted is False


def test_clear_gate_skips_remote_solve(monkeypatch):
    _patch(monkeypatch, ["none"])
    page = FakePage()
    human = HumanStub(approve=True, solve=True)
    out = runmod.run_once(page, {"full_name": "T"}, None, _meta(), human, do_submit=True)
    assert out["remote_solve_attempted"] is False
    assert out["submitted"] is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_run_flow_phase2.py -v`
Expected: FAIL — `run_once` signature/behavior differ.

- [ ] **Step 3: Update `run.py`**

Replace `run_once` (keep imports; add `HANDLERS` already imported):

```python
INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                     "hcaptcha_checkbox", "hcaptcha_image"}


def run_once(page, profile, resume_path, meta, human, do_submit, on_link=None) -> dict:
    form = snapshot_form(page)
    gate = classify_gate(page)
    decisions = map_fields(form, profile, resume_path)
    apply_decisions(page, decisions)

    remote_solve_attempted = False
    gate_after_solve = None
    if HANDLERS.get(gate, "escalate") == "escalate" and gate in INTERACTIVE_GATES:
        remote_solve_attempted = True
        if human.remote_solve(page, gate, on_link or (lambda u: None)):
            gate = classify_gate(page)       # re-read after the human solved it
            gate_after_solve = gate

    card = render_card(meta["company"], meta["role"], meta["portal"], decisions, gate)
    gate_clear = HANDLERS.get(gate, "escalate") == "proceed"
    approved = submitted = False
    if do_submit and gate_clear:
        approved = human.approve(card)
        if approved:
            _click_submit(page)
            submitted = True

    return {"gate": gate, "card": card, "approved": approved, "submitted": submitted,
            "decisions": decisions, "remote_solve_attempted": remote_solve_attempted,
            "gate_after_solve": gate_after_solve}
```

Update `main()` to build the `HumanLoop`: if `settings.telegram_bot_token`, use `TelegramApprover(TelegramClient(...))`, and (if `detect_host` succeeds) a `remote_solve_factory` that builds a `RemoteSolveSession`; else fall back to `HumanLoop(CliApprover())` with no factory. Pass an `on_link` that sends the URL via the Telegram client. (Wiring only — no new logic; the tested seam is `run_once`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_run_flow_phase2.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Update the old Phase-1 run-flow test**

`tests/career_agent/test_run_flow.py` used a bare approver + old signature. Update its three tests to pass a `HumanLoop(YesApprover())`/`HumanLoop(NoApprover())` and the new keyword args, asserting the same submit/no-submit outcomes (gate `none`, no interactive gate → `remote_solve_attempted is False`).

- [ ] **Step 6: Run the whole suite**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent -q`
Expected: all pass; the two `*_browser.py` files SKIP without `RUN_BROWSER_TESTS=1`.

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/run.py tests/career_agent/test_run_flow_phase2.py tests/career_agent/test_run_flow.py
git commit -m "feat(career-agent): run loop routes interactive gates to remote solve; telegram approval"
```

---

## Manual smoke (after Task 8 — needs a Telegram bot + Tailscale)

One-time human setup (yours to do): create a bot via @BotFather, get the token + your chat id, set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, ensure `tailscale` is up on the Mac and your phone is on the tailnet. Then a dry-run against a captcha'd page should: fill what it can → send you a Telegram card → on an interactive gate, send a tap-to-solve link → you solve on your phone → the agent detects the token and continues. Nothing submits without your Submit tap.

---

## Self-Review (completed by plan author)

- **Spec coverage (remote-solve spec):** CDP screencast + pointer relay (Task 6), single-use/TTL token + URL (Task 4), tailnet-only host detection (Task 7), is_cleared token detection (Task 5), Telegram delivery of the link + approval (Tasks 2/3/8), safe degradation when unconfigured (Task 7 `remote_solve` → False → Task 8 blocks submit). ✔
- **Human-only / no-evasion:** `forward_pointer` only relays events it is handed; no synthetic input, no mouse modeling; `gate_probe` stays detection-only. ✔
- **Private-by-default:** server binds to the detected tailnet host; `build_url` refuses without a host unless public is explicitly enabled. ✔
- **Placeholder scan:** every code/test step has real code; no TBD/TODO. ✔
- **Type consistency:** `Approver.request` reused by `TelegramApprover`; `HumanLoop.approve/remote_solve` signatures match `run_once`'s calls; `SolveToken`/`mint_token`/`check_and_consume` names consistent across Tasks 4/6; `norm_to_px` used by `cdp_bridge`. ✔
- **Phase-1 regression:** Task 8 Step 5 updates the old run-flow test to the new signature so the suite stays green. ✔
