"""Turn a hiring post's free text into actionable channels, and a post into a
``JobListing`` so the per-job pipeline (tailored résumé, company research,
cover letter, career_agent) works on it unchanged.

Pure regex for contacts; role/company use a single LLM JSON call (job_dashboard.llm) with
a regex fallback. Nothing here sends anything.
"""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlparse

from job_dashboard.llm import complete_json
from job_dashboard.models import JobListing

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|\b(?:lnkd\.in|forms\.gle|bit\.ly)/)[^\s<>\"')]+")
# Indian mobiles (+91 / 10 digits starting 6-9) and generic +CC numbers.
_PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b|\+\d{1,3}[\s-]?\d[\d\s-]{7,12}\d")
_DM = re.compile(r"\b(?:DM|dm me|direct message|inbox me|message me)\b", re.I)
_FORM_HOSTS = ("forms.gle/", "docs.google.com/forms", "forms.office.com", "typeform.com",
               "jotform.com", "tally.so")
_NOISE_LINK = ("linkedin.com/in/", "linkedin.com/feed", "linkedin.com/company")


def extract_contacts(text: str, url: str | None = None) -> dict:
    """{emails, forms, links, phones, dm} found in ``text`` (+ the post url when
    it is an embedded apply link rather than the poster's profile)."""
    text = text or ""
    raw = [u.rstrip(".,;:!") for u in _URL.findall(text)]
    if url and "linkedin.com/in/" not in url:
        raw.append(url)
    links = []
    for u in raw:
        u = u if u.startswith("http") else "https://" + u
        host = urlparse(u).hostname or ""
        # "B.Tech", "M.Sc" — degree abbreviations read as bare hosts (two labels,
        # one-letter first); real one-letter subdomains like t.mercor.com stay.
        labels = host.split(".")
        if not host or (len(labels) == 2 and len(labels[0]) < 2):
            continue
        if u not in links and not any(n in u for n in _NOISE_LINK):
            links.append(u)
    forms = [u for u in links if any(h in u for h in _FORM_HOSTS)]
    return {
        "emails": list(dict.fromkeys(e.rstrip(".").lower() for e in _EMAIL.findall(text))),
        "forms": forms,
        "links": [u for u in links if u not in forms],
        "phones": list(dict.fromkeys(re.sub(r"[\s-]", "", p) for p in _PHONE.findall(text))),
        "dm": bool(_DM.search(text)),
    }


def resolve_link(url: str, get=None) -> str:
    """Follow a shortener (lnkd.in, forms.gle, bit.ly) to its final URL; the
    input url on any failure. LinkedIn's lnkd.in interstitial keeps the real
    target in the page, so fall back to scraping it from the body."""
    try:
        if get is None:
            import requests
            get = lambda u: requests.get(u, timeout=10, allow_redirects=True,  # noqa: E731
                                         headers={"User-Agent": "Mozilla/5.0"})
        r = get(url)
        final = str(r.url)
        if "lnkd.in" in final or "linkedin.com/safety" in final:
            m = re.search(r'href="(https?://(?![^"/]*(?:linkedin\.com|lnkd\.in|licdn\.com))[^"]+)"',
                          r.text or "")
            if m:
                final = html.unescape(m.group(1))
        return final
    except Exception:  # noqa: BLE001
        return url


def _regex_role(post: dict) -> dict:
    text = post.get("text") or ""
    head = post.get("poster_headline") or ""
    m = re.search(r"(?:Role|Position|Title|Opening)\s*[:\-–]\s*([^|📍🏢💼\n]{3,70}?)"
                  r"(?=\s*(?:Location|Experience|Company|📍|🏢|💼|\||$))", text, re.I)
    m = m or re.search(r"(?:hiring|looking for)\s+(?:an?\s+)?([A-Z][\w/&+ .-]{3,60}?)"
                       r"(?=\s*(?:\(|to join|in |at |\||–|-|!|\.|,))", text)
    title = m.group(1).strip(" :-–") if m else ""
    c = (re.search(r"Company\s*[:\-–]\s*([^|📍💼\n(]{2,50})", text, re.I)
         or re.search(r"\b(?:at|@)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})", head))
    company = c.group(1).strip(" .,") if c else ""
    if not company:
        emails = extract_contacts(text)["emails"]
        dom = emails[0].split("@")[1].split(".")[0] if emails else ""
        if dom and dom not in ("gmail", "yahoo", "outlook", "hotmail"):
            company = dom.capitalize()
    loc = re.search(r"Locations?\s*[:\-–]?\s*([^|💼🕒\n]{2,50}?)(?=\s*(?:Experience|Work|Employ|💼|🕒|\||$))",
                    text, re.I)
    return {"title": title, "company": company, "location": loc.group(1).strip(" 📍|") if loc else ""}


def extract_role(post: dict, post_fn=None) -> dict:
    """{title, company, location} for a post: the LLM first, regex fills gaps."""
    guess = _regex_role(post)
    try:
        prompt = ("From this LinkedIn hiring post, return ONLY JSON "
                  '{"title": "...", "company": "...", "location": "..."} — the role being '
                  "hired for, the HIRING company (not a recruiting agency if the client is "
                  'named), and location. Use "" when not stated.\n\n'
                  f"Poster headline: {post.get('poster_headline') or ''}\n"
                  f"Post: {(post.get('text') or '')[:3000]}")
        got = complete_json(prompt, temperature=0.1, post=post_fn)
        for k in guess:
            v = got.get(k)
            if isinstance(v, str) and v.strip():
                guess[k] = v.strip()
    except Exception:  # noqa: BLE001 — model down → regex guess stands
        pass
    return guess


def apply_channel(contacts: dict, resolve=resolve_link) -> tuple[str | None, str]:
    """Best apply route, best-first: form > external link (resolved) > email >
    LinkedIn job page > dm. A recruiter's email beats LinkedIn Easy Apply."""
    if contacts["forms"]:
        return resolve(contacts["forms"][0]), "form"
    resolved = [resolve(u) for u in contacts["links"]]
    forms = [u for u in resolved if any(h in u for h in _FORM_HOSTS)]
    if forms:  # a short link that lands on a form is a form
        return forms[0], "form"
    ext = [u for u in resolved if "linkedin.com" not in u]
    if ext:
        return ext[0], "external"
    if contacts["emails"]:
        return "mailto:" + contacts["emails"][0], "email"
    if resolved:
        return resolved[0], "external"
    return None, "dm"


def post_to_job(post: dict, role: dict, resolve=resolve_link) -> JobListing:
    contacts = extract_contacts(post.get("text"), post.get("url"))
    apply_url, kind = apply_channel(contacts, resolve)
    return JobListing(
        source="linkedin_post",
        title=role.get("title") or "Role from LinkedIn post",
        company=role.get("company") or post.get("poster_name") or "Unknown",
        location=role.get("location") or None,
        description=post.get("text") or "",
        job_url=post["url"],
        external_id=f"hiring_post:{post['id']}",
        apply_url=apply_url, apply_kind=kind,
    )


def text_key(text: str) -> str:
    """Near-duplicate key: same post reshared/re-fetched → same key."""
    norm = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return hashlib.sha1(norm[:400].encode()).hexdigest()


# --- Location, decided in code (the model contradicts itself on this) ---------
# ponytail: single home-country gazetteer (India) — swap/extend when the candidate relocates.
_HOME_PLACES = ("india|bengaluru|bangalore|mumbai|delhi|ncr|gurgaon|gurugram|noida|pune|hyderabad|"
                "chennai|kolkata|ahmedabad|jaipur|kochi|indore|chandigarh|navi mumbai|thane|coimbatore")
_FOREIGN = ("us|u\\.s\\.|usa|u\\.s\\.a\\.|united states|uk|u\\.k\\.|united kingdom|canada|eu|europe|germany|"
            "france|australia|brazil|latam|latin america|africa|north america|emea|singapore|uae|dubai|saudi")
_HOME = re.compile(rf"\b({_HOME_PLACES})\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|work from anywhere|worldwide)\b", re.I)
_CLOSED = [re.compile(p, re.I) for p in (
    rf"\b({_FOREIGN})[\s-]*(only|based|residents?|citizens?)(?![A-Za-z])",
    rf"\bremote\s*[\(\-–,:|]\s*({_FOREIGN})(?![A-Za-z])",
    rf"\b({_FOREIGN})\s*[|,/\-–—]\s*remote\b",
    rf"\bremote\s+(?:across|within|in|from)\s+(?:the\s+)?({_FOREIGN})(?![A-Za-z])",
    rf"\b(?:must|need to|required to|should)\s+(?:be\s+)?(?:located|based|reside|residing|living)\s+(?:in|within)\s+(?:the\s+)?({_FOREIGN})(?![A-Za-z])",
    rf"\b(?:authori[sz]ed|authori[sz]ation|eligible|right)\s+to work\s+in\s+(?:the\s+)?({_FOREIGN})(?![A-Za-z])",
    rf"\b({_FOREIGN})\s+work\s+(?:authori[sz]ation|permit|visa)\b",
    r"\bW-?2\b|\bC2C\b|\bcorp[- ]to[- ]corp\b|\b1099\b",          # US-only contracting forms
)]
_NO_SPONSOR = re.compile(r"\b(no|not offer(?:ing)?|cannot|can't|do not|don't|unable to)\s+(?:\w+\s+){0,2}(?:visa\s+)?sponsor", re.I)


def location_verdict(text: str) -> str:
    """'open' | 'closed' | 'unknown' for a candidate based in India, from the
    post text alone: another country's work-authorization/only/W2 wording closes
    it; a home city/country or unrestricted remote opens it."""
    t = text or ""
    if any(p.search(t) for p in _CLOSED):
        return "closed"
    if _HOME.search(t):
        return "open"
    if _REMOTE.search(t) and not _NO_SPONSOR.search(t):
        return "open"
    return "closed" if _NO_SPONSOR.search(t) else "unknown"


_LOC_HINT = {
    "open": "LOCATION CHECK (done in code, do not contradict): OPEN to the candidate — do not penalize location; location_open must be true.",
    "closed": "LOCATION CHECK (done in code, do not contradict): CLOSED to the candidate — say so in the reason; location_open must be false.",
    "unknown": "",
}


_JUDGE_PROMPT = """You screen LinkedIn hiring posts for one candidate. Compare the post to the
candidate's résumé and return ONLY JSON:
{{"title": "role being hired for, \"\" if none",
  "company": "the HIRING company, never the poster's own name; \"\" if not stated",
  "location_open": true or false (can the candidate take this role given its location/work mode and their authorization?),
  "fit": 0-100, "reason": "one short sentence: the main match or mismatch"}}
Score fit on: same role family (ML/AI/data science), required years vs the candidate's,
skills overlap, and whether the location/work mode is open to the candidate.
Hard caps (apply them even if the skills match perfectly):
- role family differs, or needs far more experience than the candidate has -> fit <= 30
- on-site/hybrid in a country the candidate is not authorized for, or the post
  requires that country's work authorization, and it does not offer visa
  sponsorship -> fit <= 30
Remote-worldwide and India-based roles are open to the candidate. {constraints}

Résumé:
{resume}

Post by {poster} ({headline}):
{post}
{location_hint}"""   # post-specific parts last: the long résumé prefix stays identical across calls


def judge_post(post: dict, resume_text: str, constraints: str = "", post_fn=None) -> dict:
    """{title, company, fit (0-100 or None), reason} via the LLM. On failure
    only the regex title guess comes back, with ``fit`` None."""
    out = {"title": _regex_role(post)["title"], "company": "", "fit": None, "reason": ""}
    try:
        prompt = _JUDGE_PROMPT.format(
            constraints=constraints, location_hint=_LOC_HINT[location_verdict(post.get("text"))],
            resume=resume_text[:6000], poster=post.get("poster_name") or "",
            headline=post.get("poster_headline") or "", post=(post.get("text") or "")[:3000])
        got = complete_json(prompt, temperature=0.1, post=post_fn)
        if isinstance(got.get("title"), str) and got["title"].strip():
            out["title"] = got["title"].strip()
        company = str(got.get("company") or "").strip()
        out["company"] = "" if company.lower().startswith((post.get("poster_name") or "\0").lower()) else company
        fit = got.get("fit")
        out["fit"] = max(0, min(100, int(fit))) if isinstance(fit, (int, float)) else None
        # Enforce the location cap in code: the model states the mismatch in its
        # reason yet still scores 50-75 when skills match.
        verdict = location_verdict(post.get("text"))
        closed = verdict == "closed" or (verdict == "unknown" and got.get("location_open") is False)
        if closed and out["fit"] is not None:
            out["fit"] = min(out["fit"], 30)
        out["reason"] = str(got.get("reason") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return out


_SUBJ_ASK = re.compile(
    r"Subject(?:\s*Line)?\s*[:\-–]\s*(.+?)(?=\s+(?:[#👉📌📧📩✉]|If |Please |Like |Comment|Reactions?)|\s*…|\s*$)", re.I)
_SUBJ_MENTION = re.compile(r"mention\s+[“\"'‘]([^”\"'’]{4,90})[”\"'’]", re.I)
_PLACEHOLDER = re.compile(r"[\[<(]\s*([^\]>)]{2,30}?)\s*[\]>)]")


def requested_subject(text: str) -> str | None:
    """The opening title a post asks applicants to use as the email subject
    ("Subject: …", "Subject Line: … - [Your Name] - [Notice Period]", 'mention
    “…” in your application'). Parts holding a [placeholder] (name, notice
    period, CTC…) are dropped, so only the title remains; None if absent."""
    m = _SUBJ_ASK.search(text or "") or _SUBJ_MENTION.search(text or "")
    if not m:
        return None
    parts = re.split(r"\s+[-–—|]\s+", re.sub(r"\s+", " ", m.group(1)).strip())
    keep = [p for p in parts if not _PLACEHOLDER.search(p)]
    subj = " – ".join(keep).strip(" .-–")
    return subj if 4 <= len(subj) <= 100 and "@" not in subj else None
