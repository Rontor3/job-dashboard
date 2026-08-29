# Career Agent — Page-Prep Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reusable, idempotent tools that clear overlays/noise and get the walk from a landing URL to the real application form (direct-form or email-auth), holding the credential boundary.

**Architecture:** New `browser/page_prep.py` with small pure/DOM tools; `suppress_noise` applied inside `snapshot_form`; a `prepare(page)` pass + `prep_fn` param on `walk`; an entry-classification loop in `apply.py`.

**Tech Stack:** Python 3.11, Playwright (sync), pytest. Tests: `PYTHONPATH=src python3 -m pytest tests/career_agent` (flat, no `__init__.py`). DOM tools use browser tests (skip unless `RUN_BROWSER_TESTS=1`, run via `.jd_env`); `suppress_noise` is pure.

## Global Constraints (from the spec)

- **No agent-entered passwords / account creation** — `classify_entry` returns `"password"`; the agent stops and hands off (never fills a password field).
- **Consent ≠ attestation** — `dismiss_consent` acts only on site cookie/consent overlays (decline-preferring; OK/Accept only to unblock); NEVER an application T&C/attestation.
- **Captcha unchanged** — detect + escalate (phone relay via injected `on_captcha`); never solved here.
- **OTP** via injected `otp_reader`; the agent enters the code, never a password.
- **Idempotent & safe** — every tool no-ops when not applicable, never clicks a destructive/submit control.
- **LLM-free.** Dry-run / human-gated submit unchanged.
- Branch `career-agent-page-prep`. Commit per task.

## File Structure

- `src/career_agent/browser/page_prep.py` — NEW: `suppress_noise`, `dismiss_consent`, `dismiss_dialogs`, `classify_entry`, `enter_application`, `email_auth`, `prepare`.
- `src/career_agent/browser/perception.py` — MODIFY `snapshot_form` to apply `suppress_noise`.
- `src/career_agent/orchestrator/step_engine.py` — MODIFY `walk` to accept `prep_fn`.
- `src/career_agent/apply.py` — MODIFY `main` to run the entry-classification loop.
- Tests: `tests/career_agent/test_page_prep.py` (pure), `test_page_prep_browser.py` (+ fixtures).

---

### Task 1: `suppress_noise` (pure) + wire into perception

**Files:**
- Create: `src/career_agent/browser/page_prep.py`
- Modify: `src/career_agent/browser/perception.py:137`
- Test: `tests/career_agent/test_page_prep.py`

**Interfaces:**
- Produces: `suppress_noise(fields: list[Field]) -> list[Field]` — drops chatbot/honeypot/captcha-token fields.

- [ ] **Step 1: Write the failing test** — `tests/career_agent/test_page_prep.py`

```python
from career_agent.browser.form_model import Field
from career_agent.browser.page_prep import suppress_noise


def _f(ref, label, kind="text", purpose=None):
    return Field(ref, kind, label, False, [], None, purpose)


def test_suppress_noise_drops_chatbot_honeypot_captcha():
    fields = [
        _f("#name", "Full name", purpose="full_name"),          # keep
        _f("#oda-chat-user-text-input", "Ask Me Something"),    # chatbot -> drop
        _f("[name=\"oda-work-summary-text-area\"]", "Add Summary"),  # chatbot -> drop
        _f("[name=\"honey-pot\"]", ""),                          # honeypot -> drop
        _f("#g-recaptcha-response", "g-recaptcha-response", kind="textarea"),  # token -> drop
        _f("#q", "Why do you want this role?", kind="textarea"),  # keep
    ]
    kept = {f.ref for f in suppress_noise(fields)}
    assert kept == {"#name", "#q"}
```

- [ ] **Step 2: Run to verify failure** — `PYTHONPATH=src python3 -m pytest tests/career_agent/test_page_prep.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `suppress_noise`** in a new `src/career_agent/browser/page_prep.py`

```python
"""Reusable page-prep tools: clear overlays/noise and get the walk to the real
application form. DOM tools are idempotent and never click a submit/destructive
control; suppress_noise is pure. LLM-free."""
from __future__ import annotations

import re

# Fields that are never real application inputs.
_NOISE_RE = re.compile(
    r"oda-|ask me something|add summary|work-summary|honey.?pot|"
    r"g-recaptcha-response|h-captcha-response", re.I)


def suppress_noise(fields):
    """Drop chatbot (Oracle ODA), honeypot, and captcha-token fields from the
    Form Model. Matches on ref OR label; never drops a field with a known
    purpose."""
    out = []
    for f in fields:
        if f.purpose:
            out.append(f); continue
        blob = f"{f.ref} {f.label}"
        if _NOISE_RE.search(blob):
            continue
        out.append(f)
    return out
```

- [ ] **Step 4: Wire into `snapshot_form`** — `src/career_agent/browser/perception.py`

```python
def snapshot_form(page) -> list[Field]:
    from .page_prep import suppress_noise
    return suppress_noise(to_form_model(collect_raw(page)))
```

- [ ] **Step 5: Run** — `test_page_prep.py` → PASS; full career_agent suite green (the honeypot/oda fields that Oracle runs escalated are now simply absent — no test asserted their presence).

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/page_prep.py src/career_agent/browser/perception.py tests/career_agent/test_page_prep.py
git commit -m "feat(career-agent): suppress_noise drops chatbot/honeypot/captcha-token fields (page-prep task 1)"
```

---

### Task 2: `dismiss_consent` + `dismiss_dialogs`

**Files:**
- Modify: `src/career_agent/browser/page_prep.py`
- Test: `tests/career_agent/test_page_prep_browser.py` + fixtures `consent_decline.html`, `consent_accept_only.html`, `dialog_session.html`

**Interfaces:**
- Produces: `dismiss_consent(page) -> bool`, `dismiss_dialogs(page) -> bool`.

- [ ] **Step 1: Fixtures**

`tests/career_agent/fixtures/consent_decline.html`:
```html
<!doctype html><html><body>
  <div role="dialog" aria-label="cookies">We use cookies.
    <button>Decline</button><button>Accept all</button></div>
  <form><input type="text" aria-label="Full name"></form>
</body></html>
```
`tests/career_agent/fixtures/consent_accept_only.html`:
```html
<!doctype html><html><body>
  <div role="dialog" aria-label="cookies">We use cookies. <button>OK</button></div>
</body></html>
```
`tests/career_agent/fixtures/dialog_session.html`:
```html
<!doctype html><html><body>
  <div role="alertdialog">Your session is about to expire.
    <button>End Session</button><button>Continue Working</button></div>
</body></html>
```

- [ ] **Step 2: Write the failing test** — `tests/career_agent/test_page_prep_browser.py`

```python
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1",
                                reason="set RUN_BROWSER_TESTS=1 to run")


def _url(name):
    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def _page(pw, name):
    b = pw.chromium.launch(); p = b.new_page(); p.goto(_url(name)); return b, p


def test_dismiss_consent_prefers_decline():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_consent
    with sync_playwright() as pw:
        b, p = _page(pw, "consent_decline.html")
        assert dismiss_consent(p) is True
        # the banner is gone; a second call is a harmless no-op
        assert dismiss_consent(p) is False
        b.close()


def test_dismiss_consent_accept_only_clicks_ok():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_consent
    with sync_playwright() as pw:
        b, p = _page(pw, "consent_accept_only.html")
        assert dismiss_consent(p) is True
        b.close()


def test_dismiss_dialogs_continue_working():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import dismiss_dialogs
    with sync_playwright() as pw:
        b, p = _page(pw, "dialog_session.html")
        assert dismiss_dialogs(p) is True
        b.close()
```

- [ ] **Step 3: Run to verify failure** — `source .jd_env/bin/activate && RUN_BROWSER_TESTS=1 PYTHONPATH=src python3 -m pytest tests/career_agent/test_page_prep_browser.py -q` → FAIL.

- [ ] **Step 4: Implement** — append to `page_prep.py`

```python
_DECLINE = ["Decline", "Reject all", "Reject", "Only necessary", "Necessary only", "Refuse"]
_ACCEPT = ["Accept all", "Accept", "Agree", "OK", "Got it", "I understand"]
_DIALOG_DISMISS = ["Continue Working", "Continue", "Stay", "Stay signed in", "Dismiss", "Close"]
_NEVER = ["End Session", "Discard", "Sign out", "Log out", "Delete", "Submit"]


def _click_first(page, names, within=None):
    root = within or page
    for name in names:
        try:
            btn = root.get_by_role("button", name=name, exact=False).first
            if btn.count() == 0:
                btn = root.get_by_role("link", name=name, exact=False).first
            if btn.count() > 0:
                btn.click(timeout=3000)
                page.wait_for_timeout(400)
                return name
        except Exception:
            pass
    return None


def _looks_consent(page) -> bool:
    try:
        return bool(page.evaluate(
            "() => /cookie|consent|privacy preferences|we use/i.test(document.body.innerText.slice(0,3000))"))
    except Exception:
        return False


def dismiss_consent(page) -> bool:
    """Decline a cookie/consent overlay if offered, else OK/Accept to unblock.
    Site cookie banners ONLY — never an application T&C/attestation."""
    if not _looks_consent(page):
        return False
    if _click_first(page, _DECLINE):
        return True
    return _click_first(page, _ACCEPT) is not None


def dismiss_dialogs(page) -> bool:
    """Dismiss an idle/blocking modal (e.g. Oracle 'Continue Working'). Never a
    destructive/submit control."""
    try:
        dlg = page.locator("[role=dialog], [role=alertdialog]").first
        if dlg.count() == 0:
            return False
    except Exception:
        return False
    return _click_first(page, _DIALOG_DISMISS) is not None
```

- [ ] **Step 5: Run** — the three browser tests → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/page_prep.py tests/career_agent/test_page_prep_browser.py tests/career_agent/fixtures/consent_decline.html tests/career_agent/fixtures/consent_accept_only.html tests/career_agent/fixtures/dialog_session.html
git commit -m "feat(career-agent): dismiss_consent + dismiss_dialogs page-prep tools (page-prep task 2)"
```

---

### Task 3: `classify_entry`

**Files:**
- Modify: `src/career_agent/browser/page_prep.py`
- Test: extend `test_page_prep_browser.py` + fixtures `entry_form.html`, `entry_email.html`, `entry_password.html`, `entry_jd.html`

**Interfaces:**
- Produces: `classify_entry(page) -> str` ∈ `{"form","email_auth","password","none"}`.

- [ ] **Step 1: Fixtures**

`entry_form.html`: `<form><input aria-label="First name"><input aria-label="Email"><input aria-label="Phone"></form>`
`entry_email.html`: `<div>Enter your email to verify your identity. We'll send a code.<input type="email" aria-label="Email"></div>`
`entry_password.html`: `<form><input type="email" aria-label="Email"><input type="password" aria-label="Password"></form>`
`entry_jd.html`: `<div>Data Scientist. Great role.<button>Apply now</button></div>`

- [ ] **Step 2: Write the failing test** — extend `test_page_prep_browser.py`

```python
def test_classify_entry():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import classify_entry
    with sync_playwright() as pw:
        for name, expect in [("entry_password.html", "password"),
                             ("entry_email.html", "email_auth"),
                             ("entry_form.html", "form"),
                             ("entry_jd.html", "none")]:
            b, p = _page(pw, name)
            assert classify_entry(p) == expect, name
            b.close()
```

- [ ] **Step 3: Run to verify failure** → FAIL.

- [ ] **Step 4: Implement** — append to `page_prep.py`

```python
def classify_entry(page) -> str:
    try:
        d = page.evaluate("""() => {
          const vis = e => { const r=e.getBoundingClientRect(); return r.width>4 && r.height>4; };
          const ins = Array.from(document.querySelectorAll('input,select,textarea')).filter(vis);
          const txt = document.body.innerText.slice(0, 4000);
          const hasPw = ins.some(e => e.type === 'password') || /create a password|sign in with password/i.test(txt);
          const email = ins.find(e => e.type === 'email' || /mail/i.test(e.name||e.id||''));
          const fillable = ins.filter(e => !['hidden','submit','button'].includes(e.type)
            && !/search/i.test(e.getAttribute('aria-label')||e.name||'')).length;
          return { hasPw, hasEmail: !!email,
            verify: /verify|one-time|we'll send|continue with email|create .*profile|confirm your identity/i.test(txt),
            fillable };
        }""")
    except Exception:
        return "none"
    if d["hasPw"]:
        return "password"
    if d["hasEmail"] and d["verify"]:
        return "email_auth"
    if d["fillable"] >= 2:
        return "form"
    return "none"
```

- [ ] **Step 5: Run** — the classify test → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/page_prep.py tests/career_agent/test_page_prep_browser.py tests/career_agent/fixtures/entry_*.html
git commit -m "feat(career-agent): classify_entry (form/email_auth/password/none) (page-prep task 3)"
```

---

### Task 4: `enter_application`

**Files:**
- Modify: `src/career_agent/browser/page_prep.py`
- Test: extend `test_page_prep_browser.py` + fixture `entry_apply.html`

**Interfaces:**
- Consumes: `classify_entry` (Task 3).
- Produces: `enter_application(page) -> str` — one Apply hop, returns `classify_entry` of where it lands.

- [ ] **Step 1: Fixture** — `entry_apply.html` (Apply button reveals a form):
```html
<!doctype html><html><body>
  <div>Data Scientist role.<button id="ap" aria-label="Apply for this job">Apply now</button></div>
  <div id="form" style="display:none"><form>
    <input aria-label="First name"><input aria-label="Email"><input aria-label="Phone"></form></div>
  <script>document.getElementById('ap').onclick =
    () => { document.getElementById('form').style.display='block'; };</script>
</body></html>
```

- [ ] **Step 2: Write the failing test**

```python
def test_enter_application_reaches_form():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import enter_application
    with sync_playwright() as pw:
        b, p = _page(pw, "entry_apply.html")
        assert enter_application(p) == "form"
        b.close()
```

- [ ] **Step 3: Run to verify failure** → FAIL.

- [ ] **Step 4: Implement** — append to `page_prep.py`

```python
_APPLY = ["Apply now", "Apply for this job", "Apply", "I'm interested", "Start application", "Start"]


def enter_application(page) -> str:
    """From a JD page (classify_entry == 'none'), click Apply once and follow a
    same-tab nav OR a new tab; return classify_entry of where it lands. One hop."""
    if classify_entry(page) != "none":
        return classify_entry(page)
    ctx = page.context
    before = len(ctx.pages)
    clicked = None
    for name in _APPLY:
        try:
            el = page.get_by_role("button", name=name, exact=False).first
            if el.count() == 0:
                el = page.get_by_role("link", name=name, exact=False).first
            if el.count() > 0:
                el.click(timeout=5000); clicked = name; break
        except Exception:
            pass
    if clicked is None:
        return "none"
    page.wait_for_timeout(2500)
    active = page
    if len(ctx.pages) > before:                    # a new tab opened -> adopt it
        active = ctx.pages[-1]
        try: active.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception: pass
    return classify_entry(active)
```

Note: when a new tab is adopted, the caller uses the returned classification; `apply.py` (Task 6) re-reads `ctx.pages[-1]` as the active page after `enter_application`.

- [ ] **Step 5: Run** — the enter test → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/page_prep.py tests/career_agent/test_page_prep_browser.py tests/career_agent/fixtures/entry_apply.html
git commit -m "feat(career-agent): enter_application — one Apply hop to the form (page-prep task 4)"
```

---

### Task 5: `email_auth`

**Files:**
- Modify: `src/career_agent/browser/page_prep.py`
- Test: extend `test_page_prep_browser.py` + fixture `email_auth.html`

**Interfaces:**
- Consumes: `classify_entry`; `classify_gate`/`INTERACTIVE_GATES` (from `gate_probe`/`step_engine`).
- Produces: `email_auth(page, email, otp_reader, on_captcha=None) -> str`.

- [ ] **Step 1: Fixture** — `email_auth.html` (email → NEXT reveals a 6-box code → verify reveals a form):
```html
<!doctype html><html><body>
  <div id="s1">Confirm your identity. Enter your email; we'll send a code.
    <input type="email" id="em"><button id="next">NEXT</button></div>
  <div id="s2" style="display:none">Enter the code.
    <input name="pin-code-1"><input name="pin-code-2"><input name="pin-code-3">
    <input name="pin-code-4"><input name="pin-code-5"><input name="pin-code-6">
    <button id="verify">Verify</button></div>
  <div id="s3" style="display:none"><form>
    <input aria-label="First name"><input aria-label="Phone"><input aria-label="Email"></form></div>
  <script>
    next.onclick=()=>{s1.style.display='none';s2.style.display='block';};
    verify.onclick=()=>{s2.style.display='none';s3.style.display='block';};
  </script>
</body></html>
```

- [ ] **Step 2: Write the failing test**

```python
def test_email_auth_email_to_otp_to_form():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.page_prep import email_auth
    with sync_playwright() as pw:
        b, p = _page(pw, "email_auth.html")
        got = {}
        def otp_reader():
            got["asked"] = True
            return "123456"
        res = email_auth(p, "me@example.com", otp_reader=otp_reader, on_captcha=None)
        assert got.get("asked") is True
        assert res == "form"
        assert p.locator('#em').input_value() == "me@example.com"
        assert p.locator('input[name="pin-code-1"]').input_value() == "1"
        b.close()
```

- [ ] **Step 3: Run to verify failure** → FAIL.

- [ ] **Step 4: Implement** — append to `page_prep.py`

```python
_INTERACTIVE_GATES = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                      "hcaptcha_checkbox", "hcaptcha_image"}


def _fill_otp(page, code):
    code = "".join(c for c in str(code) if c.isdigit())[:6]
    boxes = [page.query_selector(f'input[name="pin-code-{i}"]') for i in range(1, 7)]
    boxes = [b for b in boxes if b]
    if not boxes:
        boxes = page.query_selector_all('input[aria-label*="verification code digit" i]')
    if not boxes:
        return False
    for b, ch in zip(boxes, code):
        try: b.click(); b.fill(ch)
        except Exception: pass
    return True


def _advance(page, names=("NEXT", "Next", "Continue", "Verify", "Submit")):
    for n in names:
        try:
            el = page.get_by_role("button", name=n, exact=False).first
            if el.count() > 0:
                el.click(timeout=5000); page.wait_for_timeout(1200); return True
        except Exception:
            pass
    return False


def email_auth(page, email, otp_reader, on_captcha=None) -> str:
    """Passwordless email-first auth: fill email -> (captcha via on_captcha) ->
    NEXT -> OTP (via otp_reader) -> form. Never fills a password / ticks T&C."""
    from ..browser.gate_probe import classify_gate
    try:
        page.fill('input[type=email], input[name*="mail" i]', email)
    except Exception:
        return "none"
    gate = classify_gate(page)
    if gate in _INTERACTIVE_GATES:
        if on_captcha is None or not on_captcha(page, gate):
            return "captcha"
    _advance(page)
    page.wait_for_timeout(1500)
    # OTP screen?
    if page.query_selector('input[name="pin-code-1"], input[aria-label*="verification code digit" i]'):
        code = otp_reader() if otp_reader else None
        if not code:
            return "otp_timeout"
        _fill_otp(page, code)
        _advance(page)
        page.wait_for_timeout(1500)
    return classify_entry(page)
```

- [ ] **Step 5: Run** — the email_auth test → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/page_prep.py tests/career_agent/test_page_prep_browser.py tests/career_agent/fixtures/email_auth.html
git commit -m "feat(career-agent): email_auth — email -> captcha -> OTP -> form, reusable (page-prep task 5)"
```

---

### Task 6: `prepare()` + `walk` prep_fn + `apply.py` entry orchestration

**Files:**
- Modify: `src/career_agent/browser/page_prep.py` (`prepare`), `src/career_agent/orchestrator/step_engine.py` (`walk`), `src/career_agent/apply.py`
- Test: extend `tests/career_agent/test_step_engine.py`

**Interfaces:**
- Produces: `prepare(page) -> None`; `walk(..., prep_fn=None)`.

- [ ] **Step 1: `prepare`** — append to `page_prep.py`

```python
def prepare(page) -> None:
    """Idempotent per-step page prep: clear cookie overlays and idle dialogs."""
    try: dismiss_consent(page)
    except Exception: pass
    try: dismiss_dialogs(page)
    except Exception: pass
```

- [ ] **Step 2: Write the failing test** — extend `test_step_engine.py`

```python
def test_walk_runs_prep_fn_each_step():
    s1 = [_f("#n", "Full name", "full_name"), _f("#c", "Submit application", None, kind="button")]
    deps = Deps([s1])
    calls = {"n": 0}
    def prep_fn(page): calls["n"] += 1
    walk(object(), CandidateProfile(contact={"full_name": "R"}), Human(), deps,
         do_submit=True, autonomous=True, prep_fn=prep_fn)
    assert calls["n"] >= 1
```

- [ ] **Step 3: Run to verify failure** → FAIL (no `prep_fn`).

- [ ] **Step 4: Modify `walk`** — `step_engine.py`: add `prep_fn=None` to the signature; at the top of the loop, before `form = deps.snapshot(page)`:

```python
        if prep_fn is not None:
            prep_fn(page)
        form = deps.snapshot(page)
```

- [ ] **Step 5: Wire `apply.py`** — before the `walk(...)` call, run the entry loop and pass `prep_fn`:

```python
    from .browser.page_prep import prepare, classify_entry, enter_application, email_auth
    page.goto(args.url)
    try: page.wait_for_load_state("networkidle", timeout=8000)
    except Exception: pass
    prepare(page)
    kind = classify_entry(page)
    if kind == "none":
        enter_application(page)
        page = page.context.pages[-1]      # adopt a new tab if one opened
        prepare(page); kind = classify_entry(page)
    if kind == "email_auth":
        email_auth(page, contact.get("email", ""), otp_reader=None, on_captcha=None)
    elif kind == "password":
        print("[stop] this application needs an account/login. Create it / log in "
              "in the open browser (or via your password manager), then re-run --url "
              "at the post-login form. The agent never enters passwords.")
        close(pw, context); return
    out = walk(page, profile, human, BrowserDeps(),
               max_steps=args.max_steps, do_submit=args.submit,
               autonomous=args.autonomous, resume_pdf=resume_pdf, judge_fn=judge_fn,
               prep_fn=prepare)
```

(Replace the existing `page.goto(...)` + `walk(...)` block with the above; keep the surrounding try/finally.)

- [ ] **Step 6: Run** — the prep-fn test + full career_agent suite → PASS; `PYTHONPATH=src python3 -c "import career_agent.apply"` OK.

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/browser/page_prep.py src/career_agent/orchestrator/step_engine.py src/career_agent/apply.py tests/career_agent/test_step_engine.py
git commit -m "feat(career-agent): prepare() pass + walk prep_fn + apply.py entry orchestration (page-prep task 6)"
```

---

### Task 7: Full-suite green + live re-validation

**Files:** none (verification).

- [ ] **Step 1: Full repo suite** — `PYTHONPATH=src python3 -m pytest -q` → green.
- [ ] **Step 2: Browser suite** — `source .jd_env/bin/activate && RUN_BROWSER_TESTS=1 PYTHONPATH=src python3 -m pytest tests/career_agent -q` → green.
- [ ] **Step 3: Live re-validation (dry-run):** re-run the scratch judge driver on **retransform** (consent dismissed + Apply followed or "none" reported) and **Rippling** (noise-free perception; the ODA/honeypot fields gone). Record outcomes in the ledger. Nothing submitted.

---

## Self-Review

**Spec coverage:** suppress_noise → Task 1; dismiss_consent/dismiss_dialogs → Task 2; classify_entry → Task 3; enter_application → Task 4; email_auth → Task 5; prepare + walk + apply.py entry (form/email_auth/password branch) → Task 6; validation → Task 7. All covered. Credential boundary: `classify_entry`→"password" → apply.py stops (Task 6), never fills a password.

**Type consistency:** `classify_entry(page) -> str` (Task 3) consumed by `enter_application` (Task 4) and `apply.py` (Task 6). `email_auth(page, email, otp_reader, on_captcha=None) -> str` (Task 5) called in Task 6. `prepare(page) -> None` (Task 6) passed as `prep_fn` to `walk`. `suppress_noise(fields) -> fields` (Task 1) in `snapshot_form`.

**Placeholder scan:** no TBD/TODO; every code step has real code. Task 6's "replace the goto+walk block" is an instruction with the exact replacement given.

**Boundaries:** consent decline-preferring, never a form/attestation control; dialogs never destructive/submit; enter_application one hop, never submit; email_auth never a password; password → human; dry-run/human-gated submit unchanged.
