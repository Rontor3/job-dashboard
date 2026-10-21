"""READ-ONLY retrieval experiments for answer-pipeline triage.

Run: PYTHONPATH=src python3 triage_experiment.py "/path/to/main/data/jobs.db"
Never writes. Applies qbank.exact via SELECT + match_question + resolve_value +
shape_ok + _coerce_option, reproducing the decision path for the failed fields.
"""
import json
import re
import sqlite3
import sys

# Open the main repo's DB strictly read-only.
conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

from career_agent.memory import qbank
from career_agent.memory.qbank_match import (answer_field, match_question, fit_option,
                                             split_escape, resolve_value, FLOOR, DEFAULT_HIGH)
from career_agent.memory.qbank_rules import infer_shape, shape_ok
from career_agent.orchestrator.screen_review import _coerce_option

embed = qbank.default_embed
qbank.seed_if_empty(conn, embed)   # in-memory rows only if db empty; db NOT empty
print("entries:", conn.execute("SELECT COUNT(*) FROM qbank_entry").fetchone()[0],
      "wordings:", conn.execute("SELECT COUNT(*) FROM qbank_wording").fetchone()[0],
      "FLOOR", FLOOR, "DEFAULT_HIGH", DEFAULT_HIGH)

CASES = [
    # (page label, description, field kind, input_type, options, purpose)
    ("How Did You Hear About Us?", "", "combobox", "", ["LinkedIn", "Indeed", "Google", "Referral", "Job Board - Other", "Other"], None),
    ("How Did You Hear About Us?*", "", "combobox", "", [], None),
    ("How did you hear about us?", "", "select", "", ["Job Board", "Referral", "Company Website", "Other"], None),
    ("How Did You Hear About Us?", "", "select", "", ["Talent Community", "Campus", "Print Ad.", "Job Portals (Naukri, Indeed)", "Social Media", "Referral"], None),
    ("Country Phone Code*", "", "combobox", "", [], None),
    ("Country Phone Code*", "", "select", "", ["+91 (India)", "+1 (United States)", "India (+91)", "+91", "+1"], None),
    ("Get email updates for the latest data scientist jobs in Bengaluru, Karnataka", "", "checkbox", "", [], None),
    ("Get email updates for the latest senior data scientist jobs", "", "checkbox", "", [], None),
    ("What interests you about working for this company?", "", "textarea", "", [], None),
    ("How did you hear about this job? Google Search Friend or Family Company Website Advertisement (TV, Radio, Print) Other", "", "select", "", ["Google Search", "Friend or Family", "Company Website", "Advertisement (TV, Radio, Print)", "Other"], None),
]

job = {"company": "RANI", "location": "Bengaluru, Karnataka"}
contact = {"phone": "+91 9900000000", "email": "rs@example.com"}

from career_agent.browser.form_model import Field
for label, desc, kind, itype, options, purpose in CASES:
    f = Field(ref="#x", kind=kind, label=label, required=True, options=options,
              description=desc, input_type=itype, purpose=purpose)
    quest, escape = split_escape(label, desc)
    m = match_question(conn, qbank_match_without_hint := label.replace("*", ""), embed=embed, llm=None)
    eid = qbank.exact(conn, quest)
    print("\n===", label[:70])
    print("  split_escape ->", repr(quest), "escape:", repr(escape))
    print("  exact wording hit?:", eid)
    print("  match ->", m.band, m.kind, m.entry_id, m.score, "cands:", m.candidates, "note:", m.note)
    if m.entry_id:
        entry = qbank.get_entry(conn, m.entry_id)
        val = resolve_value(conn, entry, question=quest, escape=escape, job=job, contact=contact, options=options)
        shape = infer_shape(entry["shape"] if entry else None, itype, "", label)
        print("  entry ->", entry["id"], "| answer:", repr(entry["answer"]), "| shape->", shape,
              "| shape_ok:", shape_ok(shape, val, escape))
        fitted = fit_option(label, val, options, entry["synonyms"], None)
        print("  fit_option among", len(options), "site options ->", repr(fitted))
    else:
        facts_free = None
        print("  no entry: would fall to rules/judge/facts-plan tier")
