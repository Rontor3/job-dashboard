# Question Bank Preferences Implementation Plan

> **For agentic workers:** superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Ordered-preference entries (work arrangement, employment type, shifts, relocation) answer pick-one and yes/no wordings consistently; overlapping entries merged/retired.
**Spec:** `docs/superpowers/specs/2026-10-03-qbank-preferences-design.md`
**Global constraints:** seed never carries answers; no `Co-Authored-By`; files < 500 lines; PYTHONPATH=src python3 -m pytest …; ponytail style; never `git stash`; stage only task files.
Worktree `/Users/rakshitsingh/Desktop/My_project/qbank-pref` (branch feat/qbank-pref, from main). Baseline: `PYTHONPATH=src python3 -m pytest tests/career_agent tests/test_qa_api.py -q`.

---

### Task P1: `preference` rule + options plumbing

**Files:** `src/career_agent/memory/qbank_rules.py`, `src/career_agent/memory/qbank_match.py`, `tests/conftest.py`, `tests/career_agent/test_qbank_rules.py`, `tests/career_agent/test_qbank_match.py`

- [ ] **Step 1: tests first.**
In `tests/career_agent/test_qbank_rules.py` (keep existing; `RuleCtx` gets new defaulted fields so `ctx()` helper still works — extend it with `options=None, synonyms=None`):

```python
ARR = "Remote > Hybrid > Onsite"
SYN = {"Remote": ["remote", "remotely", "work from home", "wfh"], "Hybrid": ["hybrid"],
       "Onsite": ["onsite", "on-site", "in office", "in-person", "from the office"]}


def pctx(question="", answer=ARR, options=None, synonyms=SYN):
    return RuleCtx(question, answer, None, {}, lambda e: None, options=options or [], synonyms=synonyms)


def test_preference_pick_one_takes_highest_ranked_offered():
    r = RULES["preference"]
    assert r(pctx(options=["Onsite", "Hybrid", "Remote"])) == "Remote"
    assert r(pctx(options=["On-site (office)", "Hybrid"])) == "Hybrid"
    assert r(pctx(options=["On-site (office)"])) == "On-site (office)"     # only onsite offered -> onsite is fine
    assert r(pctx(options=["Contract", "Intern"])) is None                 # nothing maps -> no answer


def test_preference_yes_no_uses_named_alternative():
    r = RULES["preference"]
    for q in ("Are you comfortable working in an onsite setting?", "Open to working remotely?",
              "Are you open to remote or hybrid roles?"):
        assert r(pctx(q, options=["Yes", "No"])) == "Yes", q
    assert r(pctx("Are you open to onsite?", answer="Remote > Hybrid; not: Onsite", options=["Yes", "No"])) == "No"
    assert r(pctx("Open to remote or onsite?", answer="Remote; not: Onsite")) is None      # mixed
    assert r(pctx("Are you open to the arrangement?", options=["Yes", "No"])) is None      # none named


def test_preference_text_and_unanswered():
    r = RULES["preference"]
    assert r(pctx("What is your preferred work mode?")) == "Remote"        # no options, none named -> top choice
    assert r(pctx("Open to onsite?", answer=None)) is None
    assert r(pctx("Open to onsite?", answer="")) is None
```
Update `test_seed_only_uses_known_rules` expectations only via the new RULES/RULE_HELP entries (it already asserts `set(RULE_HELP) == set(RULES)`).

In `tests/conftest.py` append to `QBANK_ENTRIES`:
```python
    {"id": "work_arrangement", "question": "What is your preferred work arrangement (remote, hybrid or onsite)?",
     "atype": "choice", "rule": "preference", "answer": "Remote > Hybrid > Onsite",
     "wordings": ["Are you comfortable working in an onsite setting?"],
     "synonyms": {"Remote": ["remote", "work from home"], "Hybrid": ["hybrid"], "Onsite": ["onsite", "on-site", "in office"]}},
```
(and make the fixture's `upsert_entry` keep passing `synonyms`; it already passes the whole dict).
In `tests/career_agent/test_qbank_match.py` append:
```python
def test_preference_entry_answers_pick_one_and_yes_no(qbank_conn, fake_embed, make_field):
    f = make_field("What is your preferred work arrangement (remote, hybrid or onsite)?", "radio_group",
                   ["Onsite", "Hybrid", "Remote"])
    m, v = answer_field(qbank_conn, f, embed=fake_embed)
    assert (m.entry_id, v) == ("work_arrangement", "Remote")
    f = make_field("Are you comfortable working in an onsite setting?", "radio_group", ["Yes", "No"])
    m, v = answer_field(qbank_conn, f, embed=fake_embed)
    assert (m.entry_id, v) == ("work_arrangement", "Yes")
```

- [ ] **Step 2: run, expect FAIL** (`KeyError: 'preference'` / RuleCtx args).

- [ ] **Step 3: `qbank_rules.py`.** `from dataclasses import dataclass, field`; add to `RuleCtx` after `bank`:
```python
    options: list = field(default_factory=list)    # the page field's options (pick-one questions)
    synonyms: dict = field(default_factory=dict)   # entry synonyms; for preference: {alternative: [keywords]}
```
Add:
```python
_YESNO = {"yes", "no", "true", "false"}


def _pref(answer):
    """'A > B > C; not: X, Y' -> (['A','B','C'], ['X','Y'])."""
    head, _, tail = (answer or "").partition(";")
    order = [x.strip() for x in head.split(">") if x.strip()]
    nope = []
    if tail.strip().lower().startswith("not"):
        nope = [x.strip() for x in tail.split(":", 1)[-1].split(",") if x.strip()]
    return order, nope


def _named(text, synonyms, alts):
    """Alternatives whose keywords appear (whole word, any case) in text."""
    t = (text or "").lower()
    return [a for a in alts if any(re.search(rf"(?<!\w){re.escape(k.lower())}(?!\w)", t)
                                   for k in (synonyms.get(a) or [a]))]


def preference(c: RuleCtx):
    """Ordered acceptable alternatives -> the page's pick-one option, or Yes/No for a yes/no wording."""
    order, nope = _pref(c.answer)
    if not order:
        return None
    alts = order + nope
    opts = [o for o in c.options if o.strip().lower() not in _YESNO]
    if opts:
        by_alt = {}
        for o in opts:
            hit = _named(o, c.synonyms, alts)
            if len(hit) == 1:
                by_alt.setdefault(hit[0], o)
        return next((by_alt[a] for a in order if a in by_alt), None)
    named = _named(c.question, c.synonyms, alts)
    if not named:
        return None if c.options else order[0]
    ok = [a in order for a in named]
    return "Yes" if all(ok) else "No" if not any(ok) else None
```
Register: add `preference` to the `RULES` tuple; `RULE_HELP["preference"] = "Best first, separated by >, e.g. Remote > Hybrid > Onsite. Add '; not: X, Y' for options you refuse. Pick-one questions get your highest-ranked offered option; yes/no questions get Yes if the option asked about is on your list, No if refused."`

- [ ] **Step 4: `qbank_match.py`.** `resolve_value(conn, entry, *, question, escape, job, contact, options=(), _depth=0)`; pass `options=list(options), synonyms=entry.get("synonyms") or {}` in the `RuleCtx(...)` call (the nested `bank()` recursion passes none). In `answer_field` call `resolve_value(..., options=f.options)`.
- [ ] **Step 5: GREEN** — focused tests then `PYTHONPATH=src python3 -m pytest tests/career_agent tests/test_qa_api.py -q`.
- [ ] **Step 6: commit** `feat(qbank): ordered-preference rule for pick-one and yes/no work/employment/shift/relocation questions`.

---

### Task P2: seed entries, cleanup (merge/retire), CLI

**Files:** `src/career_agent/memory/qbank_seed.json`, `src/career_agent/memory/qbank_admin.py`, `scripts/qbank.py`, `tests/career_agent/test_qbank_admin.py`, `tests/career_agent/test_qbank.py`, `tests/test_qa_api.py`

- [ ] **Step 1: tests first.** Append to `tests/career_agent/test_qbank_admin.py`:
```python
import json
from career_agent.memory.qbank_admin import MERGES, RETIRE, cleanup, merge_entry


def _two(c, fake_embed):
    for i in ("a", "b"):
        qbank.upsert_entry(c, {"id": i, "question": f"q {i}", "atype": "text"})
    qbank.add_wording(c, "Old wording?", "a", fake_embed(["Old wording?"])[0], "seed")


def test_merge_moves_wordings_and_supersedes(qbank_conn, fake_embed):
    _two(qbank_conn, fake_embed)
    assert merge_entry(qbank_conn, "a", "b") == 1
    assert qbank.exact(qbank_conn, "Old wording?") == "b"
    assert qbank.get_entry(qbank_conn, "a")["status"] == "superseded"
    assert merge_entry(qbank_conn, "a", "b") == 0                    # idempotent
    assert merge_entry(qbank_conn, "nope", "b") == 0 and merge_entry(qbank_conn, "b", "nope") == 0


def test_cleanup_on_real_seed(fake_embed):
    c = sqlite3.connect(":memory:")
    qbank.ensure(c)
    raw = json.loads(qbank.SEED_PATH.read_text())["entries"]
    ids = {e["id"] for e in raw}
    assert {d for _, d in MERGES} <= ids                              # survivors are in the seed
    assert not ({s for s, _ in MERGES} | set(RETIRE)) & ids           # removed ones are gone from the seed
    for e in raw:
        qbank.upsert_entry(c, e)
    for s in [s for s, _ in MERGES] + RETIRE:                         # simulate a DB seeded before this change
        qbank.upsert_entry(c, {"id": s, "question": s, "atype": "text"})
    r = cleanup(c)
    assert r["merged"] == len(MERGES) and r["retired"] == len(RETIRE)
    assert all(qbank.get_entry(c, s)["status"] == "superseded" for s, _ in MERGES)
    assert cleanup(c) == {"merged": 0, "retired": 0}                  # idempotent
```
(`sqlite3` must be imported in that file; add if missing.) In `test_qbank.py` change the `len(raw) >= 90` assertion to `>= 80` and add:
```python
def test_preference_entries_in_seed():
    by = {e["id"]: e for e in json.loads(qbank.SEED_PATH.read_text())["entries"]}
    for eid in ("work_arrangement", "employment_type", "shift_pattern", "relocation_places"):
        assert by[eid]["rule"] == "preference" and by[eid]["synonyms"], eid
    assert "gurugram" in by["relocation_places"]["synonyms"]["India"]
```
In `tests/test_qa_api.py` change `len(body["answers"]) >= 90` to `>= 80`. `grep -rn "onsite_ok\|shifts_ok\|contract_ok\|full_time_ok\|relevant_experience_years\|interviewed_recently\|timeline_considerations" tests src --include=*.py` and update any test that references a removed id.

- [ ] **Step 2: run, expect FAIL.**

- [ ] **Step 3: `qbank_admin.py`** — append:
```python
MERGES = [("relevant_experience_years", "total_experience_years"), ("interviewed_recently", "interviewed_before"),
          ("timeline_considerations", "earliest_start"), ("onsite_ok", "work_arrangement"),
          ("shifts_ok", "shift_pattern"), ("contract_ok", "employment_type"), ("full_time_ok", "employment_type")]
RETIRE = ["ctc_fixed_component", "ctc_variable_component", "other_offer_ctc", "whatsapp_ok", "sms_consent",
          "drug_test_ok", "driving_license", "passport_valid", "home_office_setup"]


def merge_entry(conn, src, dst) -> int:
    """Re-point src's wordings to dst and supersede src. Returns wordings moved; 0 if either side is missing
    or src is already superseded (idempotent). Nothing is deleted."""
    s, d = qbank.get_entry(conn, src), qbank.get_entry(conn, dst)
    if s is None or d is None or s["status"] != "active":
        return 0
    n = conn.execute("UPDATE qbank_wording SET entry_id=? WHERE entry_id=?", (dst, src)).rowcount
    qbank.set_status(conn, src, "superseded")
    return n


def cleanup(conn) -> dict:
    """Merge overlapping entries and retire rarely-asked ones (idempotent). Load the seed first so survivors exist."""
    merged = sum(1 for s, d in MERGES if qbank.get_entry(conn, s) and qbank.get_entry(conn, s)["status"] == "active"
                 and qbank.get_entry(conn, d) and (merge_entry(conn, s, d) or True))
    retired = sum(1 for i in RETIRE if qbank.get_entry(conn, i) and qbank.get_entry(conn, i)["status"] == "active"
                  and qbank.set_status(conn, i, "superseded"))
    return {"merged": merged, "retired": retired}
```
(Implementer may write the two counters as plain loops if clearer; behaviour is what the test pins.)

- [ ] **Step 4: `scripts/qbank.py`** — add `cleanup` to the choices; branch: `qbank.load_seed(conn, embed); print(json.dumps(cleanup(conn)))` (import `cleanup`); extend the docstring.

- [ ] **Step 5: seed JSON** (`src/career_agent/memory/qbank_seed.json`, one entry per line as today). With a small throwaway Python script (not committed) rewrite the file keeping the header lines and one-JSON-object-per-line format:
  1. Remove entries: relevant_experience_years, interviewed_recently, timeline_considerations, onsite_ok, shifts_ok, contract_ok, full_time_ok, ctc_fixed_component, ctc_variable_component, other_offer_ctc, whatsapp_ok, sms_consent, drug_test_ok, driving_license, passport_valid, home_office_setup.
  2. Fold wording lists (each removed entry's `question` + `wordings`) into: relevant_experience_years→total_experience_years, interviewed_recently→interviewed_before, timeline_considerations→earliest_start. No wording may appear twice in the file (test pins uniqueness).
  3. Replace the existing `work_arrangement` entry and add three more (all `"atype": "choice"`, `"rule": "preference"`, no `answer`):
```json
{"id": "work_arrangement", "topic": "location", "atype": "choice", "rule": "preference", "question": "What is your preferred work arrangement (remote, hybrid or onsite)?", "wordings": ["Work mode preference", "Are you open to working in-person from the office?", "Are you comfortable working in an onsite setting?", "Are you open to working in-person in one of our offices 25% of the time?", "Are you comfortable working from the office 3 days a week?", "Are you able to work on-site?", "Are you open to working remotely?", "Are you open to a hybrid work model?"], "synonyms": {"Remote": ["remote", "remotely", "work from home", "wfh", "distributed"], "Hybrid": ["hybrid"], "Onsite": ["onsite", "on-site", "on site", "in office", "in-office", "in-person", "in person", "from the office", "office"]}}
{"id": "employment_type", "topic": "availability", "atype": "choice", "rule": "preference", "question": "What type of employment are you looking for (full-time, contract, part-time, internship)?", "wordings": ["Employment type", "Job type", "Are you open to a contract role?", "Would you consider a contract-to-hire position?", "Are you looking for a full-time role?", "Are you available for full-time employment?", "Are you open to part-time work?"], "synonyms": {"Full-time": ["full-time", "full time", "permanent"], "Contract": ["contract", "contract-to-hire", "contractor", "freelance"], "Part-time": ["part-time", "part time"], "Internship": ["internship", "intern"]}}
{"id": "shift_pattern", "topic": "availability", "atype": "choice", "rule": "preference", "question": "Which shifts are you comfortable working (day, rotational or night)?", "wordings": ["Are you comfortable working night or rotational shifts?", "Are you open to working in shifts?", "Shift preference", "Are you open to night shifts?"], "synonyms": {"Day": ["day shift", "daytime", "general shift"], "Rotational": ["rotational", "rotating", "shifts"], "Night": ["night", "night shift", "graveyard"]}}
{"id": "relocation_places", "topic": "location", "atype": "choice", "rule": "preference", "question": "Which places are you willing to relocate to?", "wordings": ["Would you be open to relocating to Dubai, UAE, if required for the role?", "Are you currently residing in Gurugram or willing to relocate to Gurugram?", "Are you currently residing in Gurugram, Haryana or willing to relocate to Gurugram, Haryana?", "Are you willing to relocate to Bangalore?", "Are you open to relocating to the United States?"], "synonyms": {"India": ["india", "mumbai", "delhi", "new delhi", "gurugram", "gurgaon", "noida", "ghaziabad", "bengaluru", "bangalore", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad", "jaipur", "kochi", "chandigarh", "indore", "coimbatore", "haryana", "maharashtra", "karnataka", "telangana", "tamil nadu", "uttar pradesh"], "UAE": ["uae", "dubai", "abu dhabi", "united arab emirates", "sharjah"], "US": ["usa", "united states", "america", "new york", "san francisco", "california", "texas", "seattle"], "UK": ["uk", "united kingdom", "london", "england"], "Europe": ["europe", "germany", "berlin", "netherlands", "amsterdam", "france", "paris", "ireland", "dublin", "spain", "switzerland", "sweden"], "Canada": ["canada", "toronto", "vancouver"], "Singapore": ["singapore"], "Australia": ["australia", "sydney", "melbourne"]}}
```
  The existing `willing_to_relocate` entry stays (place-less, profile-backed).

- [ ] **Step 6: GREEN** — `PYTHONPATH=src python3 -m pytest tests/career_agent tests/test_qa_api.py -q`.
- [ ] **Step 7: commit** `feat(qbank): preference entries in the seed; cleanup merges overlapping entries and retires rarely-asked ones`.
