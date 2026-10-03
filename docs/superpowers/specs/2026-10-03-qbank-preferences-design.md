# Question bank — ordered preference entries + cleanup

Date: 2026-10-03 · Status: approved by user in chat · Builds on `2026-09-26-question-bank-design.md`

## Problem
Pick-one and yes/no wordings of the same preference contradict each other across sites:
"Remote / Hybrid / Onsite" (pick one), "Are you comfortable working in an onsite setting?" (yes/no),
"Would you be open to relocating to Dubai?" (yes/no), "Gurugram or willing to relocate to Gurugram?".
Today each wording is a separate yes/no entry (or an LLM guess), so answers are inconsistent and
many near-duplicate entries overlap (hold-one-out calibration: 0.789 top-1, misses between adjacent entries).

## Design
**Preference entry** = `rule: "preference"`, `atype: "choice"`. Stored answer: an ordered list of
acceptable alternatives, best first, plus optional refusals: `Remote > Hybrid > Onsite` or
`India; not: UAE, US, UK`. Entry `synonyms` = `{alternative: [keywords]}` (keywords are whole-word,
case-insensitive; an alternative with no keyword list matches its own name).

`preference(ctx)` (in `qbank_rules.py`):
- **Pick-one** (page has options other than yes/no): map each option to the alternatives whose keywords
  it contains (exactly one); return the option text of the highest-ranked acceptable alternative; none → `None`.
- **Yes/no or text with named alternative(s)** in the question: all named acceptable → `Yes`;
  all refused → `No`; mixed or none named → `None`.
- **No options and none named** (free-text "preferred work mode?"): the top-ranked alternative.
- Unanswered entry → `None`. `None` means "no bank answer" (existing semantics: the field falls through
  to rules/judge like any unanswered question).

`RuleCtx` gains `options: list` and `synonyms: dict`; `resolve_value`/`answer_field` pass the field's options.

**Entries** (seed has structure + keywords, never answers):
`work_arrangement` (Remote/Hybrid/Onsite), `employment_type` (Full-time/Contract/Part-time/Internship),
`shift_pattern` (Day/Rotational/Night), `relocation_places` (India/UAE/US/UK/Europe/Canada/Singapore/Australia,
keywords = countries + major cities). User's answers (applied to the real DB, not committed):
`Remote > Hybrid > Onsite` · `Full-time > Contract > Part-time; not: Internship` ·
`Day > Rotational > Night` · `India; not: UAE, US, UK, Europe, Canada, Singapore, Australia`.

**Cleanup** (`qbank_admin.cleanup`, CLI `scripts/qbank.py cleanup`, idempotent, nothing deleted):
- merge (re-point all wordings to the survivor, supersede the source):
  relevant_experience_years→total_experience_years, interviewed_recently→interviewed_before,
  timeline_considerations→earliest_start, onsite_ok→work_arrangement, shifts_ok→shift_pattern,
  contract_ok→employment_type, full_time_ok→employment_type.
- retire (supersede): ctc_fixed_component, ctc_variable_component, other_offer_ctc, whatsapp_ok,
  sms_consent, drug_test_ok, driving_license, passport_valid, home_office_setup (re-added from real
  forms via "save as new entry").
- Removed entries are also removed from the seed (their wordings folded into the survivors).

**Dashboard:** no UI change — preference entries show the existing text box plus `rule_help`
explaining the `A > B > C; not: D` format.

## Known limits
- A question naming an alternative with no keyword (unknown city) → `None` → falls to the judge, not a
  hard flag. Add the keyword (or a new alternative) to the entry's synonyms when it shows up.
- Keyword matching is lexical; unusual phrasings fall back to the LLM pick/judge as before.
