"""Fields inside a repeated résumé entry (a work-experience or education block), read by their structure.

Workday names every box after its entry and role: `workExperience-351--startDate-dateSectionMonth-input`,
`education-368--lastYearAttended-dateSectionYear-input`, `workExperience-351--roleDescription`. A bare "Month" or
"Year" label means nothing to the question bank (it guessed "2023" for every Year box, live 2026-10-25), but the id
says which entry, which date and which part. Those come straight from the profile, before the bank is asked."""
from __future__ import annotations

import re
from datetime import datetime

from .mapper import FillDecision, _action_for_kind

_WORK = re.compile(r"work|experience|employment|employer|job|position", re.I)
_EDU = re.compile(r"educat|school|degree|academ|universit|college", re.I)
_START = re.compile(r"start|from|begin|first", re.I)
_END = re.compile(r"end(?!er)|until|last|finish|\bto\b", re.I)
_MONTH = re.compile(r"month|\bmm\b", re.I)
_YEAR = re.compile(r"year|\byyyy\b", re.I)
_ROLE = re.compile(r"role ?description|responsibilit|job ?description|duties|description", re.I)
_ENTRY = re.compile(r"([A-Za-z]+)-(\d+)--")          # the entry's own key: "workExperience-351--"
_ONGOING = re.compile(r"present|current|now|ongoing|till date", re.I)


_SWAP = {">": " over ", "<": " under ", "[": "(", "]": ")", "{": "(", "}": ")", '"': "'", "\\": "/"}


def _plain(text: str) -> str:
    """Characters Workday's text boxes refuse ("Contains illegal characters < > [ ] \" { } \\", Opella 2026-10-26):
    'ROC >85' reads 'ROC over 85'."""
    text = text.replace("**", "").replace("__", "")      # the résumé's markdown bold ('**IRDAI**', Pretium 2026-10-26)
    for a, b in _SWAP.items():
        text = text.replace(a, b)
    return __import__("re").sub(r"[ \t]{2,}", " ", text).replace(" \n", "\n")


def _hay(f) -> str:
    return f"{getattr(f, 'part_hint', '') or ''} {f.ref}"


def _date_parts(text: str):
    """'July 2023' / 'Jul 2022' / '2019' -> ('07', '2023'); None when absent or ongoing."""
    t = (text or "").strip()
    if not t or _ONGOING.search(t):
        return None
    for fmt in ("%B %Y", "%b %Y", "%m/%Y", "%Y"):
        try:
            d = datetime.strptime(t, fmt)
            return (f"{d.month:02d}" if fmt != "%Y" else None), str(d.year)
        except ValueError:
            continue
    return None


def _entries(profile, kind):
    """[(start, end, bullets)] for the profile's work or education entries, in résumé order."""
    if kind == "work":
        return [(e.start, e.end, list(e.bullets), e) for e in getattr(profile, "experiences", [])]
    edu = [(e.start, e.end, [], e) for e in getattr(profile, "education", [])]
    contact = getattr(profile, "contact", {}) or {}
    if edu and not (edu[0][0] or edu[0][1]):           # the résumé line has no dates: the profile's own education dates
        edu[0] = (contact.get("education_start", ""), contact.get("education_end", ""), [], edu[0][3])
    return edu


# The entry's own words, by the part its id names (Workday: workExperience-351--jobTitle, education-368--schoolName).
# One bank answer would put the current employer into every entry (Walmart, live 2026-10-30: OYO's box too).
_PARTS = {"work": [(re.compile(r"job ?title|position ?title|^title", re.I), "title"),
                   (re.compile(r"company|employer|organi[sz]ation", re.I), "company")],
          "edu": [(re.compile(r"school|institution|universit|college", re.I), "school"),
                  (re.compile(r"degree", re.I), "degree")]}
_CURRENT = re.compile(r"currently ?work|current ?(job|role|position)|present", re.I)


def _part(kind, rest, entry):
    for pat, attr in _PARTS[kind]:
        if pat.search(rest):
            v = str(getattr(entry, attr, "") or "").strip()
            return re.sub(r"\s*\((?:internship|intern|contract|part[- ]time)\)\s*$", "", v, flags=re.I) or None
    return None


def entry_decisions(fields, profile):
    """(decisions, remaining): every field whose id places it in a work/education entry and names its date part or
    the role description, answered from that entry. An ongoing job's end date is left out of both lists — the
    'I currently work here' tick covers it."""
    order: dict = {}
    for f in fields:                                   # entry number by first appearance on the page, per kind
        m = _ENTRY.search(_hay(f))
        if m:
            kind = "work" if _WORK.search(m.group(1)) else "edu" if _EDU.search(m.group(1)) else None
            if kind:
                order.setdefault(kind, [])
                if m.group(0) not in order[kind]:
                    order[kind].append(m.group(0))
    decisions, remaining = [], []
    for f in fields:
        hay, m = _hay(f), _ENTRY.search(_hay(f))
        kind = m and ("work" if _WORK.search(m.group(1)) else "edu" if _EDU.search(m.group(1)) else None)
        if not kind:
            remaining.append(f)
            continue
        idx = order[kind].index(m.group(0))
        entries = _entries(profile, kind)
        if idx >= len(entries):
            remaining.append(f)
            continue
        start, end, bullets, entry = entries[idx]
        rest = hay[m.end():]                           # the part after the entry key: "startDate-dateSectionMonth-input"
        value = None
        if kind == "work" and f.kind == "checkbox" and _CURRENT.search(rest + " " + (f.label or "")):
            if _ONGOING.search(end or ""):
                decisions.append(FillDecision(f.ref, f.kind, f.label, True, "check", "resume",
                                              basis=f"work entry {idx + 1}: still there"))
            continue                                   # a past job: the box stays unticked
        if kind == "work" and re.search(r"location|city", rest, re.I) and not _ONGOING.search(end or ""):
            continue    # a past job's place is not on the résumé; your city today is not where OYO was (Walmart 2026-10-30)
        if f.kind != "checkbox" and (part := _part(kind, rest, entry)):
            decisions.append(FillDecision(f.ref, f.kind, f.label, part, _action_for_kind(f.kind), "resume",
                                          basis=f"{kind} entry {idx + 1} from your résumé"))
            continue
        if kind == "work" and f.kind == "textarea" and _ROLE.search(rest + " " + (f.label or "")):
            value = _plain("\n".join(f"• {b}" for b in bullets)) or None
        elif _MONTH.search(rest) or _YEAR.search(rest):
            which = start if _START.search(rest) else end if _END.search(rest) else None
            if which is not None and _END.search(rest) and _ONGOING.search(which or ""):
                continue                               # still there: no end date to give
            parts = _date_parts(which or "")
            if parts:
                value = parts[0] if _MONTH.search(rest) else parts[1]
        if value:
            decisions.append(FillDecision(f.ref, f.kind, f.label, value, "fill", "resume",
                                          basis=f"{kind} entry {idx + 1} from your résumé"))
        else:
            remaining.append(f)
    return decisions, remaining


if __name__ == "__main__":                             # one runnable check
    from types import SimpleNamespace as N
    prof = N(experiences=[N(start="July 2023", end="Present", bullets=["a", "b"], title="Data Scientist", company="Tata AIG"),
                          N(start="May 2022", end="Jul 2022", bullets=["c"], title="Data Science Intern",
                            company="OYO (Internship)")],
             education=[N(start="", end="", school="IIT (BHU) Varanasi", degree="B.Tech")], contact={"education_start": "July 2019", "education_end": "May 2023"})
    F = lambda ref, kind="text", label="Month": N(ref=ref, kind=kind, label=label, part_hint=ref.lstrip("#"))
    fs = [F("#workExperience-351--startDate-dateSectionMonth-input"), F("#workExperience-351--startDate-dateSectionYear-input", label="Year"),
          F("#workExperience-351--endDate-dateSectionMonth-input"), F("#workExperience-351--roleDescription", "textarea", "Role Description"),
          F("#workExperience-352--endDate-dateSectionMonth-input"), F("#education-368--lastYearAttended-dateSectionYear-input", label="Year"),
          F("#name", label="Name")]
    ds, rest = entry_decisions(fs, prof)
    assert [d.value for d in ds] == ["07", "2023", "• a\n• b", "07", "2023"], [d.value for d in ds]
    assert [f.ref for f in rest] == ["#name"]          # the ongoing job's end month is in neither list
    more = [F("#workExperience-351--jobTitle", label="Job Title"), F("#workExperience-352--companyName", label="Company"),
            F("#workExperience-351--currentlyWorkHere", "checkbox", "I currently work here"),
            F("#workExperience-352--currentlyWorkHere", "checkbox", "I currently work here"),
            F("#education-368--schoolName", label="School"), F("#workExperience-352--location", label="Location")]
    ds, rest = entry_decisions(fs[:5] + more, prof)
    got = {d.ref: d.value for d in ds}
    assert got["#workExperience-351--jobTitle"] == "Data Scientist" and got["#workExperience-352--companyName"] == "OYO"
    assert got["#workExperience-351--currentlyWorkHere"] is True and "#workExperience-352--currentlyWorkHere" not in got
    assert got["#education-368--schoolName"] == "IIT (BHU) Varanasi"
    assert "#workExperience-352--location" not in got and "#workExperience-352--location" not in [f.ref for f in rest]
    print("ok")
