"""One arbitrage for every "Apply"-looking control: an additive score decides which
candidate is the job's own CTA and which is an ad / house-promo decoy (the two
demoted shells are job 31505's ad-iframe "Apply Now" and job-board house tiles).

Pure module: element descriptors arrive as plain dicts the caller builds (the
drill in page_prep scans and enriches them), so nothing here imports Playwright.
Sorting is stable and the weights are a fixed table — shipped as-is:

  decoy evidence (positive — the higher, the more ad-like)
    +4  the owning iframe/asset URL carries an ad-network fragment
        (AD_HOST_FRAGMENTS — the one host list; page_prep's frame deny and
        perception's frame deny delegate here so there is a single table)
    +3  the owning iframe is titled "Advertisement" or named aswift_* /
        google_ads_* (AdSense slot names)
    +2  ad machinery on/next to the element: div-gpt-ad, adsbygoogle,
        google_ads_*, data-google-av-attrs, an ad-/advert/ad-slot class token
    +1  a banner-slot size token (728x90 / 300x250 / 300x600 / 970x250) in attrs
    +1  sponsored / promoted / data-ad marker in attrs or in the accessible name
    +1  house-ad vocabulary in the accessible name ("Get started", "Learn more",
        "Recommended", resume-service / cover-letter-builder copy)
    +1  the element sits in a banner-sized iframe (both dimensions < 420 px)
    +1  the element sits in a corner iframe (top-left/right band, near the top)
    +1  the element sits inside a <footer>
    +6  a candidate whose decoy evidence alone reaches the ad threshold (+2) is
        demoted below every non-ad candidate — once, and only on evidence, so a
        real apply living inside an ad unit can still win when nothing else does

  real-control evidence (negative)
    -5  a strong apply-intent phrase in the name ("Apply now", "Apply on company
        site", "I'm ready to apply", "Start application", ...)
    -2  a plain whole-word "apply" in the name, only
    -4  sticky or fixed-bottom position — the site's own persistent apply bar
        (job 31505: the real control was a fixed bottom bar while the ad iframe
        sold an identical "Apply Now" next to it)
"""
from __future__ import annotations

import re

# The ONE ad-network host-fragment list. page_prep._is_ad_frame and
# perception.is_denied_frame both read it; no module keeps its own copy.
AD_HOST_FRAGMENTS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "adservice.google", "amazon-adsystem.com", "taboola.com", "outbrain.com",
    "adnxs.com", "casalemedia.com", "criteo.com", "pubmatic.com",
    "rubiconproject.com", "smartadserver.com",
)

# AdSense slots name their frames aswift_* / google_ads_*; the title is exact.
_AD_SLOT_NAMES = ("aswift_", "google_ads_")
_AD_TITLE = "advertisement"

_AD_SIZE = re.compile(r"(?:^|\D)(?:728x90|300x250|300x600|970x250)(?:\D|$)")

# Machine markers on the element itself or its ad container (attribute tokens).
_AD_MACHINERY = re.compile(r"^(?:ad|adv|advert|adslot|adunit|ad-unit|ad-zone|advertisement)(?:[-_].*)?$")

_SOLD_TOKENS = ("sponsored", "sponsor", "promoted", "data-ad", "ad-cli")

# Copy that smells like a job board selling to the candidate, not the job (the
# design doc's seed list). Apply-intent phrases stay separate: "Get started" is
# also page_prep's low-rank apply entry for a few boards, so it only sinks, never vetoes.
_HOUSE_AD_RE = re.compile(
    r"get started|learn more|recommended|best resume|resume (?:service|writer|writing)"
    r"|ai (?:writer|cover letter)|cover letter(?: builder| tool)|start free trial"
    r"|post a (?:job|vacancy)|for employers|sponsored|promoted|featured|top rated", re.I)

# Strong enough that an ad carries the phrase in its own name — a decoy veto is
# what keeps the probe from scoring a real control below an ad by accident.
_STRONG_INTENT_RE = re.compile(
    r"apply (?:now|online|to|for|at|on)"
    r"|(?:i'?m |im )?(?:ready|here) to apply"
    r"|start (?:the |my |this |an )?(?:application|apply)"
    r"|submit (?:the |my |an |your )?application"
    r"|begin (?:the |my |a )?application"
    r"|continue to (?:the |employer|application)"
    r"|company site", re.I)

# One cheap pass per frame that holds candidates: each candidate ref answers
# where it sits (sticky band, docked bottom, footer) and whether an ad machine
# container wraps it. Just data — page_prep evaluates it, cta_arbiter never does.
SIT_REPORT_JS = r"""(refs) => {
  const out = [];
  const vh = window.innerHeight || 800;
  for (const ref of refs) {
    const e = document.querySelector(ref);
    if (!e) { out.push({ref}); continue; }
    const cs = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const anc = e.closest('ins,[id^=div-gpt-ad],[class*="ad-" i],[class*="advert" i],[data-ad-slot],[data-google-av-attrs]');
    out.push({ref: ref,
      sticky: cs.position === 'sticky' || cs.position === 'fixed',
      fixed_bottom: (cs.position === 'sticky' || cs.position === 'fixed')
                    && r.bottom >= vh * 0.7 && r.bottom <= vh + 60,
      in_footer: !!e.closest('footer,[role=contentinfo]'),
      ad_mark: anc ? `${anc.id || ''} ${typeof anc.className === 'string' ? anc.className : ''}` : ''});
  }
  return out;
}"""


def _attr_tokens(text) -> list:
    return re.findall(r"[a-z0-9_*:.\-]+", (text or "").lower())


def _machinery(tok) -> bool:
    hits = tok.startswith(("div-gpt-ad", "google_ads", "data-google-av", "adsbygoogle"))
    return bool(hits or _AD_MACHINERY.match(tok))


def _sold(tok) -> bool:
    return tok.startswith(_SOLD_TOKENS)


def _ad_evidence(candidate, page_ctx=None) -> float:
    """The decoy half of the table — what makes a candidate look like an ad."""
    c = {**candidate, **(candidate.get("ctx") or {}), **(page_ctx or {})}
    s = 0.0
    url = (c.get("frame_url") or c.get("url") or "").lower()
    if any(h in url for h in AD_HOST_FRAGMENTS):
        s += 4.0
    title = (c.get("frame_title") or "").lower().strip()
    fname = (c.get("frame_name") or "").lower().strip()
    if title == _AD_TITLE or fname.startswith(_AD_SLOT_NAMES):
        s += 3.0
    toks = _attr_tokens(c.get("attrs"))
    if any(_machinery(t) for t in toks):
        s += 2.0
    elif _AD_SIZE.search(c.get("attrs") or ""):
        s += 1.0
    name = (c.get("name") or "").strip().lower()
    if any(_sold(t) for t in toks) or re.search(r"\b(?:sponsored|promoted)\b", name):
        s += 1.0
    if _HOUSE_AD_RE.search(name):
        s += 1.0
    if c.get("small_frame"):
        s += 1.0
    if c.get("corner_frame"):
        s += 1.0
    if c.get("in_footer"):
        s += 1.0
    return s


def score(candidate, page_ctx=None) -> float:
    """The whole table: decoy evidence minus real-control evidence. Lower is more
    like the job's own control. `page_ctx` carries the sit flags the caller
    computed ({"sticky": bool, "in_footer": bool, "fixed_bottom": bool, ...}) and
    wins over the same keys embedded in the candidate itself."""
    c = {**candidate, **(candidate.get("ctx") or {}), **(page_ctx or {})}
    s = _ad_evidence(c)
    if s >= 2.0:
        s += 6.0                          # thresholded ad: sinks under every non-ad candidate
    if c.get("sticky") or c.get("fixed_bottom"):
        s -= 4.0                          # the site's own persistent bar
    name = (c.get("name") or "").strip().lower()
    if _STRONG_INTENT_RE.search(name):
        s -= 5.0
    elif re.search(r"\bapply\b", name):
        s -= 2.0
    return s


def is_ad_like(candidate, page_ctx=None) -> bool:
    """The frame/element-level deny answer: decoy evidence alone reaches the +2
    ad threshold. page_prep's frame deny delegates here; fed only url/title/frame
    name it reproduces the old inline ad test (plus the wider host list)."""
    return _ad_evidence(candidate, page_ctx) >= 2.0


def rank(candidates, allow=None) -> list:
    """Candidates sorted best first — lowest decoy score, then the phrase order
    of `allow` (page_prep passes _APPLY_ALLOW to keep today's label priority as
    the tie-breaker), then the caller's original order. An empty list stays an
    empty list: 'no candidates' must change nothing."""
    allow = [a.lower() for a in (allow or ())]

    def phrase_rank(name):
        for i, phrase in enumerate(allow):
            if phrase in name:
                return i
        return len(allow)

    items = []
    for i, cand in enumerate(candidates or ()):
        name = (cand.get("name") or "").strip().lower()
        items.append((score(cand, cand.get("ctx")), phrase_rank(name), i, cand))
    items.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in items]
