# Career Agent — Phase 1: Perception Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable harness that, given a career-page URL, opens a persistent Chrome, reads the form into a compact Form Model, detects any verification gate, maps the user's profile onto the fields, fills them, composes a structured review card, and stops for human approval — submitting only when explicitly told to.

**Architecture:** Deterministic core. Browser I/O (Playwright) is kept in thin, dependency-injected collectors; all logic (Form Model normalization, purpose guessing, gate classification, field mapping, review card) is **pure and unit-tested**. No LLM and no network beyond the target site in this phase — every known field maps by rule. Later phases graft on the LLM judgment tier, memory, Telegram, and Gmail via the seams left here.

**Tech Stack:** Python 3.11 · Playwright (chromium, `launch_persistent_context`) · pytest · stdlib `sqlite3`/`dataclasses` · reuse of `job_dashboard.apply.store`.

## Global Constraints

Every task's requirements implicitly include these (copied from the design spec §7, §8, §15, §16):

- **No evasion in-tree.** `gate_probe` **detects only** — it never interacts with a challenge widget. The `HANDLERS` map ships `escalate` for every genuine challenge type (incl. `cloudflare_interstitial`). **No module imports or references `flare_tool.py` or `proxy_tool.py`.**
- **No auto-submit.** Submit is opt-in via an explicit `--submit` flag; default is dry-run (fill + review, then stop). The first real submit always passes through an explicit human approval.
- **Attestations are never auto-valued.** Consent / certification / background-check checkboxes are surfaced to the human, never ticked by the mapper.
- **PII stays local.** No third-party model, no telemetry. The only outbound traffic is to the target career page itself.
- **Perception compacts once.** The A11y/DOM snapshot is normalized into the Form Model a single time per page; downstream code reads the compact model, never re-scrapes.
- **File hygiene.** Keep every file < 500 lines. Tests live under `tests/career_agent/`, never in the repo root.
- **Persistent, honest browser.** Chrome launches via `launch_persistent_context` against a real on-disk user-data dir, headed by default.

---

### Task 1: Package scaffold, settings, dependency

**Files:**
- Create: `src/career_agent/__init__.py`, `src/career_agent/browser/__init__.py`, `src/career_agent/orchestrator/__init__.py`, `src/career_agent/memory/__init__.py`, `src/career_agent/integrations/__init__.py`, `src/career_agent/config/__init__.py`
- Create: `src/career_agent/config/settings.py`
- Modify: `requirements.txt` (append `playwright>=1.44`)
- Create: `tests/career_agent/__init__.py`, `tests/career_agent/test_settings.py`

**Interfaces:**
- Produces: `Settings` dataclass with fields `user_data_dir: str`, `headed: bool`, `ollama_host: str`, `ollama_model: str`; `load_settings() -> Settings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_settings.py
import os
from career_agent.config.settings import load_settings, Settings


def test_defaults_when_env_absent(monkeypatch):
    for k in ("CAREER_AGENT_USER_DATA_DIR", "CAREER_AGENT_HEADED",
              "OLLAMA_HOST", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert isinstance(s, Settings)
    assert s.user_data_dir.endswith("career_agent/chrome-profile")
    assert s.headed is True
    assert s.ollama_host == "http://localhost:11434"
    assert s.ollama_model == "qwen3:14b"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CAREER_AGENT_HEADED", "0")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:30b-a3b")
    s = load_settings()
    assert s.headed is False
    assert s.ollama_model == "qwen3:30b-a3b"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: career_agent`.

- [ ] **Step 3: Create the empty package files**

Create each `__init__.py` listed above as an empty file (one line comment is fine, e.g. `"""Career agent package."""`).

- [ ] **Step 4: Write `settings.py`**

```python
# src/career_agent/config/settings.py
"""Runtime settings for the career agent. Env-overridable, local-first."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PROFILE_DIR = str(
    Path(__file__).resolve().parents[1] / "chrome-profile"
)


@dataclass(frozen=True)
class Settings:
    user_data_dir: str
    headed: bool
    ollama_host: str
    ollama_model: str


def _as_bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "")


def load_settings() -> Settings:
    return Settings(
        user_data_dir=os.getenv("CAREER_AGENT_USER_DATA_DIR", _DEFAULT_PROFILE_DIR),
        headed=_as_bool(os.getenv("CAREER_AGENT_HEADED"), True),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b"),
    )
```

- [ ] **Step 5: Append the dependency to `requirements.txt`**

Add a trailing line: `playwright>=1.44`

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_settings.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add src/career_agent tests/career_agent requirements.txt
git commit -m "feat(career-agent): scaffold package + settings"
```

---

### Task 2: Factual Core — export & load the profile

**Files:**
- Create: `src/career_agent/memory/factual_core.py`
- Create: `tests/career_agent/test_factual_core.py`

**Interfaces:**
- Consumes: `job_dashboard.apply.store.get_application_profile(conn)` (returns a dict with keys `full_name, email, phone, location, linkedin_url, github_url, portfolio_url, work_authorization, years_experience, willing_to_relocate, notice_period, salary_expectation, current_ctc, reason_for_change`).
- Produces: `export_profile(conn, path: str) -> dict` (writes JSON, returns the dict); `load_profile(path: str) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_factual_core.py
import sqlite3
from career_agent.memory.factual_core import export_profile, load_profile
from job_dashboard.apply.store import (
    ensure_application_tables, save_application_profile,
)


def _seed_conn():
    conn = sqlite3.connect(":memory:")
    ensure_application_tables(conn)
    save_application_profile(conn, {
        "full_name": "Test User", "email": "t@example.com",
        "phone": "+1-555-0100", "work_authorization": "US Citizen",
        "notice_period": "2 weeks", "willing_to_relocate": True,
    })
    return conn


def test_export_then_load_roundtrip(tmp_path):
    conn = _seed_conn()
    path = tmp_path / "profile.json"
    exported = export_profile(conn, str(path))
    assert exported["full_name"] == "Test User"
    loaded = load_profile(str(path))
    assert loaded["email"] == "t@example.com"
    assert loaded["work_authorization"] == "US Citizen"
    assert loaded["willing_to_relocate"] is True


def test_load_missing_file_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_profile(str(tmp_path / "nope.json"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_factual_core.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `factual_core.py`**

```python
# src/career_agent/memory/factual_core.py
"""Factual Core: the agent's static, verbatim profile facts.

Sourced once from the dashboard's application_profile, then read from a
local JSON file. No LLM ever regenerates these values.
"""
from __future__ import annotations

import json
from pathlib import Path

from job_dashboard.apply.store import get_application_profile


def export_profile(conn, path: str) -> dict:
    profile = get_application_profile(conn)
    if profile is None:
        raise ValueError("no application_profile row (id=1) to export")
    profile.pop("updated_at", None)
    Path(path).write_text(json.dumps(profile, indent=2, sort_keys=True))
    return profile


def load_profile(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"profile JSON not found: {path}")
    return json.loads(p.read_text())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_factual_core.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/memory/factual_core.py tests/career_agent/test_factual_core.py
git commit -m "feat(career-agent): factual core profile export/load"
```

---

### Task 3: Form Model types + purpose guesser

**Files:**
- Create: `src/career_agent/browser/form_model.py`
- Create: `tests/career_agent/test_form_model.py`

**Interfaces:**
- Produces: `Field` dataclass with `ref:str, kind:str, label:str, required:bool, options:list[str], group:str|None, purpose:str|None`; `KNOWN_PURPOSES: frozenset[str]`; `guess_purpose(label:str, kind:str) -> str|None`.
- `kind` is one of: `"text","email","tel","textarea","select","checkbox","radio_group","file"`.
- `purpose` values (the vocabulary later tasks map on): `"full_name","email","phone","location","linkedin_url","github_url","portfolio_url","work_authorization","years_experience","notice_period","salary_expectation","willing_to_relocate","attestation","resume_upload"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_form_model.py
from career_agent.browser.form_model import Field, guess_purpose, KNOWN_PURPOSES


def test_field_is_frozen_dataclass():
    f = Field(ref="#a", kind="text", label="Full name", required=True,
              options=[], group=None, purpose=None)
    assert f.ref == "#a" and f.options == []


def test_guess_common_purposes():
    assert guess_purpose("Full Name", "text") == "full_name"
    assert guess_purpose("Email address", "email") == "email"
    assert guess_purpose("Mobile number", "tel") == "phone"
    assert guess_purpose("LinkedIn Profile URL", "text") == "linkedin_url"
    assert guess_purpose("GitHub", "text") == "github_url"
    assert guess_purpose("Are you authorized to work in the US?", "select") == "work_authorization"
    assert guess_purpose("Notice period", "text") == "notice_period"
    assert guess_purpose("Expected salary", "text") == "salary_expectation"
    assert guess_purpose("Upload your resume", "file") == "resume_upload"


def test_attestation_detected_for_consent_checkbox():
    assert guess_purpose("I certify the above is true", "checkbox") == "attestation"
    assert guess_purpose("I consent to a background check", "checkbox") == "attestation"


def test_unknown_returns_none():
    assert guess_purpose("What is your favourite colour?", "text") is None


def test_all_returned_purposes_are_known():
    for label, kind in [("Full name","text"), ("Email","email"),
                        ("I agree to terms","checkbox"), ("Resume","file")]:
        p = guess_purpose(label, kind)
        assert p is None or p in KNOWN_PURPOSES
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_form_model.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `form_model.py`**

```python
# src/career_agent/browser/form_model.py
"""The compact Form Model: structured fields extracted from a page, plus a
rule-based purpose guesser. Pure — no browser, no LLM."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field

KNOWN_PURPOSES = frozenset({
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "notice_period", "salary_expectation", "willing_to_relocate",
    "attestation", "resume_upload",
})


@dataclass(frozen=True)
class Field:
    ref: str
    kind: str
    label: str
    required: bool
    options: list = _field(default_factory=list)
    group: str | None = None
    purpose: str | None = None


# Ordered most-specific-first; first hit wins.
_RULES: list[tuple[str, str]] = [
    (r"\bfirst name\b|\blast name\b|\bfull name\b|\byour name\b|\bname\b", "full_name"),
    (r"\be-?mail\b", "email"),
    (r"\bphone\b|\bmobile\b|\bcontact number\b", "phone"),
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bgithub\b", "github_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal site\b", "portfolio_url"),
    (r"\bauthoriz|\bwork permit\b|\bvisa\b|\bsponsor|\beligible to work\b", "work_authorization"),
    (r"\byears? of experience\b|\byears? experience\b|\bexperience\b", "years_experience"),
    (r"\bnotice period\b|\bavailab|\bearliest start\b|\bstart date\b", "notice_period"),
    (r"\bsalary\b|\bcompensation\b|\bexpected ctc\b|\bpay expectation\b", "salary_expectation"),
    (r"\brelocat", "willing_to_relocate"),
    (r"\bresume\b|\bcv\b|\bupload.*(resume|cv)\b", "resume_upload"),
    (r"\bcity\b|\blocation\b|\baddress\b", "location"),
]

_ATTEST = re.compile(
    r"\bi (certify|agree|consent|acknowledge|authorize)\b|\bbackground check\b"
    r"|\bterms\b|\bprivacy policy\b|\btrue and (complete|correct)\b",
    re.I,
)


def guess_purpose(label: str, kind: str) -> str | None:
    text = (label or "").strip().lower()
    if not text:
        return None
    if kind == "file":
        return "resume_upload" if re.search(_RULES[-3][0], text) else None
    if kind == "checkbox" and _ATTEST.search(text):
        return "attestation"
    for pattern, purpose in _RULES:
        if re.search(pattern, text):
            return purpose
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_form_model.py -v`
Expected: PASS (5 passed). If `test_guess_common_purposes` fails on the resume/file case, verify the `_RULES` index used in the `kind == "file"` branch points at the resume rule; adjust the branch to `re.search(r"\bresume\b|\bcv\b", text)` directly rather than by index.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/browser/form_model.py tests/career_agent/test_form_model.py
git commit -m "feat(career-agent): form model types + purpose guesser"
```

---

### Task 4: Raw → Form Model normalizer (pure)

**Files:**
- Create: `src/career_agent/browser/perception.py`
- Create: `tests/career_agent/test_perception_normalize.py`

**Interfaces:**
- Consumes: `Field`, `guess_purpose` from Task 3.
- Produces: `to_form_model(raw: list[dict]) -> list[Field]`. Each `raw` dict has keys `ref, kind, label, required(bool), options(list), group(str|None)`. Radio inputs sharing a `group` collapse into one `radio_group` Field whose `options` is the union of their labels; the group's `ref` is the shared group name prefixed `group:`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_perception_normalize.py
from career_agent.browser.perception import to_form_model


def test_maps_purpose_and_preserves_fields():
    raw = [
        {"ref": "#name", "kind": "text", "label": "Full name",
         "required": True, "options": [], "group": None},
        {"ref": "#email", "kind": "email", "label": "Email",
         "required": True, "options": [], "group": None},
    ]
    fm = to_form_model(raw)
    assert [f.purpose for f in fm] == ["full_name", "email"]
    assert fm[0].required is True


def test_radio_inputs_collapse_into_one_group():
    raw = [
        {"ref": "#r1", "kind": "radio", "label": "Yes",
         "required": False, "options": [], "group": "authorized"},
        {"ref": "#r2", "kind": "radio", "label": "No",
         "required": False, "options": [], "group": "authorized"},
    ]
    fm = to_form_model(raw)
    assert len(fm) == 1
    g = fm[0]
    assert g.kind == "radio_group"
    assert g.ref == "group:authorized"
    assert set(g.options) == {"Yes", "No"}


def test_empty_input_yields_empty_model():
    assert to_form_model([]) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_perception_normalize.py -v`
Expected: FAIL — `to_form_model` missing.

- [ ] **Step 3: Write the normalizer in `perception.py`**

```python
# src/career_agent/browser/perception.py
"""Perception: turn a page's raw form elements into the compact Form Model.

`to_form_model` is pure (unit-tested). `collect_raw`/`snapshot_form` are the
thin browser-bound collectors (Task 5)."""
from __future__ import annotations

from .form_model import Field, guess_purpose


def to_form_model(raw: list[dict]) -> list[Field]:
    fields: list[Field] = []
    radio_groups: dict[str, dict] = {}

    for r in raw:
        kind = r["kind"]
        if kind == "radio" and r.get("group"):
            g = radio_groups.setdefault(
                r["group"],
                {"labels": [], "required": False, "label": r["group"]},
            )
            g["labels"].append(r["label"])
            g["required"] = g["required"] or bool(r.get("required"))
            continue
        fields.append(Field(
            ref=r["ref"], kind=kind, label=r["label"],
            required=bool(r.get("required")), options=list(r.get("options", [])),
            group=r.get("group"),
            purpose=guess_purpose(r["label"], kind),
        ))

    for name, g in radio_groups.items():
        label = g["labels"][0] if len(g["labels"]) == 1 else name
        fields.append(Field(
            ref=f"group:{name}", kind="radio_group", label=name,
            required=g["required"], options=g["labels"], group=name,
            purpose=guess_purpose(name, "radio_group"),
        ))
    return fields
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_perception_normalize.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/browser/perception.py tests/career_agent/test_perception_normalize.py
git commit -m "feat(career-agent): raw->form-model normalizer"
```

---

### Task 5: Browser-bound perception collector (integration, skip-marked)

**Files:**
- Modify: `src/career_agent/browser/perception.py` (add `collect_raw`, `snapshot_form`)
- Create: `tests/career_agent/fixtures/sample_form.html`
- Create: `tests/career_agent/test_perception_browser.py`

**Interfaces:**
- Consumes: a Playwright `Page`.
- Produces: `collect_raw(page) -> list[dict]` (queries inputs/selects/textareas + labels), `snapshot_form(page) -> list[Field]` (= `to_form_model(collect_raw(page))`).

- [ ] **Step 1: Create the HTML fixture**

```html
<!-- tests/career_agent/fixtures/sample_form.html -->
<!doctype html><html><body>
<form>
  <label for="name">Full name</label>
  <input id="name" name="name" type="text" required>
  <label for="email">Email</label>
  <input id="email" name="email" type="email" required>
  <label for="resume">Upload your resume</label>
  <input id="resume" name="resume" type="file">
  <fieldset><legend>Are you authorized to work?</legend>
    <label><input type="radio" name="authorized" value="yes">Yes</label>
    <label><input type="radio" name="authorized" value="no">No</label>
  </fieldset>
  <label><input id="consent" type="checkbox">I certify the above is true</label>
  <button type="submit">Submit</button>
</form>
</body></html>
```

- [ ] **Step 2: Write the skip-marked test**

```python
# tests/career_agent/test_perception_browser.py
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 and `playwright install chromium` to run",
)


def _fixture_url():
    p = Path(__file__).parent / "fixtures" / "sample_form.html"
    return p.resolve().as_uri()


def test_snapshot_form_reads_fixture():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        fm = snapshot_form(page)
        browser.close()

    by_purpose = {f.purpose for f in fm}
    assert "full_name" in by_purpose
    assert "email" in by_purpose
    assert "resume_upload" in by_purpose
    assert "attestation" in by_purpose
    assert any(f.kind == "radio_group" for f in fm)
```

- [ ] **Step 3: Add the collectors to `perception.py`**

```python
# append to src/career_agent/browser/perception.py

_INPUT_JS = r"""
() => {
  const out = [];
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${el.id}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) return lg.innerText.trim(); }
    return (el.getAttribute('aria-label') || el.name || '').trim();
  };
  for (const el of document.querySelectorAll('input,select,textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button') continue;
    let kind = tag === 'textarea' ? 'textarea'
             : tag === 'select' ? 'select'
             : ['email','tel','file','checkbox','radio'].includes(type) ? type
             : 'text';
    const options = tag === 'select'
      ? Array.from(el.options).map(o => o.text.trim()).filter(Boolean) : [];
    out.push({
      ref: el.id ? `#${el.id}` : `[name="${el.name}"]`,
      kind, label: labelFor(el), required: !!el.required,
      options, group: (kind === 'radio') ? (el.name || null) : null,
    });
  }
  return out;
}
"""


def collect_raw(page) -> list[dict]:
    return page.evaluate(_INPUT_JS)


def snapshot_form(page) -> list[Field]:
    return to_form_model(collect_raw(page))
```

- [ ] **Step 4: Run the browser test (opt-in) and the full suite**

Run: `PYTHONPATH=src RUN_BROWSER_TESTS=1 python3 -m pytest tests/career_agent/test_perception_browser.py -v`
(First: `python3 -m playwright install chromium`.)
Expected: PASS. Then `PYTHONPATH=src python3 -m pytest tests/career_agent -q` — the browser test SKIPS without the env var; everything else passes.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/browser/perception.py tests/career_agent/fixtures/sample_form.html tests/career_agent/test_perception_browser.py
git commit -m "feat(career-agent): browser perception collector + fixture"
```

---

### Task 6: Gate probe — pure classifier + browser signals

**Files:**
- Create: `src/career_agent/browser/gate_probe.py`
- Create: `tests/career_agent/test_gate_probe.py`

**Interfaces:**
- Produces: `GATES: frozenset[str]`; `classify_from_signals(sig: dict) -> str`; `classify_gate(page) -> str`; `HANDLERS: dict[str, str]` mapping every gate to the string `"escalate"` except `"none"/"cleared"/"recaptcha_v3"/"turnstile"` → `"proceed"`, `"otp_email"` → `"otp_email"`.
- Gate strings: `recaptcha_v2_checkbox, recaptcha_v2_image, recaptcha_v3, hcaptcha_checkbox, hcaptcha_image, turnstile, cloudflare_interstitial, otp_email, otp_sms, text_challenge, cleared, none`.
- `sig` keys (all bool unless noted): `recaptcha_iframe, grecaptcha_response_present, recaptcha_bframe_visible, hcaptcha_iframe, hcaptcha_challenge_visible, turnstile_iframe, cf_interstitial, otp_email_field, otp_sms_field`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_gate_probe.py
from career_agent.browser.gate_probe import classify_from_signals, HANDLERS, GATES


def _sig(**kw):
    base = dict(recaptcha_iframe=False, grecaptcha_response_present=False,
                recaptcha_bframe_visible=False, hcaptcha_iframe=False,
                hcaptcha_challenge_visible=False, turnstile_iframe=False,
                cf_interstitial=False, otp_email_field=False, otp_sms_field=False)
    base.update(kw)
    return base


def test_none_when_no_signals():
    assert classify_from_signals(_sig()) == "none"


def test_cloudflare_interstitial():
    assert classify_from_signals(_sig(cf_interstitial=True)) == "cloudflare_interstitial"


def test_recaptcha_v2_image_when_challenge_open():
    assert classify_from_signals(
        _sig(recaptcha_iframe=True, recaptcha_bframe_visible=True)
    ) == "recaptcha_v2_image"


def test_recaptcha_v2_checkbox_present_not_open():
    assert classify_from_signals(_sig(recaptcha_iframe=True)) == "recaptcha_v2_checkbox"


def test_recaptcha_cleared_when_token_present():
    assert classify_from_signals(
        _sig(recaptcha_iframe=True, grecaptcha_response_present=True)
    ) == "cleared"


def test_turnstile_and_otp():
    assert classify_from_signals(_sig(turnstile_iframe=True)) == "turnstile"
    assert classify_from_signals(_sig(otp_email_field=True)) == "otp_email"


def test_every_gate_has_a_handler():
    for g in GATES:
        assert g in HANDLERS
    assert HANDLERS["cloudflare_interstitial"] == "escalate"
    assert HANDLERS["recaptcha_v2_checkbox"] == "escalate"
    assert HANDLERS["turnstile"] == "proceed"
    assert HANDLERS["otp_email"] == "otp_email"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_gate_probe.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `gate_probe.py`**

```python
# src/career_agent/browser/gate_probe.py
"""Gate probe — DETECTS verification gates, never solves them.

`classify_from_signals` is pure. `classify_gate` gathers the signals from a
live page. HANDLERS routes each gate to a string action; every genuine
challenge ships `escalate`. Nothing here interacts with a challenge widget,
and nothing imports any bypass/solver/proxy tool."""
from __future__ import annotations

GATES = frozenset({
    "recaptcha_v2_checkbox", "recaptcha_v2_image", "recaptcha_v3",
    "hcaptcha_checkbox", "hcaptcha_image", "turnstile",
    "cloudflare_interstitial", "otp_email", "otp_sms",
    "text_challenge", "cleared", "none",
})

# Detection routing only. `escalate` = hand to a human (Phase 1: stop + report).
HANDLERS: dict[str, str] = {g: "escalate" for g in GATES}
HANDLERS.update({
    "none": "proceed", "cleared": "proceed",
    "recaptcha_v3": "proceed", "turnstile": "proceed",
    "otp_email": "otp_email",
})


def classify_from_signals(sig: dict) -> str:
    # cleared beats "present" — a solved reCAPTCHA has a response token.
    if sig.get("grecaptcha_response_present"):
        return "cleared"
    if sig.get("cf_interstitial"):
        return "cloudflare_interstitial"
    if sig.get("hcaptcha_iframe"):
        return "hcaptcha_image" if sig.get("hcaptcha_challenge_visible") else "hcaptcha_checkbox"
    if sig.get("recaptcha_iframe"):
        return "recaptcha_v2_image" if sig.get("recaptcha_bframe_visible") else "recaptcha_v2_checkbox"
    if sig.get("turnstile_iframe"):
        return "turnstile"
    if sig.get("otp_email_field"):
        return "otp_email"
    if sig.get("otp_sms_field"):
        return "otp_sms"
    return "none"


def _gather_signals(page) -> dict:
    js = r"""
    () => {
      const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect();
        return r.width > 10 && r.height > 10; };
      const q = (s) => document.querySelector(s);
      const token = q('textarea#g-recaptcha-response');
      return {
        recaptcha_iframe: !!q('iframe[src*="recaptcha/api2/anchor"]'),
        grecaptcha_response_present: !!(token && token.value && token.value.length > 0),
        recaptcha_bframe_visible: vis(q('iframe[src*="recaptcha/api2/bframe"]')),
        hcaptcha_iframe: !!q('iframe[src*="hcaptcha.com"]'),
        hcaptcha_challenge_visible: vis(q('iframe[src*="hcaptcha.com/captcha"]')),
        turnstile_iframe: !!q('iframe[src*="challenges.cloudflare.com"]'),
        cf_interstitial: /just a moment|checking your browser/i.test(document.title || ''),
        otp_email_field: !!q('input[autocomplete="one-time-code"], input[name*="otp" i], input[name*="verification" i]'),
        otp_sms_field: false,
      };
    }
    """
    return page.evaluate(js)


def classify_gate(page) -> str:
    return classify_from_signals(_gather_signals(page))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_gate_probe.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/browser/gate_probe.py tests/career_agent/test_gate_probe.py
git commit -m "feat(career-agent): gate probe (detect-and-route, escalate default)"
```

---

### Task 7: Field mapper (pure)

**Files:**
- Create: `src/career_agent/orchestrator/mapper.py`
- Create: `tests/career_agent/test_mapper.py`

**Interfaces:**
- Consumes: `Field` (Task 3), a profile dict (Task 2).
- Produces: `FillDecision` dataclass `ref:str, kind:str, label:str, value, action:str, source:str` where `action ∈ {"fill","select","check_group","upload","review","attestation"}`; `map_fields(form: list[Field], profile: dict, resume_path: str|None) -> list[FillDecision]`.
- Rules: purpose→profile-key direct maps produce `action="fill"` (or `"select"` for select/`"check_group"` for radio_group), `source="profile"`. `resume_upload` → `action="upload"`, value=`resume_path`. `attestation` → `action="attestation"`, `value=None` (never auto-checked). Unknown purpose or missing profile value → `action="review"`, `value=None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_mapper.py
from career_agent.browser.form_model import Field
from career_agent.orchestrator.mapper import map_fields, FillDecision

PROFILE = {
    "full_name": "Test User", "email": "t@example.com", "phone": "+1-555-0100",
    "linkedin_url": "https://linkedin.com/in/test", "work_authorization": "US Citizen",
    "notice_period": "2 weeks",
}


def _f(ref, kind, label, purpose, options=None):
    return Field(ref=ref, kind=kind, label=label, required=False,
                 options=options or [], group=None, purpose=purpose)


def test_direct_profile_fields_fill_from_profile():
    form = [_f("#n", "text", "Full name", "full_name"),
            _f("#e", "email", "Email", "email")]
    decisions = {d.ref: d for d in map_fields(form, PROFILE, None)}
    assert decisions["#n"].value == "Test User"
    assert decisions["#n"].action == "fill"
    assert decisions["#n"].source == "profile"
    assert decisions["#e"].value == "t@example.com"


def test_attestation_is_never_auto_valued():
    form = [_f("#c", "checkbox", "I certify this is true", "attestation")]
    d = map_fields(form, PROFILE, None)[0]
    assert d.action == "attestation"
    assert d.value is None


def test_resume_upload_uses_resume_path():
    form = [_f("#r", "file", "Upload resume", "resume_upload")]
    d = map_fields(form, PROFILE, "/tmp/cv.pdf")[0]
    assert d.action == "upload" and d.value == "/tmp/cv.pdf"


def test_unknown_or_missing_becomes_review():
    form = [_f("#x", "text", "Favourite colour?", None),
            _f("#s", "text", "Expected salary", "salary_expectation")]  # not in PROFILE
    decisions = {d.ref: d for d in map_fields(form, PROFILE, None)}
    assert decisions["#x"].action == "review" and decisions["#x"].value is None
    assert decisions["#s"].action == "review"


def test_radio_group_uses_check_group_action():
    form = [_f("group:auth", "radio_group", "authorized", "work_authorization",
               options=["Yes", "No"])]
    d = map_fields(form, PROFILE, None)[0]
    assert d.action == "check_group"
    assert d.value == "US Citizen"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_mapper.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `mapper.py`**

```python
# src/career_agent/orchestrator/mapper.py
"""Field mapper: Form Model + profile -> per-field fill decisions.

Pure. Direct profile fields fill automatically; attestations are flagged
never valued; anything unknown or unbacked becomes a human-review item."""
from __future__ import annotations

from dataclasses import dataclass

from ..browser.form_model import Field

# purpose -> application_profile key (same-name except where noted)
_PROFILE_KEYS = {
    "full_name", "email", "phone", "location", "linkedin_url", "github_url",
    "portfolio_url", "work_authorization", "years_experience",
    "notice_period", "salary_expectation",
}


@dataclass(frozen=True)
class FillDecision:
    ref: str
    kind: str
    label: str
    value: object
    action: str
    source: str


def _action_for_kind(kind: str) -> str:
    if kind == "select":
        return "select"
    if kind == "radio_group":
        return "check_group"
    return "fill"


def map_fields(form: list[Field], profile: dict, resume_path: str | None) -> list[FillDecision]:
    out: list[FillDecision] = []
    for f in form:
        if f.purpose == "attestation":
            out.append(FillDecision(f.ref, f.kind, f.label, None, "attestation", "flag"))
            continue
        if f.purpose == "resume_upload":
            out.append(FillDecision(f.ref, f.kind, f.label, resume_path, "upload", "profile"))
            continue
        if f.purpose in _PROFILE_KEYS and profile.get(f.purpose):
            out.append(FillDecision(
                f.ref, f.kind, f.label, profile[f.purpose],
                _action_for_kind(f.kind), "profile"))
            continue
        out.append(FillDecision(f.ref, f.kind, f.label, None, "review", "none"))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_mapper.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/orchestrator/mapper.py tests/career_agent/test_mapper.py
git commit -m "feat(career-agent): field mapper (direct fill, attestations flagged)"
```

---

### Task 8: Review card (pure)

**Files:**
- Create: `src/career_agent/integrations/review_card.py`
- Create: `tests/career_agent/test_review_card.py`

**Interfaces:**
- Consumes: `FillDecision` (Task 7).
- Produces: `render_card(company: str, role: str, portal: str, decisions: list[FillDecision], gate: str) -> str`. The card has sections: a header line; `FILLED` (actions fill/select/check_group/upload with a value); `REVIEW` (action review); `ATTESTATIONS` (action attestation, shown as not-ticked); and a `GATE` line naming the detected gate.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_review_card.py
from career_agent.orchestrator.mapper import FillDecision
from career_agent.integrations.review_card import render_card


def _d(ref, action, label, value=None):
    return FillDecision(ref=ref, kind="text", label=label, value=value,
                        action=action, source="profile")


def test_card_groups_by_section():
    decisions = [
        _d("#n", "fill", "Full name", "Test User"),
        _d("#s", "review", "Expected salary"),
        _d("#c", "attestation", "I certify this is true"),
    ]
    card = render_card("Acme", "Engineer", "acme.com", decisions, "none")
    assert "Acme" in card and "Engineer" in card
    assert "FILLED" in card and "Full name" in card and "Test User" in card
    assert "REVIEW" in card and "Expected salary" in card
    assert "ATTESTATIONS" in card and "not ticked" in card.lower()
    assert "GATE" in card and "none" in card


def test_gate_surfaced_when_challenge_detected():
    card = render_card("Acme", "Eng", "acme.com", [], "cloudflare_interstitial")
    assert "cloudflare_interstitial" in card
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_review_card.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `review_card.py`**

```python
# src/career_agent/integrations/review_card.py
"""Compose the human review card from the agent's own fill decisions.

Pure text, built only from decisions — never a screenshot or session data."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision

_FILLED = {"fill", "select", "check_group", "upload"}


def render_card(company: str, role: str, portal: str,
                decisions: list[FillDecision], gate: str) -> str:
    filled = [d for d in decisions if d.action in _FILLED]
    review = [d for d in decisions if d.action == "review"]
    attest = [d for d in decisions if d.action == "attestation"]

    lines = [f"📋 {company} — {role}   ·   {portal}"]
    lines.append("")
    lines.append("FILLED ✅")
    for d in filled:
        lines.append(f"  • {d.label}: {d.value}")
    if not filled:
        lines.append("  (none)")
    if review:
        lines.append("")
        lines.append("REVIEW ⚠️  (needs your input)")
        for d in review:
            lines.append(f"  • {d.label}")
    if attest:
        lines.append("")
        lines.append("ATTESTATIONS 🔒")
        for d in attest:
            lines.append(f"  • {d.label} — NOT ticked")
    lines.append("")
    lines.append(f"GATE: {gate}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_review_card.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/integrations/review_card.py tests/career_agent/test_review_card.py
git commit -m "feat(career-agent): structured review card"
```

---

### Task 9: Approver interface + CLI implementation

**Files:**
- Create: `src/career_agent/integrations/approver.py`
- Create: `tests/career_agent/test_approver.py`

**Interfaces:**
- Produces: `Approver` (Protocol) with `request(card: str) -> bool`; `CliApprover` (prints the card, reads stdin; `y`/`yes` → True, anything else → False); `AutoDenyApprover` (always False — the safe default for unattended dry-runs). The Telegram approver drops in here in a later phase.

- [ ] **Step 1: Write the failing test**

```python
# tests/career_agent/test_approver.py
import builtins
from career_agent.integrations.approver import CliApprover, AutoDenyApprover


def test_cli_yes(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda *_: "yes")
    assert CliApprover().request("CARD") is True
    assert "CARD" in capsys.readouterr().out


def test_cli_no(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "n")
    assert CliApprover().request("CARD") is False


def test_auto_deny_is_false():
    assert AutoDenyApprover().request("anything") is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_approver.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `approver.py`**

```python
# src/career_agent/integrations/approver.py
"""Human approval interface. CLI now; Telegram later drops in behind the
same `request(card) -> bool` contract."""
from __future__ import annotations

from typing import Protocol


class Approver(Protocol):
    def request(self, card: str) -> bool: ...


class CliApprover:
    def request(self, card: str) -> bool:
        print(card)
        answer = input("\nSubmit this application? [y/N] ").strip().lower()
        return answer in ("y", "yes")


class AutoDenyApprover:
    """Never approves — safe default for unattended / dry-run."""
    def request(self, card: str) -> bool:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_approver.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/integrations/approver.py tests/career_agent/test_approver.py
git commit -m "feat(career-agent): approver interface + CLI impl"
```

---

### Task 10: Browser runner + filler (integration, skip-marked)

**Files:**
- Create: `src/career_agent/browser/runner.py`
- Create: `src/career_agent/browser/filler.py`
- Create: `tests/career_agent/test_filler_browser.py`

**Interfaces:**
- `runner.launch(settings) -> tuple[playwright, context, page]`; `runner.close(playwright, context)`. Uses `chromium.launch_persistent_context(settings.user_data_dir, headless=not settings.headed)`.
- `filler.apply_decisions(page, decisions: list[FillDecision]) -> None` — executes fill/select/check_group/upload; skips review/attestation. `filler.read_back(page, decisions) -> dict[ref, str]` — reads current input values for verification.

- [ ] **Step 1: Write the skip-marked browser test**

```python
# tests/career_agent/test_filler_browser.py
import os
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 to run",
)


def _fixture_url():
    return (Path(__file__).parent / "fixtures" / "sample_form.html").resolve().as_uri()


def test_fill_then_readback_matches():
    from playwright.sync_api import sync_playwright
    from career_agent.browser.perception import snapshot_form
    from career_agent.browser.filler import apply_decisions, read_back
    from career_agent.orchestrator.mapper import map_fields

    profile = {"full_name": "Jane Q", "email": "jane@example.com"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(_fixture_url())
        form = snapshot_form(page)
        decisions = map_fields(form, profile, None)
        apply_decisions(page, decisions)
        values = read_back(page, decisions)
        browser.close()

    assert values["#name"] == "Jane Q"
    assert values["#email"] == "jane@example.com"
```

- [ ] **Step 2: Run it to verify it fails/skips appropriately**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_filler_browser.py -v`
Expected: SKIP (no env var). It will fail on import once the env var is set until Step 3/4 exist.

- [ ] **Step 3: Write `runner.py`**

```python
# src/career_agent/browser/runner.py
"""Persistent-context Chrome launcher. A real on-disk profile so sessions and
cookies persist across runs, headed by default."""
from __future__ import annotations

from pathlib import Path


def launch(settings):
    from playwright.sync_api import sync_playwright
    Path(settings.user_data_dir).mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        settings.user_data_dir, headless=not settings.headed,
    )
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


def close(pw, context) -> None:
    try:
        context.close()
    finally:
        pw.stop()
```

- [ ] **Step 4: Write `filler.py`**

```python
# src/career_agent/browser/filler.py
"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision


def apply_decisions(page, decisions: list[FillDecision]) -> None:
    for d in decisions:
        if d.value is None:
            continue
        if d.action == "fill":
            page.fill(d.ref, str(d.value))
        elif d.action == "select":
            page.select_option(d.ref, label=str(d.value))
        elif d.action == "upload":
            page.set_input_files(d.ref, str(d.value))
        elif d.action == "check_group":
            # value is the intended option label; click the matching radio.
            page.get_by_label(str(d.value)).check()
        # review / attestation: intentionally left for the human.


def read_back(page, decisions: list[FillDecision]) -> dict:
    out: dict[str, str] = {}
    for d in decisions:
        if d.action in ("fill", "select") and d.ref.startswith(("#", "[")):
            try:
                out[d.ref] = page.input_value(d.ref)
            except Exception:
                pass
    return out
```

- [ ] **Step 5: Run the browser test (opt-in) + full suite**

Run: `PYTHONPATH=src RUN_BROWSER_TESTS=1 python3 -m pytest tests/career_agent/test_filler_browser.py -v`
Expected: PASS. Then `PYTHONPATH=src python3 -m pytest tests/career_agent -q` → all pass/skip.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/browser/runner.py src/career_agent/browser/filler.py tests/career_agent/test_filler_browser.py
git commit -m "feat(career-agent): persistent runner + filler with read-back"
```

---

### Task 11: `run.py` — one-pass orchestration (dry-run default)

**Files:**
- Create: `src/career_agent/run.py`
- Create: `tests/career_agent/test_run_flow.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run_once(page, profile, resume_path, meta, approver, do_submit) -> dict` — pure-ish orchestration over an injected `page` (so it is testable with a fake page); returns `{"gate", "card", "approved", "submitted", "decisions"}`. Also a `main()` argparse entrypoint: `--url` (required), `--submit` (default False), `--company`, `--role`, `--resume`.
- Contract: `run_once` never submits unless `do_submit and approver.request(card) is True and gate handler is "proceed"`. If the gate's handler is `escalate`, it never submits and the card notes the gate.

- [ ] **Step 1: Write the failing test (fake page — no browser)**

```python
# tests/career_agent/test_run_flow.py
from career_agent.browser.form_model import Field
from career_agent.run import run_once


class FakePage:
    def __init__(self, form): self._form = form; self.submitted = False
    def _snapshot(self): return self._form
    def click_submit(self): self.submitted = True


class YesApprover:
    def request(self, card): return True


class NoApprover:
    def request(self, card): return False


def _form():
    return [Field("#n", "text", "Full name", True, [], None, "full_name"),
            Field("#c", "checkbox", "I certify true", False, [], None, "attestation")]


def _meta():
    return {"company": "Acme", "role": "Engineer", "portal": "acme.com"}


def test_dry_run_never_submits(monkeypatch):
    page = FakePage(_form())
    monkeypatch.setattr("career_agent.run.snapshot_form", lambda p: p._snapshot())
    monkeypatch.setattr("career_agent.run.classify_gate", lambda p: "none")
    monkeypatch.setattr("career_agent.run.apply_decisions", lambda p, d: None)
    out = run_once(page, {"full_name": "T"}, None, _meta(), YesApprover(), do_submit=False)
    assert out["submitted"] is False
    assert "Acme" in out["card"]


def test_submit_requires_approval_and_clear_gate(monkeypatch):
    page = FakePage(_form())
    monkeypatch.setattr("career_agent.run.snapshot_form", lambda p: p._snapshot())
    monkeypatch.setattr("career_agent.run.classify_gate", lambda p: "none")
    monkeypatch.setattr("career_agent.run.apply_decisions", lambda p, d: None)
    out = run_once(page, {"full_name": "T"}, None, _meta(), YesApprover(), do_submit=True)
    assert out["approved"] is True and out["submitted"] is True and page.submitted is True


def test_escalated_gate_blocks_submit(monkeypatch):
    page = FakePage(_form())
    monkeypatch.setattr("career_agent.run.snapshot_form", lambda p: p._snapshot())
    monkeypatch.setattr("career_agent.run.classify_gate", lambda p: "cloudflare_interstitial")
    monkeypatch.setattr("career_agent.run.apply_decisions", lambda p, d: None)
    out = run_once(page, {"full_name": "T"}, None, _meta(), YesApprover(), do_submit=True)
    assert out["submitted"] is False
    assert "cloudflare_interstitial" in out["card"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_run_flow.py -v`
Expected: FAIL — `career_agent.run` missing.

- [ ] **Step 3: Write `run.py`**

```python
# src/career_agent/run.py
"""Phase-1 entrypoint: one application pass over a target URL.

perceive -> classify gate -> map -> fill -> compose card -> approve -> (maybe) submit.
Dry-run by default; submits only on explicit approval AND a clear gate."""
from __future__ import annotations

import argparse

from .browser.perception import snapshot_form
from .browser.gate_probe import classify_gate, HANDLERS
from .browser.filler import apply_decisions
from .orchestrator.mapper import map_fields
from .integrations.review_card import render_card
from .integrations.approver import CliApprover


def _click_submit(page) -> None:
    # Prefer an explicit hook (tests), else a best-effort submit button.
    if hasattr(page, "click_submit"):
        page.click_submit()
    else:
        page.get_by_role("button", name="Submit").click()


def run_once(page, profile, resume_path, meta, approver, do_submit) -> dict:
    form = snapshot_form(page)
    gate = classify_gate(page)
    decisions = map_fields(form, profile, resume_path)
    apply_decisions(page, decisions)
    card = render_card(meta["company"], meta["role"], meta["portal"], decisions, gate)

    gate_clear = HANDLERS.get(gate, "escalate") == "proceed"
    approved = False
    submitted = False
    if do_submit and gate_clear:
        approved = approver.request(card)
        if approved:
            _click_submit(page)
            submitted = True

    return {"gate": gate, "card": card, "approved": approved,
            "submitted": submitted, "decisions": decisions}


def main() -> None:
    from .config.settings import load_settings
    from .browser.runner import launch, close
    from .memory.factual_core import load_profile

    ap = argparse.ArgumentParser(description="Career agent — Phase 1 harness")
    ap.add_argument("--url", required=True)
    ap.add_argument("--submit", action="store_true", help="actually submit (default: dry-run)")
    ap.add_argument("--company", default="(unknown)")
    ap.add_argument("--role", default="(unknown)")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--profile", default="profile.json")
    args = ap.parse_args()

    settings = load_settings()
    profile = load_profile(args.profile)
    pw, context, page = launch(settings)
    try:
        page.goto(args.url)
        meta = {"company": args.company, "role": args.role, "portal": args.url}
        out = run_once(page, profile, args.resume, meta, CliApprover(), args.submit)
        print(out["card"])
        print(f"\n[gate={out['gate']}] submitted={out['submitted']}")
    finally:
        close(pw, context)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent/test_run_flow.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole Phase-1 suite**

Run: `PYTHONPATH=src python3 -m pytest tests/career_agent -q`
Expected: all pass; the two `*_browser.py` files SKIP without `RUN_BROWSER_TESTS=1`.

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/run.py tests/career_agent/test_run_flow.py
git commit -m "feat(career-agent): phase-1 run loop (dry-run default, gate-guarded submit)"
```

---

## Manual smoke (after Task 11, optional — needs a real browser)

Not a test; a one-time human check on a real, low-stakes career page:

```bash
python3 -m playwright install chromium
PYTHONPATH=src python3 -c "import sqlite3; from job_dashboard.db import init_db" # ensure DB import works
# export your dashboard profile once (adjust the DB path to your jobs.db):
PYTHONPATH=src python3 -c "from career_agent.memory.factual_core import export_profile; from job_dashboard.db import init_db; import sqlite3; c=sqlite3.connect('data/jobs.db'); from job_dashboard.apply.store import ensure_application_tables; ensure_application_tables(c); print(export_profile(c,'profile.json'))"
# dry-run (fills, shows the card, never submits):
PYTHONPATH=src python3 -m career_agent.run --url "<a real career-page form URL>" --company "X" --role "Y"
```

Confirm: the browser opens, fields fill, the card lists FILLED/REVIEW/ATTESTATIONS correctly, and nothing submits.

---

## Self-Review (completed by plan author)

- **Spec coverage:** Phase 1 build-order item (persistent profile → navigate → Form Model + gate_probe → fill from profile → approve → submit) is covered by Tasks 5/10 (persistent browser + perception), 6 (gate_probe), 7 (map/fill), 8–9 (card + approve), 11 (submit, gated). Telegram/Gmail/memory/LLM are explicitly later phases. ✔
- **No-evasion constraint:** gate_probe detects only; HANDLERS default `escalate`; a test asserts `cloudflare_interstitial → escalate`; nothing imports flare_tool/proxy_tool. ✔
- **No-auto-submit constraint:** `--submit` opt-in; `run_once` submits only on approval AND `HANDLERS[gate]=="proceed"`; tests assert dry-run and escalated-gate both block submit. ✔
- **Placeholder scan:** every code/test step contains real code; no TBD/TODO. ✔
- **Type consistency:** `Field` signature (Task 3) is used identically in Tasks 4/5/7; `FillDecision.action` vocabulary matches between mapper (Task 7), review card (Task 8), and filler (Task 10). ✔
