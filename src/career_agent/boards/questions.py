"""Upfront questionnaires — JSON a board sends before rendering its form — as
Field lists, so the shared answer ladder answers every question before any
irreversible click. One parser per board shape; the board profile names it."""
from __future__ import annotations

from ..browser.form_model import Field, guess_purpose

# Naukri questionType -> Field.kind. Multi-select "Check Box" maps to
# radio_group so the ladder coerces the answer onto a real option.
_NAUKRI_KINDS = {"text box": "text", "text area": "textarea", "radio button": "radio_group",
                 "check box": "radio_group", "list menu": "select", "drop down": "select"}


def _options(ans):
    return [str(v) for v in (ans.values() if isinstance(ans, dict) else ans or [])]


def naukri(questionnaire):
    """Naukri apply-workflow `jobs[0].questionnaire` -> (fields, prefill {ref: value}).
    prefill is Naukri's own profile value for that question (prefillData)."""
    fields, prefill = [], {}
    for q in questionnaire or []:
        ref, label = f"q:{q.get('questionId')}", (q.get("questionName") or "").strip()
        kind = _NAUKRI_KINDS.get((q.get("questionType") or "").strip().lower(), "text")
        fields.append(Field(ref, kind, label, bool(q.get("isMandatory")),
                            _options(q.get("answerOption")), None, guess_purpose(label, kind)))
        if q.get("prefillData"):
            prefill[ref] = q["prefillData"][0]
    return fields, prefill


PARSERS = {"naukri": naukri}
