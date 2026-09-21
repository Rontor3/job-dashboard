"""LangGraph-based career agent graph.

Nodes: classify → cred_provide → reach → perceive → fill → human_gate → advance
Page lives outside state (Playwright isn't serialisable) — pass via
config["configurable"]["page"].  Human gates use interrupt(); the outer loop
in apply.py handles the Telegram collect → Command(resume=answers) cycle.
SqliteSaver checkpoints every node transition so the logical state survives.
"""
from __future__ import annotations

import dataclasses
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt


# ── State ─────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    url: str
    job_id: int | None
    jd_text: str | None
    kind: str               # classify_entry result
    ats_vendor: str | None  # vendor label from ats-graph (e.g. "Lever", "Workday")
    steps: int
    max_steps: int
    do_submit: bool
    autonomous: bool
    cred_provided: bool     # True after cred_provide ran (prevents re-triggering)
    # current screen snapshot (serialised Field dicts); reset each perceive pass
    form: list[dict]
    form_sig: str | None    # for stuck-detection in advance
    # fields needing human input this cycle (serialised Field dicts)
    pending_human: list[dict]
    # accumulated FillDecision dicts across all screens
    decisions: list[dict]
    submitted: bool
    stopped_reason: str | None


def initial_state(url: str, *, job_id=None, jd_text=None,
                  do_submit=False, autonomous=False, max_steps=15) -> AgentState:
    return {
        "url": url, "job_id": job_id, "jd_text": jd_text,
        "kind": "", "ats_vendor": None, "steps": 0, "max_steps": max_steps,
        "do_submit": do_submit, "autonomous": autonomous,
        "cred_provided": False,
        "form": [], "form_sig": None,
        "pending_human": [], "decisions": [],
        "submitted": False, "stopped_reason": None,
    }


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _f2d(f) -> dict:
    return dataclasses.asdict(f)


def _d2f(d: dict):
    from ..browser.form_model import Field
    return Field(**d)


def _dec2d(d) -> dict:
    return dataclasses.asdict(d)


def _d2dec(d: dict):
    from ..orchestrator.mapper import FillDecision
    return FillDecision(**d)


# ── Memory helpers ────────────────────────────────────────────────────────────

def _semantic_split(fields, mem_router):
    """Separate fields the semantic vault can answer autonomously from the rest.

    Returns (auto_decisions, remaining_fields).
    Autonomous = confidence >= 1.0 (3 human approvals).  Others fall through.
    """
    if not mem_router:
        return [], fields
    from ..orchestrator.mapper import FillDecision
    auto, rest = [], []
    for f in fields:
        if f.kind not in ("text", "textarea"):
            rest.append(f)
            continue
        hit = mem_router.dispatch("SEMANTIC_MATCH", {"question": f.label or ""})
        if hit and hit.get("autonomous"):
            auto.append(FillDecision(f.ref, f.kind, f.label,
                                     hit["answer"], "semantic", "behavioral"))
        else:
            rest.append(f)
    return auto, rest


# ── Nodes ─────────────────────────────────────────────────────────────────────

def classify_node(state: AgentState, config) -> dict:
    c = config["configurable"]
    page = c["page"]
    if c.get("prep_fn"):
        c["prep_fn"](page)
    from ..browser.page_prep import classify_entry
    from ..browser.ats_lookup import lookup as _ats_lookup
    kind = classify_entry(page)
    jd_text = state.get("jd_text")
    if not jd_text and kind != "closed":
        try:
            jd_text = (page.inner_text("body") or "")[:3000].strip() or None
        except Exception:
            jd_text = None
    # Wire jd_text into TelegramCollector and judgment context if present
    collector = c.get("collector")
    if jd_text and collector and hasattr(collector, "jd_text"):
        collector.jd_text = jd_text
    jctx = c.get("judgment_ctx")
    if jd_text and jctx is not None and not jctx.resume_text:
        jctx.resume_text = jd_text[:2000]  # give qwen JD context for essay answers
    # ATS knowledge graph lookup — vendor notes flow into judgment tier
    vendor = _ats_lookup(page.url)
    ats_vendor = vendor["label"] if vendor else None
    if ats_vendor:
        notes = vendor.get("notes") or ""
        hints = vendor.get("fix_hints") or []
        hint_str = " | fixes: " + "; ".join(hints[:2]) if hints else ""
        print(f"[ats] {ats_vendor}: {notes[:80]}{hint_str}", flush=True)
    return {"kind": kind, "jd_text": jd_text, "url": page.url, "ats_vendor": ats_vendor}


def cred_provide_node(state: AgentState, config) -> dict:
    c = config["configurable"]
    page = c["page"]
    from ..browser.credential_provider import provide as _provide
    from ..browser.page_prep import classify_entry, clear_auth_wall, is_application_form, enter_application, prepare
    original_url = state["url"]

    _prof = c.get("profile")
    _email = _prof.contact.get("email", "") if _prof and hasattr(_prof, "contact") else ""

    def _prov(pg, gate, site):
        return _provide(pg, gate, site, original_url=original_url, email=_email)

    clear_auth_wall(page, credential_provider=_prov)
    kind = classify_entry(page)
    # After registration Darwinbox lands back on the JD page — re-enter apply
    if kind in ("none", "form") and not is_application_form(page):
        enter_application(page)
        page = page.context.pages[-1]
        if c.get("prep_fn"):
            c["prep_fn"](page)
        kind = classify_entry(page)
    if kind == "password" and is_application_form(page):
        kind = "form"
    return {"kind": kind, "url": page.url, "cred_provided": True}


def tailor_cv_node(state: AgentState, config) -> dict:
    from .tailor_cv import tailor_cv_node as _tailor
    return _tailor(state, config)


def reach_node(state: AgentState, config) -> dict:
    c = config["configurable"]
    page = c["page"]
    from ..browser.page_prep import enter_application, classify_entry
    enter_application(page)
    page = page.context.pages[-1]
    if c.get("prep_fn"):
        c["prep_fn"](page)
    return {"kind": classify_entry(page), "url": page.url}


def perceive_node(state: AgentState, config) -> dict:
    """Gate check + overlay cleanup. Blocks if gate unresolvable."""
    if state.get("stopped_reason"):
        return {}
    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]
    if c.get("prep_fn"):
        c["prep_fn"](page)

    from ..browser.page_prep import dismiss_consent
    from ..browser.gate_probe import HANDLERS
    dismiss_consent(page)          # clear async cookie banners before gate check
    page.wait_for_timeout(2000)
    gate = deps.gate(page)
    _INTERACTIVE = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                    "hcaptcha_checkbox", "hcaptcha_image"}
    _SUBMIT_GATED = {"hcaptcha_checkbox"}   # invisible widget; form still accessible
    _EARLY_BLOCK = {"cloudflare_interstitial", "otp_sms", "text_challenge"}
    from ..browser.gate_probe import HANDLERS
    if gate in _INTERACTIVE:
        # Poll up to 5s for auto-verify (trusted-browser self-solve).
        for _ in range(5):
            page.wait_for_timeout(1000)
            gate = deps.gate(page)
            if HANDLERS.get(gate, "escalate") == "proceed":
                break
    if gate in _EARLY_BLOCK:
        return {"stopped_reason": f"gate:{gate}"}
    if gate == "otp_email":
        return {"stopped_reason": "gate:otp_email"}
    # Blocking visual challenge (image captcha) — remote-solve via Telegram.
    if gate in _INTERACTIVE and gate not in _SUBMIT_GATED:
        if HANDLERS.get(gate, "escalate") != "proceed":
            human = c["human"]
            on_link = c.get("on_link") or (lambda u: None)
            print(f"[gate] {gate} — sending live-view link via Telegram...", flush=True)
            if not human.remote_solve(page, gate, on_link):
                return {"stopped_reason": f"gate:{gate}"}
            if HANDLERS.get(deps.gate(page), "escalate") != "proceed":
                return {"stopped_reason": f"gate:{gate}"}

    # Navigation rule: scroll to top + screenshot before reading DOM
    from .step_engine import _page_survey
    _page_survey(page, f"perceive{state.get('steps', 0)}")

    # Snapshot form — stored in state so advance_node can check controls
    form = deps.snapshot(page)
    from ..orchestrator.advance import screen_signature
    sig = screen_signature(deps.url(page), form)
    return {"form": [_f2d(f) for f in form], "form_sig": sig, "pending_human": []}


def fill_node(state: AgentState, config) -> dict:
    """Recall → rules → judge; apply confident answers; flag the rest."""
    if state.get("stopped_reason"):
        return {}
    if state["steps"] >= state["max_steps"]:
        return {"stopped_reason": "max_steps"}
    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]
    profile = c["profile"]
    resume_pdf = c.get("resume_pdf")
    judge_fn = c.get("judge_fn")
    learn = c.get("learn")

    form = [_d2f(d) for d in state["form"]]
    fillable = [f for f in form if f.kind != "button"]

    recalled, remaining = [], fillable
    if learn:
        recalled, remaining = learn.recall(fillable)

    # Tri-Partite Memory: autonomous semantic answers bypass the human gate.
    mem_router = c.get("memory_router")
    auto_semantic, remaining = _semantic_split(remaining, mem_router)

    from ..orchestrator.screen_review import map_screen
    decisions, needs = map_screen(remaining, profile, resume_pdf)
    decisions += recalled + auto_semantic

    if needs and judge_fn:
        answered, needs, _ = judge_fn(needs)
        decisions += answered

    deps.fill(page, decisions)
    print(f"[fill] step {state['steps']+1}: {len(decisions)} filled, "
          f"{len(needs)} escalated", flush=True)

    return {
        "steps": state["steps"] + 1,
        "decisions": (state.get("decisions") or []) + [_dec2d(d) for d in decisions],
        "pending_human": [_f2d(f) for f in needs],
    }


def human_gate_node(state: AgentState, config) -> dict:
    """Interrupt for human input; apply answers to page on resume."""
    fields = [_d2f(d) for d in state["pending_human"]]
    # interrupt() suspends the graph; outer loop collects answers and resumes
    # via graph.invoke(Command(resume=answers), config=same_config)
    answers: dict = interrupt({"fields": [_f2d(f) for f in fields]})

    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]
    learn = c.get("learn")

    from ..orchestrator.screen_review import apply_answers
    new_decisions = apply_answers(fields, answers)
    deps.fill(page, new_decisions)

    mem_router = c.get("memory_router")
    # Events from TelegramCollector: {ref: "approve"|"edit"}; empty for CLI
    human = c.get("human")
    events: dict = human.get_events() if (human and hasattr(human, "get_events")) else {}
    for f in fields:
        ans = answers.get(f.ref)
        if ans is None:
            continue
        ans_str = str(ans).strip()
        if not ans_str:
            continue
        event = events.get(f.ref, "approve")
        if mem_router:
            # Dual-writes to ChromaDB (semantic vault) + FTS5 (learned_answers)
            mem_router.dispatch("RECORD_FEEDBACK", {
                "question": f.label or f.ref,
                "answer": ans_str,
                "event": event,
                "purpose": f.purpose,
            })
        elif learn:
            learn.record(f, ans)

    return {
        "pending_human": [],
        "decisions": (state.get("decisions") or []) + [_dec2d(d) for d in new_decisions],
    }


def advance_node(state: AgentState, config) -> dict:
    """Click Next or Submit; detect stuck; route back for more screens."""
    if state.get("stopped_reason"):
        return {}
    c = config["configurable"]
    page = c["page"]
    deps = c["deps"]
    human = c["human"]
    learn = c.get("learn")

    form = [_d2f(d) for d in state["form"]]
    from ..orchestrator.advance import (
        has_control, pick_advance_label, screen_signature, changed,
        ADVANCE_NAMES, SUBMIT_NAMES,
    )
    has_advance = has_control(form, ADVANCE_NAMES)
    has_submit = has_control(form, SUBMIT_NAMES)

    if not has_advance and has_submit:
        if not state["do_submit"]:
            return {"stopped_reason": "reached_submit_dry_run"}
        # Pre-submit gate re-check
        from ..browser.gate_probe import HANDLERS
        _INTERACTIVE = {"recaptcha_v2_checkbox", "recaptcha_v2_image",
                        "hcaptcha_checkbox", "hcaptcha_image"}
        pre_gate = deps.gate(page)
        if HANDLERS.get(pre_gate, "escalate") != "proceed":
            on_link = c.get("on_link") or (lambda u: None)
            if pre_gate in _INTERACTIVE and human.remote_solve(page, pre_gate, on_link):
                if HANDLERS.get(deps.gate(page), "escalate") != "proceed":
                    return {"stopped_reason": f"gate:{pre_gate}"}
            else:
                return {"stopped_reason": f"gate:{pre_gate}"}
        if not (state["autonomous"] or human.approve("Ready to submit")):
            return {"stopped_reason": "submit_declined"}
        if learn and hasattr(deps, "read_back"):
            all_dec = [_d2dec(d) for d in (state.get("decisions") or [])]
            try:
                learn.record_corrections(form, all_dec, deps.read_back(page, all_dec))
            except Exception:
                pass
        deps.click(page, pick_advance_label(form, is_last=True))
        return {"submitted": True, "stopped_reason": "submitted"}

    if not has_advance:
        return {"stopped_reason": "no_advance_control"}

    deps.click(page, pick_advance_label(form, is_last=False))

    # Mid-walk credential wall (e.g. iCIMS "Create a login" on screen 2).
    from ..browser.page_prep import classify_entry, clear_auth_wall
    _kind = classify_entry(page)
    if _kind in ("password", "email_auth"):
        _job_url = state.get("url") or page.url
        _adv_prof = c.get("profile")
        _adv_email = _adv_prof.contact.get("email", "") if _adv_prof and hasattr(_adv_prof, "contact") else ""
        from ..browser.credential_provider import provide as _provide
        _prov = lambda pg, gate, site: _provide(pg, gate, site, original_url=_job_url, email=_adv_email)
        print(f"[cred] {_kind} wall mid-walk — credential provider...", flush=True)
        clear_auth_wall(page, credential_provider=_prov)
        if classify_entry(page) in ("password", "email_auth"):
            return {"stopped_reason": "auth_wall"}

    new_form = deps.snapshot(page)
    after = screen_signature(deps.url(page), new_form)
    if state.get("form_sig") and not changed(state["form_sig"], after):
        return {"stopped_reason": "stuck"}
    return {"form": [_f2d(f) for f in new_form], "form_sig": after, "url": page.url}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_reach(state: AgentState) -> str:
    # Route to cred_provide only on first password wall (guard prevents loop)
    if state["kind"] == "password" and not state.get("cred_provided"):
        return "cred_provide"
    return "tailor_cv"


def _route_classify(state: AgentState) -> str:
    k = state["kind"]
    if k == "closed":
        return END
    if k == "password":
        return "cred_provide"
    return "reach"


def _route_perceive(state: AgentState) -> str:
    return END if state.get("stopped_reason") else "fill"


def _route_fill(state: AgentState) -> str:
    if state.get("stopped_reason"):
        return END
    return "human_gate" if state.get("pending_human") else "advance"


def _route_advance(state: AgentState) -> str:
    if state.get("stopped_reason") or state.get("submitted"):
        return END
    return "perceive"


# ── Build ─────────────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    """Return a compiled graph, optionally with a SqliteSaver checkpointer."""
    g = StateGraph(AgentState)
    g.add_node("classify", classify_node)
    g.add_node("cred_provide", cred_provide_node)
    g.add_node("reach", reach_node)
    g.add_node("tailor_cv", tailor_cv_node)
    g.add_node("perceive", perceive_node)
    g.add_node("fill", fill_node)
    g.add_node("human_gate", human_gate_node)
    g.add_node("advance", advance_node)

    g.set_entry_point("classify")
    g.add_conditional_edges("classify", _route_classify,
                            {"cred_provide": "cred_provide", "reach": "reach", END: END})
    g.add_edge("cred_provide", "reach")
    g.add_conditional_edges("reach", _route_reach, {"cred_provide": "cred_provide", "tailor_cv": "tailor_cv"})
    g.add_edge("tailor_cv", "perceive")
    g.add_conditional_edges("perceive", _route_perceive, {"fill": "fill", END: END})
    g.add_conditional_edges("fill", _route_fill,
                            {"human_gate": "human_gate", "advance": "advance", END: END})
    g.add_edge("human_gate", "advance")
    g.add_conditional_edges("advance", _route_advance, {"perceive": "perceive", END: END})

    return g.compile(checkpointer=checkpointer)
