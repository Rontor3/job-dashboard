"""The decline-class gate — a deterministic, LLM-free policy for the asks the
agent must never put to a human: newsletter / job-alert / marketing-contact
opt-ins and their Yes/No variants ("Get email updates for the latest senior
data scientist jobs", "Follow <company> to stay up to date", "I agree to
receive updates about new job opportunities").

Applying is not consent to be marketed to. Where the old pipeline only had two
late safety nets that could not stop the *ask* itself — screen_review's
attestation-branch _MARKETING flag and boards/run._untick at the final click —
this gate is the single early decision point in `answer_fields`, before the
screen-review tier and the judgment tier ever see the field.

classify(field) -> Verdict(action, reason), with:
  "decline"  an optional acquisition ask: the gate answers it negatively
             itself (a FillDecision, source "decline_class",
             basis "marketing opt-in auto-declined by policy").
             Checkboxes untick (value False); radio groups / selects / combobox
             pick the live option that means No — and only when such an option
             exists. A widget that can express no "No" (a free-text combobox,
             ["Opt in","Opt out"]) is held undecided instead: no fabricated
             value.
  "skip"     a REQUIRED acquisition ask: no decision at all, and never a
             question for judge() (qbank_memory's documented invariant — a
             required box cannot be declined, never untick it — is policy,
             not just commentary). The field is held out of the asks list and
             the human decides it at the escalation boundary; application_qa
             carries the hold-back (source decline_class, basis naming the
             gate) for auditability.
  "ask"      anything else — pass through to the existing ladder untouched.

Counter-examples the patterns deliberately DO NOT catch (single place to audit
the policy, and to extend it — keep it patterns-as-data):
  * "Please notify me of the status of my application via email" (Gulf/Workday)
    — application-status consent, not marketing (C-1 red-team: recruiters
    treat it as consent-to-contact; a silent decline could drop the candidate).
  * "Any updates on your availability?" / "Any offer in hand?" — application
    questions that merely share words with the old _MARKETING regex.
  * "Please choose your notification language" — a configuration control.
  * profiling opt-ins ("Check here if you're open to relocating — we'll update
    your profile so companies can contact you"): the profile may legitimately
    want that ticked, so the gate leaves it to the ladder.
A mixed ask (Koch's "receive SMS … regarding your application and other career
opportunities") is treated as process consent: never auto-declined.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .mapper import FillDecision, _action_for_kind

DECLINE = "decline"      # the gate answers No itself (an affirmative decline decision)
ASK = "ask"              # pass through: not the gate's business
SKIP = "skip"            # gate-consumed, no decision, never asked by a tier: held for the human

SOURCE = "decline_class"
DECLINE_BASIS = "marketing opt-in auto-declined by policy"

# Only choice widgets can be a pre-ticked opt-in. Text/essay/file are never a
# decline: a human answer there is a fact, not a marketing preference.
_CHOICE = {"checkbox", "radio", "radio_group", "select", "combobox"}

# NOT marketing — application-process consent and configuration. Checked
# BEFORE the acquisition patterns: a mixed label ("regarding your application
# and other career opportunities") must reach the human, not a regex.
_PROCESS = re.compile(
    r"status.{0,60}application|application.{0,60}status"
    r"|status of (my|your|the|this)\b"
    r"|\bnotif\w*\b.{0,60}(application|status|result|outcome|interview|shortlist|eligib)"
    r"|\b(application|eligib\w*)\b.{0,40}\bnotif\w*"
    r"|\b(regarding|about|on|of|for) (your|my|the|this)\b.{0,30}\bapplication\b"
    r"|\beligib\w*|\bto be (considered|contactable)\b|\bconsidered for\b"
    r"|\blooking (for|to)\b"
    r"|\binterview\b|\bshortlist\w*|\bscreening\b|\bassess\w*|\breminder\b|remind\w*"
    r"|\bavailab\w*\b.{0,40}\bupdate\w*|\bupdate\w*\b.{0,40}\bavailab\w*",
    re.I)

# Profiling opt-ins: what the profile says is the candidate's own standing
# answer ("we'll update your profile so companies can contact you") — the
# profile resolver may legitimately tick it, so the gate leaves it alone.
_PROFILE = re.compile(r"(update|edit|change|save)\b.{0,30}\b(your |the )?profile\b", re.I)

# What IS a marketing-acquisition ask. Ordered list of (name, pattern); every
# pattern is scoped so it names the acquisition explicitly — no bare "notif",
# no bare "updates? (about|on)" (the C-1 over-reach in the old _MARKETING).
_ACQUIRE: list[tuple[str, re.Pattern]] = [
    ("newsletter",
     re.compile(r"news ?letters?", re.I)),
    ("job-alerts",
     re.compile(r"jobs? (alerts?|matches?)"
                r"|(alerts?|notif\w*)\b.{0,60}\b(jobs?|roles?|positions?|openings?|vacanc)"
                r"|(new|latest|similar) (jobs?|roles?|openings?)", re.I)),
    ("get-email-updates",
     re.compile(r"email updates for the latest"
                r"|(get|send)\s+(me |us )?(email |emailed? )?(new |latest |similar |more )?(jobs?|roles?|openings?)\b.{0,20}\b(latest|new|similar|like|this|alerts?|updates?|offers?)\b"
                r"|^(get|receive)\s+(emails?|jobs?|weekly|daily)\s+(updates?|alerts?)\b"
                r"|(email|mail)\s+(updates?|alerts?).{0,40}\bjobs?"
                r"|\b(email|mail) (me|us) .{0,25}\b(new |latest |similar |job offers?|jobs?)"
                r"|receive .{0,20}\bjobs? (recommendations?|by email)"
                r"|send (me|us) .{0,30}\b(job offers?|promotions?|updates?|alerts?)", re.I)),
    ("updates-for-jobs",
     re.compile(r"updates? (about|on|for|regarding)\b.{0,40}\b(new |other |latest |similar )?(jobs?|roles?|openings?|opportun|vacanc)", re.I)),
    ("job-opportunities",
     re.compile(r"(job|career|employment) opportunit", re.I)),
    ("marketing-comms",
     re.compile(r"\bmarketing\b|\bpromo(tional|tion|s)\b", re.I)),
    ("comms-consent",
     re.compile(r"(consent|agree|want|choose|opt(ed)? ?in( to)?|like|wish) to receive\b"
                r"|receive (emails?|e-?mails?|messages?|updates?|alerts?|offers?)\b"
                r"|receive \w*.{0,25}\b(sms|text|whats ?app|e-?mail|mail)s?\b", re.I)),
    ("talent-community",
     re.compile(r"talent (community|network|pool|pipeline)"
                r"|(connect|join|become part of)\b.{0,25}(us|our (community|network|talent))", re.I)),
    ("follow-company",
     re.compile(r"follow\w*\b.{0,40}\b(us|company|companie|business|employer|brand)\b"
                r"|follow\w*\b.{0,60}\b(linkedin|twitter|x\.com|instagram|facebook|social)\b"
                r"|(stay|keep|be) (up to date|informed|updated|connected|posted|in the loop)", re.I)),
    ("sms-channels",
     re.compile(r"\b(sms|text|whats ?app)\b.{0,30}\b(alert|update|notification|offer)s?\b"
                r"|(alert|update|notification)s? (by|via|on|through) (sms|text|whats ?app)", re.I)),
]


@dataclass(frozen=True)
class Verdict:
    action: str                 # "decline" | "ask" | "skip"
    reason: str = ""
    pattern: str = ""           # which _ACQUIRE name matched ("" when none / a guard hit)


def _acquire(label: str) -> tuple[str, re.Pattern] | None:
    for name, pat in _ACQUIRE:
        if pat.search(label):
            return name, pat
    return None


def classify(f, job: dict | None = None) -> Verdict:
    """The gate's verdict for one field form. `job` is accepted for the policy's
    signature (the 30604 phrasing carries the role inside the label; the job
    context is reserved for site-specific packs that land here later)."""
    kind = getattr(f, "kind", "") or ""
    label = f"{getattr(f, 'label', '') or ''} {(getattr(f, 'description', '') or '')}".strip()
    if kind not in _CHOICE:
        return Verdict(ASK, "not a choice field — a human answer here is a fact, not a marketing opt-in")
    why = _PROCESS.search(label) or _PROFILE.search(label)
    if why:
        return Verdict(ASK, "application-process / profile consent, not marketing "
                            f"(matched {why.group(0)[:40]!r})")
    hit = _acquire(label)
    if hit is None:
        return Verdict(ASK, "no acquisition pattern")
    name, _pat = hit
    required = bool(getattr(f, "required", False))
    if required:
        return Verdict(SKIP, f"required {name} ask held back (policy: required opt-ins are never auto-declined) "
                             "— left for you at the escalation boundary", name)
    return Verdict(DECLINE, f"optional {name} ask declined by policy", name)


def decline_value(f) -> tuple[str, object] | None:
    """(action, value) of the gate's negative answer for this widget kind, or
    None when the widget can express no "No": a checkbox unticks; a radio
    group / select / combobox picks the live option that means No (via the
    same coercion the rest of the pipeline uses) — an empty-options combobox
    or ["Opt in","Opt out"] is left undecided rather than fabricating a value."""
    opts = [o for o in (getattr(f, "options", None) or [])
            if o and o.strip().lower() not in ("", "select an option", "select...", "select one")]
    if getattr(f, "kind", "") == "checkbox":
        return "uncheck", False
    if getattr(f, "kind", "") in ("radio", "radio_group", "select", "combobox"):
        if not opts:
            return None
        from .screen_review import _coerce_option
        no = _coerce_option("No", opts)
        return None if no is None else (_action_for_kind(f.kind), no)
    return None


def _decision(f, name: str) -> FillDecision | None:
    dv = decline_value(f)
    if dv is None:
        return None
    action, value = dv
    return FillDecision(f.ref, f.kind, f.label, value, action, SOURCE,
                        basis=f"{DECLINE_BASIS} ({name} pattern)")


def gate(fields):
    """Run the gate over `fields`: (decline decisions, remaining, held).

    decisions — FillDecisions to fill/untick, source "decline_class".
    remaining — fields the gate's hands are off (Verdict "ask"): the ladder
      continues exactly as before.
    held — list of (field, basis, escalated) the gate consumed with NO decision
      and NO tier ask:
      required acquisition asks (escalated=True: held for the human at the
        escalation boundary; answer_fields appends them to `needs`) and
      optional asks whose widget can express no "No" (escalated=False: left
        undecided, recorded for audit so nothing silently disappears)."""
    decisions, remaining, held = [], [], []
    for f in fields:
        v = classify(f)
        if v.action == ASK:
            remaining.append(f)
            continue
        if v.action == SKIP:
            held.append((f, f"required marketing opt-in held back by the decline gate ({v.reason})", True))
            continue
        d = _decision(f, v.pattern)
        if d is None:
            held.append((f, f"marketing opt-in left undecided: no option expresses 'No' ({v.pattern} pattern)",
                         False))
            continue
        decisions.append(d)
    return decisions, remaining, held
