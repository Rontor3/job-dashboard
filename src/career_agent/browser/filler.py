"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

import re

from ..orchestrator.mapper import FillDecision
from ..orchestrator.screen_review import _coerce_option
from .clicks import pace
from .perception import frame_target, split_ref
from .value_shape import date_mask_refuses, read_shape, shape_value


# Any fill action can legitimately fail on a real form (an unmatched option, a
# hidden file input, or a field that turns out disabled/read-only). None may
# hang or abort the whole run — every action fails fast and leaves the field
# for the human. (A live reCAPTCHA demo has a disabled decoy input that, filled
# strictly, blocked for 30s and crashed the run — never again.)
_SOFT_TIMEOUT_MS = 4000

# SR (SmartRecruiters) uses <spl-input id="X"> web components whose internal
# <input id="X"> lives in a shadow root. CSS selectors can't pierce it.
# This JS finds the host by id, accesses its shadow root, and fills via the
# native setter + input/change events so the web component's reactive state
# updates (plain .value = x alone doesn't trigger re-render).
_SHADOW_FILL_JS = """\
(args) => {
    // SR uses deeply-nested web components, e.g.:
    //   main DOM: <spl-phone-field id="spl-form-element_5">
    //     shadowRoot: <spl-input id="spl-form-element_5">
    //       shadowRoot: <input type="tel">
    // findById: find any element with this id across all shadow roots.
    function findById(root, id) {
        const hit = root.querySelector('[id="' + id + '"]');
        if (hit) return hit;
        for (const el of root.querySelectorAll('*')) {
            if (el.shadowRoot) { const r = findById(el.shadowRoot, id); if (r) return r; }
        }
        return null;
    }
    // findInput: deep search for the actual <input>/<textarea> in any nested shadow root.
    function findInput(shadowRoot) {
        const direct = shadowRoot.querySelector('input, textarea');
        if (direct) return direct;
        for (const el of shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot) { const r = findInput(el.shadowRoot); if (r) return r; }
        }
        return null;
    }
    const host = findById(document, args.id);
    if (!host || !host.shadowRoot) return false;
    const inp = findInput(host.shadowRoot);
    if (!inp) return false;
    inp.focus();
    const proto = inp.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(inp, args.value);
    inp.dispatchEvent(new InputEvent('input', {bubbles: true, cancelable: true}));
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
}"""


_SMALL = {"of", "and", "the", "for", "in", "at", "&"}


def _type_ahead_queries(value: str) -> list[str]:
    """What to type into a type-ahead, most specific first: the whole value; its comma-separated parts from the last
    ("Santacruz (E), Mumbai" -> "Mumbai": a list of cities won't match a street-level value) and the first; the
    name as lists abbreviate it ("Indian Institute of Technology BHU" -> "IIT BHU"); its leading words. Live
    2026-10-18: Greenhouse's School search found nothing for the full university name."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    head = parts[0] if parts else value
    words = head.split()
    caps = [w for w in words if w[:1].isupper() and w.lower() not in _SMALL]
    acro = "".join(w[0] for w in caps if not w.isupper())
    short = " ".join([acro] + [w for w in caps if w.isupper()]) if len(acro) >= 2 else ""
    lead = " ".join(words[:4]) if len(words) > 4 else ""
    names = [head, short, acro if len(acro) >= 3 else "", lead]
    # a long first part is a name (a university, a company): its forms before the place after the comma
    out = [value, *names, *reversed(parts)] if len(words) >= 3 else [value, *reversed(parts), *names]
    return [q for q in dict.fromkeys(out) if q and len(q) >= 2]


# The popup a combobox opens: role=listbox, or Workday's activeListContainer (no role on some builds). Only a
# VISIBLE one counts — a closed listbox keeps its old options in the DOM.
_POPUP_SEL = "[role=listbox], [data-automation-id='activeListContainer'], :has(> [class*='dropdown-results']), .pac-container"
# Options must be visible: a closed popup (or another prompt's) keeps its rows in the DOM and would be read as choices.
def _exact(text: str):
    """Whole-text match for an option/label click: has_text=str is a substring test, so 'Male' clicked 'Female'
    (Wipro gender, live 2026-10-23)."""
    return re.compile(r"^\W*" + re.escape(str(text).strip()) + r"\W*$", re.I)     # 'Male *' yes, 'Female' no


# a pill in Workday's selectedItemList is a choice already made in ANOTHER field ('India (+91)'), never an option here
_NOT_PILL = ":not([data-automation-id=selectedItemList] *)"
# ARIA options, Workday's, and the rows of a plain type-ahead list (Lever's .dropdown-results, Google Places' .pac-item)
_OPT_SEL = ", ".join(s + ":visible" + _NOT_PILL for s in ("[role=option]", "[id*='-option-']", "[data-automation-id='promptOption']",
                                                         "[class*='dropdown-results'] > *", ".pac-item"))


def _popup(target, lb_id):
    """The listbox this combobox controls: its aria-controls target, else the first visible popup on the page, else
    the field's own scope (type-ahead options that are not in any popup)."""
    if lb_id:
        return target.locator(f'[id="{lb_id}"]')         # SuccessFactors ids hold a colon ("322:_listSelect"): no #id
    for lb in target.locator(_POPUP_SEL).all():
        # Workday's selectedItemList is a listbox of choices ALREADY made in another field (the phone code's
        # 'India (+91)'): never this field's options (Opella 2026-10-25: 'Company Portal' was never seen)
        if lb.is_visible() and (lb.get_attribute("data-automation-id") or "") != "selectedItemList":
            return lb
    return target


def _drill_to_leaf(page, scope, pre: list[str], fit, committed=lambda: False) -> None:
    """A hierarchical prompt (Workday "How Did You Hear"): the chosen option was a category, so it opened a sub-list
    instead of committing. Pick the leaf: the one that fits the answer, else its 'Other …' entry. Nothing new listed = committed."""
    leaves = []
    for _ in range(8):      # the sub-list loads in ~1 s (Walmart 2026-10-30: empty at 400 ms, so the field stayed blank)
        page.wait_for_timeout(300)
        leaves = [t.strip() for t in scope.locator(_OPT_SEL).all_text_contents() if t.strip()]
        if leaves == pre or committed():     # the list did not change / the box holds the pick: it committed
            return
        if leaves:
            break
    if not leaves:
        return
    # the category's own catch-all counts as 'Other' ('Other Job Board' under 'Job Board', Walmart 2026-10-29)
    leaf = fit(leaves) or next((t for t in leaves if _OTHER_OPTION.search(t)), None)
    if leaf is None and len(set(leaves)) == 1:
        leaf = leaves[0]          # the chosen category's only option (Workday 'Company Portal' > 'Company Career Site')
    if leaf:
        pace(page)
        scope.locator(_OPT_SEL).filter(has_text=_exact(leaf)).first.click(timeout=_SOFT_TIMEOUT_MS)


_SEARCHING = re.compile(r"^\s*(searching|loading|please enter|type to search)\b", re.I)
_OTHER_OPTION = re.compile(r"^\s*others?\b|not listed|none of the above", re.I)   # 'OTHERS' (Wipro majors)


def read_combobox_options(page, sel) -> list[str]:
    """Open a dropdown, read the options it lists, close it with Tab (Escape would close a whole modal, Wellfound)."""
    try:
        try:
            page.click(sel, timeout=_SOFT_TIMEOUT_MS)
        except Exception:               # react-select: a placeholder div covers the input; click the wrapping control
            page.locator(sel).first.locator("xpath=ancestor::div[contains(@class,'control')][1]").click(timeout=_SOFT_TIMEOUT_MS)
        page.wait_for_timeout(800)
        scope = _popup(page, page.get_attribute(sel, "aria-controls") or page.get_attribute(sel, "aria-owns"))
        opts = [t.strip() for t in scope.locator(_OPT_SEL).all_text_contents() if t.strip()]
        page.keyboard.press("Tab")
        return opts
    except Exception:
        return []


def _add_list_parts(page, target, sel, d, matcher) -> None:
    """A comma list in a picker that kept ONE of its items ('Python' of 'Python, SQL, NumPy' — Workday Skills, every run
    'did not take'): add the other items one at a time. The widget decides what it is: an item that grows the field's
    items means multi-select, keep going; one that REPLACES the item means single choice — put the first pick back."""
    from types import SimpleNamespace
    parts = [p.strip() for p in str(d.value).split(",") if p.strip()]
    if len(parts) < 2:
        return
    items = lambda: [x.strip() for x in (field_value(target, sel) or "").split(",") if x.strip()]   # noqa: E731
    first = items()
    if len(first) != 1 or first[0].lower() == str(d.value).strip().lower():
        return                                  # nothing picked, several already, or the whole value is one option
    have = first
    pick = lambda v: _pick_combobox(page, target, sel, SimpleNamespace(value=v, label=d.label, alternatives=(),  # noqa: E731
                                                                       action=""), matcher)
    # every part gets its own pick: which part the whole-list pick stood for is a guess ('Python Numpy' read as
    # Python's left 'Python' unpicked, Workday). Re-picking an item already chosen is a no-op in _pick_combobox.
    for p in parts:
        try:
            pick(p)
        except Exception:
            continue
        now = items()
        if now != have and len(now) <= len(have):
            print(f"[fill] {d.label[:40]!r} keeps one choice — back to {first[0]!r}", flush=True)
            try:
                pick(first[0])
            except Exception:
                pass
            return
        have = now


def _pick_combobox(page, target, sel, d, matcher) -> None:
    """One attempt: open the dropdown, read its live options, click the one matching d.value."""
    pace(page)
    try:
        try:
            target.click(sel, timeout=_SOFT_TIMEOUT_MS)
        except Exception:
            # Shadow DOM: CSS can't click it — fall back to a11y-tree click
            # which pierces shadow roots (e.g. SR spl-autocomplete > spl-input).
            if d.label:
                target.get_by_label(d.label, exact=False).first.click(
                    timeout=_SOFT_TIMEOUT_MS)
            else:
                # a placeholder / value div covers the input (react-select): click the control that wraps it
                target.locator(sel).first.locator("xpath=ancestor::div[contains(@class,'control')][1]").click(timeout=_SOFT_TIMEOUT_MS)
        page.wait_for_timeout(300)      # let the listbox render
        # Scope to the listbox THIS combobox controls — reading every
        # option on the page grabs unrelated widgets (e.g. the
        # phone-country list has 247 options, one of them "Male").
        lb_id = target.get_attribute(sel, "aria-controls") or target.get_attribute(sel, "aria-owns")   # SuccessFactors: aria-owns
        scope = _popup(target, lb_id)

        def _options():
            return [t.strip() for t in scope.locator(_OPT_SEL).all_text_contents() if t.strip()]

        def _fit(options, guess=True):
            opt = _coerce_option(str(d.value), options) if options else None
            for alt in (getattr(d, "alternatives", ()) or ()) if opt is None and options else ():
                opt = _coerce_option(str(alt), options)        # the answer's own stand-ins first ('Company Portal')
                if opt:
                    break
            if opt is None and options and matcher is not None and guess:
                opt = matcher(d.label, str(d.value), options)
            if opt and opt.count(",") >= 2 and "," not in str(d.value) and \
                    opt.split(",")[0].strip().lower() != str(d.value).strip().lower():
                # an address suggestion ('Goregaon (Mumbai), Goregaon West, Mumbai, …') is the answer only when it
                # starts with it: picking one rewrote Street and set City to 'Goregaon West' (Zoho, live 2026-10-31)
                opt = None
            return opt

        options = _options()
        for _ in range(8):              # a slow list (SuccessFactors draws 100 rows in ~0.8 s): wait, up to ~2.4 s more
            if options:
                break
            page.wait_for_timeout(300)
            options = _options()
        if not options:
            # text left in a search box filters its list to nothing (Workday prompt holding an earlier 'Job Board'):
            # clear it and read the full list
            try:
                if (target.locator(sel).first.input_value(timeout=1000) or "").strip():
                    target.locator(sel).first.fill("", timeout=_SOFT_TIMEOUT_MS)
                    page.wait_for_timeout(1200)
                    scope = _popup(target, lb_id)
                    options = _options()
            except Exception:
                pass
        def _searches_on_enter():
            try:
                return target.locator(sel).first.evaluate(
                    "e => e.enterKeyHint === 'search' || e.type === 'search' || e.getAttribute('role') === 'searchbox'")
            except Exception:
                return False

        opt = _fit(options)
        if opt and _searches_on_enter() and opt.strip().lower() not in {
                str(v).strip().lower() for v in (d.value, *(getattr(d, "alternatives", ()) or ()))}:
            opt = None      # a search-on-Enter box's open list is a sample or the LAST search: only an exact hit counts
        if __import__("os").getenv("CAREER_AGENT_DEBUG_PICK"):
            print(f"[pick-debug] {d.label[:40]!r} value={d.value!r} alts={getattr(d, 'alternatives', ())!r} "
                  f"options={sorted(set(options))[:8]} -> {opt!r}", flush=True)
        if opt is None:
            # a type-ahead: try each way the value may be listed, until an option actually fits (options that show up
            # but don't fit are not an answer — the next query may find it)
            def _search(q):
                nonlocal scope
                try:
                    target.locator(sel).first.fill(q, timeout=_SOFT_TIMEOUT_MS)
                except Exception:               # the search box lives in the popup (select2): replace, never append
                    page.keyboard.press("ControlOrMeta+A")
                    page.keyboard.type(q)
                found = []
                for i in range(16):             # a remote list answers in its own time ('Searching…'): up to ~8 s
                    page.wait_for_timeout(500)
                    scope = _popup(target, lb_id)   # the popup may only appear once something is typed
                    found = _options()
                    if found and not all(_SEARCHING.match(o) for o in found):
                        break
                    if i == 3:
                        # pasted text was not searched: some boxes search on key events only (Lever's location, live
                        # 2026-11-01: 'Mumbai' pasted listed nothing, typed listed 'Mumbai, Maharashtra, IND')
                        try:
                            box = target.locator(sel).first
                            box.fill("", timeout=_SOFT_TIMEOUT_MS)
                            box.press_sequentially(q, delay=40, timeout=_SOFT_TIMEOUT_MS)
                        except Exception:
                            pass
                if _searches_on_enter():
                    # a box that searches on Enter (enterkeyhint=search): what it lists before Enter is not the result —
                    # Workday Field of Study shows the first 100 A-Z ('Ceramic Engineering' never listed), and Skills
                    # 'SQL' fuzzily fit 'U-SQL' there instead of 'Structured Query Language (SQL)'
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1500)
                    scope = _popup(target, lb_id)
                    found = _options()
                return found

            # the answer's own wordings first, then its stand-ins: a search box filters the list to what it holds, so
            # 'Job Board' typed into Workday's prompt showed nothing and 'Company Portal' was never looked for (Opella)
            parts = {p.strip().lower() for p in str(d.value).split(",") if p.strip()}
            for q in [*_type_ahead_queries(str(d.value)), *(getattr(d, "alternatives", ()) or ())]:
                found = _search(q)
                opt = _fit(found)
                if opt is None and q.strip().lower() in parts:
                    # one part of the answer searched alone (the city of 'Mumbai, India'): a row NAMED by that part is
                    # it — Lever lists 'Mumbai, Maharashtra, IND', which no whole-value match accepts (Lingaro 2026-11-01)
                    opt = next((o for o in found if o.split(",")[0].strip().lower() == q.strip().lower()), None)
                if opt:
                    break
            if opt is None and getattr(d, "action", "") == "combobox":
                # not in the site's list: the list's own 'Other / Not Listed' entry is the honest pick
                # (Koch Avature: "If your school is not in the list, choose Other / Not Listed")
                for q in ("Not Listed", "Other"):
                    opt = next((o for o in _search(q) if _OTHER_OPTION.search(o)), None)
                    if opt:
                        break
        if opt and opt.strip().lower() in {x.strip().lower() for x in (field_value(target, sel) or "").split(",")}:
            return          # Enter on a lone match already chose it; a click now would toggle it back off (Workday)
        if opt:
            pace(page)
            before = _options()
            scope.locator(_OPT_SEL).filter(has_text=_exact(opt)).first.click(timeout=_SOFT_TIMEOUT_MS)
            # a sub-list leaf: the value was spent on the category, so its stand-ins first (the job's source board, Naukri
            # — 'Job Board' itself loosely fit 'Other Job Board'), then the value, then 'Other'; never a model's guess
            # (it picked 'LinkedIn', Walmart 2026-10-30)
            def _leaf(o):
                hit = next((h for a in (getattr(d, "alternatives", ()) or ()) if (h := _coerce_option(str(a), o))), None)
                return hit or _fit(o, guess=False)
            _drill_to_leaf(page, scope, before, _leaf, lambda: bool((field_value(target, sel) or "").strip()))
            try:            # leave the box: blur-only validators keep a stale 'required' flag (SuccessFactors juic _onBlur)
                page.wait_for_timeout(300)                  # the site writes the pick into the box a beat after the click
                target.locator(sel).first.evaluate("e => { e.focus(); e.blur(); }", timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        else:
            # nothing fit: the box keeps the ANSWER, never the last search word — 'Other' was left typed in Zoho's City and
            # Postal Code lookups (live 2026-10-31). A free-text lookup takes it; a strict one flags it for the refill.
            try:
                box = target.locator(sel).first
                if not box.evaluate("e => e.tagName === 'INPUT'"):      # a lookup wrapper (Zoho): its own text box
                    box = box.locator("input:not([type=hidden])").first
                if box.evaluate("e => e.tagName === 'INPUT' && !e.readOnly") and \
                        (box.input_value() or "").strip().lower() != str(d.value).strip().lower():
                    box.fill(str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
            if not target.locator(sel).first.evaluate(
                    "e => !!e.closest('[role=dialog],[aria-modal=true],[class*=modal i]')"):
                # Escape closes the listbox — but inside a modal it closes
                # the whole application (Wellfound), so leave it open there.
                page.keyboard.press("Escape")
    except Exception:
        pass


_RESUME_CONTROL = r"(upload|attach|add)\b.{0,30}\b(resume|cv|r[ée]sum[ée])\b"
_UPLOAD_CONTROL_JS = r"""(pattern) => {
  const R = new RegExp(pattern, 'i');
  const text = id => { const n = document.getElementById(id); return n ? (n.innerText || n.textContent || '') : ''; };
  const name = e => [e.getAttribute('aria-label'), (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(text).join(' '),
                     e.getAttribute('title'), e.innerText].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const acts = e => e.matches('button,a[href],[role=button],[onclick]') || (e.tabIndex >= 0 && e.hasAttribute('tabindex'));
  const hits = Array.from(document.querySelectorAll('button,a,[role=button],[onclick],[tabindex]'))
    .filter(e => vis(e) && acts(e) && R.test(name(e)));
  // something that acts on a click beats a label that merely sits in the slot
  hits.sort((a, b) => (b.matches('[onclick],[role=button],button') ? 1 : 0) - (a.matches('[onclick],[role=button],button') ? 1 : 0));
  const e = hits[0];
  if (!e) return null;
  e.setAttribute('data-upload-control', '1');
  return name(e).slice(0, 80);
}"""


_RESUME_INPUT_JS = r"""(pattern) => {
  const R = new RegExp(pattern, 'i');
  const words = e => [e.name, e.id, e.getAttribute('data-automation-id'), e.getAttribute('aria-label'), e.accept,
                      ...Array.from(e.labels || []).map(l => l.innerText),
                      (e.closest('[data-automation-id],section,fieldset,div') || {}).innerText || ''].join(' ');
  const ins = Array.from(document.querySelectorAll('input[type=file]')).filter(e => !e.disabled);
  if (!ins.length) return null;
  const NOT = /cover|letter|photo|picture|avatar|image|transcript|certificate|portfolio/i;   // other documents' slots
  const pick = ins.find(e => R.test(words(e)) && !NOT.test(e.name + ' ' + e.id + ' ' + (e.getAttribute('data-automation-id') || '')))
            || (ins.length === 1 && !NOT.test(words(ins[0])) ? ins[0] : null);
  if (!pick) return null;
  pick.setAttribute('data-resume-input', '1');
  return (pick.getAttribute('data-automation-id') || pick.name || pick.id || 'file input').slice(0, 60);
}"""


def resume_already_attached(page, pdf) -> bool:
    """The page already lists this résumé file as uploaded: a re-run must not attach it again (Pretium Workday held five
    copies of Rakshit_Singh_Resume.pdf after five runs, 2026-10-26)."""
    import os
    name = os.path.basename(str(pdf or ""))
    if not name:
        return False
    try:
        return bool(page.evaluate("n => (document.body ? document.body.innerText : '').includes(n)", name))
    except Exception:
        return False


def resume_took(page, pdf, wait_ms: int = 10000) -> bool:
    """The upload shows: the file's name is on the page, or a file input holds a file. Polls (uploads are slow)."""
    for _ in range(max(1, wait_ms // 500)):
        try:
            if resume_already_attached(page, pdf) or page.evaluate(
                    "() => [...document.querySelectorAll('input[type=file]')].some(i => i.files && i.files.length)"):
                return True
            page.wait_for_timeout(500)
        except Exception:
            return False
    return False


def _upload_shows(page, pdf) -> bool:
    if resume_took(page, pdf):
        return True
    print("[fill] résumé did not show on the page after upload", flush=True)
    return False


def upload_resume_to_input(page, pdf) -> str | None:
    """The résumé straight into a file input already on the page (hidden ones too): the one named or labelled for a
    résumé / CV, else the page's only file input. Its name, or None when there is none or it did not take."""
    try:
        name = page.evaluate(_RESUME_INPUT_JS, r"resume|r[ée]sum[ée]|\bcv\b|curriculum")
        if not name:
            n = page.locator("input[type=file]").count()
            print(f"[fill] no résumé file input to use ({n} file input(s) on the page)", flush=True)
            return None
        page.locator('[data-resume-input="1"]').first.set_input_files(pdf, timeout=20000)    # an upload can be slow
        return name
    except Exception as e:
        print(f"[fill] the résumé file input did not take the file ({type(e).__name__}: {str(e)[:120]})", flush=True)
        return None


def upload_resume_via_control(page, pdf) -> str | None:
    """A résumé slot with no file input until its control is clicked (SuccessFactors: a '+' icon that opens 'Select a
    source — Upload from Device', live Wipro 2026-10-23). Click the control, then hand the résumé to the file chooser it
    opens, else to the file input that appears, else through the dialog's 'from device' option. The control's name, or
    None when the page has no such control or nothing took the file."""
    try:
        label = page.evaluate(_UPLOAD_CONTROL_JS, _RESUME_CONTROL)
    except Exception:
        return None
    if not label:
        return None
    ctl = page.locator('[data-upload-control="1"]').first
    try:
        with page.expect_file_chooser(timeout=3000) as fc:
            pace(page)
            ctl.click(timeout=_SOFT_TIMEOUT_MS)
        fc.value.set_files(pdf)
        return label if _upload_shows(page, pdf) else None
    except Exception:
        pass
    page.wait_for_timeout(800)
    try:
        box = page.locator("input[type=file]")
        if box.count():
            box.last.set_input_files(pdf, timeout=_SOFT_TIMEOUT_MS)
            return label if _upload_shows(page, pdf) else None
        opt = page.get_by_text(re.compile(r"upload from (device|computer)|from (my )?(device|computer)|browse", re.I)).first
        with page.expect_file_chooser(timeout=4000) as fc:
            opt.click(timeout=_SOFT_TIMEOUT_MS)
        fc.value.set_files(pdf)
        return label if _upload_shows(page, pdf) else None
    except Exception:
        return None


_RADIO_TEXT_JS = """e => ((e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.getAttribute('aria-label')
                    || e.value || '').replace(/\\s+/g, ' ').trim()"""


def _pick_in_group(page, target, group: str, want: str) -> None:
    """Select `want` among the radios named `group` only — never another question's Yes/No. Matches the option's
    own text (exact, then prefix), clicks it, and confirms it is checked; a site's pre-filled pick is overwritten."""
    radios = target.locator(f'input[type=radio][name="{group}"]')
    texts = [radios.nth(i).evaluate(_RADIO_TEXT_JS).lower() for i in range(radios.count())]
    w = want.strip().lower()
    idx = next((i for i, t in enumerate(texts) if t == w), None)
    if idx is None:
        idx = next((i for i, t in enumerate(texts) if t.startswith(w) or (t and w.startswith(t))), None)
    if idx is None:
        return                                  # no such option in this question: leave it for the human
    r = radios.nth(idx)
    for go in (lambda: r.check(force=True, timeout=_SOFT_TIMEOUT_MS),
               lambda: r.locator("xpath=ancestor::label[1]").click(timeout=_SOFT_TIMEOUT_MS),
               lambda: r.dispatch_event("click")):
        try:
            pace(page)
            go()
            if r.is_checked():
                return
        except Exception:
            continue


def _pick_in_aria_group(page, target, group: str, want: str) -> None:
    """A custom ARIA radiogroup (perception stamped it data-cref-group): click `want` among ITS options only, so several
    Yes/No questions on one page each get their own answer."""
    opts = target.locator(f'[data-cref-group="{group}"]').first.locator("[role=radio], label")
    norm = lambda t: re.sub(r"\W+", " ", (t or "").lower()).strip()
    texts = [norm(opts.nth(i).inner_text()) for i in range(opts.count())]
    w = norm(want)
    idx = next((i for i, t in enumerate(texts) if t == w), None)
    if idx is None:
        idx = next((i for i, t in enumerate(texts) if t and (t.startswith(w) or w.startswith(t))), None)
    if idx is None:
        return                                  # no such option in this question: leave it for the human
    try:
        pace(page)
        opts.nth(idx).click(timeout=_SOFT_TIMEOUT_MS)
    except Exception:
        pass


def _tick_box(page, target, want: str) -> None:
    """Tick ONE checkbox by its option text (the box itself is usually hidden under a styled
    label). Same ladder as _pick_radio, checkboxes edition; confirms it ended up checked."""
    q = want.replace('"', '\\"')
    attempts = (
        lambda: target.get_by_label(want, exact=True).check(timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator(f'input[type=checkbox][value="{q}" i]').first.check(
            force=True, timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator(f'input[type=checkbox][value="{q}" i]').first.locator(
            "xpath=..").click(timeout=_SOFT_TIMEOUT_MS),
        lambda: target.get_by_role("checkbox", name=re.compile(
            r"^\s*\W*" + re.escape(want) + r"\W*$", re.I)).first.check(
            force=True, timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator("label").filter(has_text=_exact(want)).first.click(timeout=_SOFT_TIMEOUT_MS),
        # a styled button masquerading as a checkbox
        lambda: target.get_by_role("checkbox", name=re.compile(re.escape(want), re.I)).first.click(
            timeout=_SOFT_TIMEOUT_MS),
    )
    for go in attempts:
        try:
            pace(page)
            go()
            cb = target.get_by_label(want, exact=True)
            if cb.count() == 0 or cb.first.is_checked():
                return
        except Exception:
            continue


def _pick_boxes(page, target, want: str) -> None:
    """Tick every wanted option of a multi-choice group; the others stay as they are
    ("How did you hear about us?" is one question with many boxes, not nine questions)."""
    for one in [w.strip() for w in re.split(r"\s*,\s*", str(want)) if w.strip()]:
        _tick_box(page, target, one)


def _pick_radio(page, target, want: str, group: str | None = None) -> None:
    """Select the radio option labelled `want`. Styled radios hide the real <input> (opacity 0, readonly)
    and often carry the question text in their aria-label, so try, in order: label match, the input by
    its value, then clicking the visible option wrapper / text."""
    group = (group or "").replace('"', '\\"')
    if group and target.locator(f'input[type=radio][name="{group}"]').count():
        return _pick_in_group(page, target, group, want)
    if group and target.locator(f'[data-cref-group="{group}"]').count():
        return _pick_in_aria_group(page, target, group, want)
    q = want.replace('"', '\\"')
    attempts = (
        lambda: target.get_by_label(want, exact=True).check(timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator(f'input[type=radio][value="{q}" i]').first.check(force=True, timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator(f'input[type=radio][value="{q}" i]').first.locator("xpath=..").click(timeout=_SOFT_TIMEOUT_MS),
        lambda: target.get_by_role("radio", name=re.compile(r"^" + re.escape(want) + r"\b", re.I)).first.check(force=True, timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator("label").filter(has_text=_exact(want)).first.click(timeout=_SOFT_TIMEOUT_MS),
    )
    for go in attempts:
        try:
            pace(page)
            go()
            chosen = target.locator(f'input[type=radio][value="{q}" i]')
            if chosen.count() == 0 or chosen.first.is_checked():
                return
        except Exception:
            continue


_RESYNC_JS = r"""([sel, label]) => {
  const norm = t => (t || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const nameOf = e => {
    const ids = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    const lb = ids.map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    return norm(lb || e.getAttribute('aria-label') || (e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.placeholder || '');
  };
  const want = norm(label).slice(0, 25);
  if (!want) return null;
  const same = e => { const n = nameOf(e); return n && (n.startsWith(want) || want.startsWith(n.slice(0, 25))); };
  let cur = null; try { cur = document.querySelector(sel); } catch (e) {}
  if (cur && same(cur)) return null;                       // the ref still points at this field
  const hit = Array.from(document.querySelectorAll('input,textarea,select')).find(same);
  if (!hit) return null;
  document.querySelectorAll('[data-resync]').forEach(e => e.removeAttribute('data-resync'));
  hit.setAttribute('data-resync', '1');
  return '[data-resync="1"]';
}"""


def _resync_sel(target, sel: str, label: str) -> str:
    """React ids (#input-11) are positional: a field that appears above (Country adds State) shifts them, so a
    later fill would hit the wrong box. If the ref no longer carries this field's name, find it by name."""
    if not label or not sel.startswith(("#", "[")):
        return sel
    try:
        return target.evaluate(_RESYNC_JS, [sel, label]) or sel
    except Exception:
        return sel


# What a field COMMITTED, not what was typed into it. A react-select style dropdown keeps a search <input> whose value
# is the text being typed; the chosen option is rendered beside it (single/multi value). Typed text that matched no
# option is not an answer, and a real choice leaves the search box empty — so read the rendered choice there.
_VALUE_JS = r"""e => {
  // a web component (<spl-input>, <x-select>): its real box lives in its shadow root(s)
  const inner = r => { const d = r.querySelector('input:not([type=hidden]),select,textarea'); if (d) return d;
                       for (const x of r.querySelectorAll('*')) if (x.shadowRoot) { const f = inner(x.shadowRoot); if (f) return f; }
                       return null; };
  if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName) && e.shadowRoot) e = inner(e.shadowRoot) || e;
  if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName)) return null;   // a <div role=combobox>: no value to read
  if (e.tagName === 'SELECT') { const o = e.options[e.selectedIndex]; return o && o.value ? o.text.trim() : ''; }   // a placeholder option has no value
  // a Workday prompt (searchBox in a multiselectInputContainer): the search text is never the answer; the choice is a
  // selectedItem pill in the same form field
  if (e.closest('[data-automation-id="multiselectInputContainer"], [data-automation-id="searchBox"]')) {
    const f = e.closest('[data-automation-id^="formField"]') || e.parentElement;
    return [...f.querySelectorAll('[data-automation-id="selectedItem"]')].map(x => (x.textContent || '').trim()).filter(Boolean).join(', ');
  }
  if (e.tagName !== 'INPUT' || (e.getAttribute('role') || '').toLowerCase() !== 'combobox') return e.value || '';
  let c = e.parentElement;
  for (let i = 0; i < 4 && c; i++, c = c.parentElement) {
    if (!/value-?container|control|select__|-container/i.test(c.className || '')) continue;
    const chosen = [...c.querySelectorAll('[class*=singleValue],[class*=single-value],[class*=multiValue],[class*=multi-value]')];
    if (chosen.length) return chosen.map(x => (x.textContent || '').trim()).filter(Boolean).join(', ');
    if (c.querySelector('[class*=placeholder],[class*=input-container],[class*=inputContainer]')) return '';
  }
  return e.value || '';
}"""


def field_value(target, sel) -> str | None:
    """The committed value of one field, or None when it can't be read (gone, cross-frame, not a field)."""
    try:
        v = target.locator(sel).first.evaluate(_VALUE_JS, timeout=_SOFT_TIMEOUT_MS)
    except Exception:
        return None
    return None if v is None else str(v)


_VALUE_KINDS = {"text", "email", "tel", "number", "url", "textarea", "select", "combobox", "date", "datepicker"}


def has_value(page, field) -> bool:
    """The page already holds an answer in this field (the site filled it from the résumé, or a person did).
    False when it is empty OR cannot be read — an unreadable field is still asked about."""
    if field.kind not in _VALUE_KINDS:
        return False
    try:
        target, sel = frame_target(page, field.ref)
    except Exception:
        return False
    return bool((field_value(target, sel) or "").strip())


def _shows_value(target, sel) -> bool:
    v = field_value(target, sel)
    return True if v is None else bool(v.strip())    # cannot tell -> do not retry blindly

def apply_decisions(page, decisions: list[FillDecision], matcher=None) -> None:
    for d in decisions:
        if d.value is None:
            continue
        # Resolve which frame this field lives in (an embedded ATS iframe fills
        # via its own frame, not the top page); `sel` is the bare selector there.
        target, sel = frame_target(page, d.ref)
        if d.action in ("datepicker", "date_parts"):
            from .date_widgets import fill_date_parts, parse_date_value, pick_calendar
            when = parse_date_value(d.value)
            if when is None:
                continue                                    # not a date we can place: leave it for the human
            if d.action == "date_parts":
                fill_date_parts(page, d.ref, when)
            else:
                pick_calendar(page, target, _resync_sel(target, sel, d.label), when)
            continue
        if d.action in ("combobox", "fill"):
            sel = _resync_sel(target, sel, d.label)
        if d.action == "combobox":
            # React "fake dropdown": open it, read the live options, map our
            # value to one (exact/word via _coerce_option, else the injected
            # llm matcher), and click it. No match -> leave blank for the human.
            for _attempt in (1, 2):             # a dropdown that still shows nothing after the click is retried once
                _pick_combobox(page, target, sel, d, matcher)
                if _shows_value(target, sel):
                    break
                page.wait_for_timeout(500)
            _add_list_parts(page, target, sel, d, matcher)
            continue
        if d.action == "fill":
            shape = read_shape(target, sel)
            value = shape_value(d.value, shape)     # numerals-only / month / date boxes get their form
            if date_mask_refuses(d.value, shape):
                # 'Present' or a bare year into an MM/DD/YYYY box only leaves 'Invalid date' that reads as filled
                # (Wipro, live 2026-10-23): leave it blank, so the field goes to the human
                print(f"[fill] {d.label[:40]!r}: {str(d.value)[:20]!r} is not a {shape.get('placeholder')} date — left blank", flush=True)
                continue
            try:
                ml = target.get_attribute(sel, "maxlength")
                if ml and str(ml).isdigit():
                    value = value[:int(ml)]
            except Exception:
                pass
            try:
                target.fill(sel, value, timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                filled = False
                # SR web components: <spl-input id="X"> host, shadow root has <input id="X">.
                # CSS selectors can't cross shadow roots — use JS native-setter approach.
                if sel.startswith('#'):
                    try:
                        ok = target.evaluate(_SHADOW_FILL_JS, {"id": sel[1:], "value": value})
                        filled = bool(ok)
                    except Exception:
                        pass
                if not filled and d.label:
                    try:
                        target.get_by_label(d.label, exact=False).first.fill(
                            value, timeout=_SOFT_TIMEOUT_MS)
                    except Exception:
                        pass
        elif d.action == "select":
            try:
                target.select_option(sel, label=str(d.value), timeout=_SOFT_TIMEOUT_MS)
                # leave the box: blur-only validators (SuccessFactors onblur=checkforMandatory) keep a stale 'required'
                target.locator(sel).first.evaluate("e => { e.focus(); e.blur(); }", timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "upload":
            if resume_already_attached(page, d.value):
                print(f"[fill] résumé already attached ({d.label[:40]!r}) — not uploading it again", flush=True)
                continue
            try:
                target.set_input_files(sel, str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                # Hidden/styled file inputs (Taleo, iCIMS) require force=True.
                try:
                    target.locator(sel).set_input_files(str(d.value), force=True, timeout=_SOFT_TIMEOUT_MS)
                except Exception:
                    # SR: file inputs live inside <spl-dropzone> shadow roots.
                    try:
                        target.locator("spl-dropzone").locator("input[type=file]").first.set_input_files(
                            str(d.value), timeout=_SOFT_TIMEOUT_MS)
                    except Exception:
                        pass
        elif d.action == "upload_chooser":
            # a "Select file" button with no <input type=file> in the DOM: it opens the native chooser on click
            try:
                pace(page)
                with page.expect_file_chooser(timeout=5000) as fc:
                    page.get_by_role("button", name=d.label, exact=True).first.click(timeout=_SOFT_TIMEOUT_MS)
                fc.value.set_files(str(d.value))
                page.wait_for_timeout(1500)
            except Exception:
                pass
        elif d.action == "check_group":
            _pick_radio(page, target, str(d.value), d.ref[6:] if d.ref.startswith("group:") else None)
        elif d.action == "uncheck":
            # a marketing opt-in the site pre-ticked: make sure it ends up unticked (idempotent)
            try:
                pace(page)
                target.uncheck(sel, timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                try:
                    if target.is_checked(sel):
                        target.click(sel, timeout=_SOFT_TIMEOUT_MS)
                except Exception:
                    pass
        elif d.action == "check_multi":
            # a small group of choices-together: tick each named option, exactly one decision
            # for the whole question (Twilio's "How did you hear about us?" lived 9 questions long)
            _pick_boxes(page, target, str(d.value))
        elif d.action == "check":
            # tick a single checkbox (a required attestation draft). Binding is
            # the SUBMIT, which stays human-gated — see screen_review.
            try:
                target.check(sel, timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        # review: intentionally left for the human.


def revalidate_invalid(page) -> int:
    """React forms flag a field invalid on blur before the typed value commits, and leave the error up although
    the box holds the value. Retype each such field once with real keystrokes so the form re-validates."""
    n = 0
    try:
        els = page.locator('input[aria-invalid="true"], textarea[aria-invalid="true"]').all()
    except Exception:
        return 0
    for el in els:
        try:
            if el.get_attribute("role") == "combobox":
                continue
            v = el.input_value()
            if not v.strip():
                continue
            el.click(timeout=_SOFT_TIMEOUT_MS)
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.type(v, delay=20)
            page.keyboard.press("Tab")
            n += 1
        except Exception:
            continue
    return n


def read_back(page, decisions: list[FillDecision]) -> dict:
    out: dict[str, str] = {}
    for d in decisions:
        _idx, sel = split_ref(d.ref)
        if d.action in ("fill", "select", "combobox") and sel.startswith(("#", "[")):
            try:
                target, s = frame_target(page, d.ref)
            except Exception:
                continue
            v = field_value(target, s)
            if v is not None:
                out[d.ref] = v
    return out


_OPTIONAL_BOX_JS = r"""e => {
  if (!['INPUT', 'TEXTAREA'].includes(e.tagName) || e.required || e.getAttribute('aria-required') === 'true') return false;
  const lab = ((e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label') || '').trim();
  return !/[*]\s*$|\(\*\)|\brequired\b/i.test(lab);
}"""


def optional_ai_boxes(page, decisions) -> list:
    """The AI-drafted (judgment) answers sitting in OPTIONAL text boxes — a 'Message' / cover note nobody must write."""
    out = []
    for d in decisions:
        get = d.get if isinstance(d, dict) else (lambda k, _d=d: getattr(_d, k, None))
        if get("source") != "judgment" or get("kind") not in ("text", "textarea") or re.search(r"[*]\s*$", get("label") or ""):
            continue
        try:
            target, sel = frame_target(page, get("ref"))
            if target.locator(sel).first.evaluate(_OPTIONAL_BOX_JS, timeout=_SOFT_TIMEOUT_MS):
                out.append(d)
        except Exception:
            continue
    return out


def clear_boxes(page, decisions) -> bool:
    """Empty these boxes; True only when every one reads back empty."""
    for d in decisions:
        ref = d.get("ref") if isinstance(d, dict) else d.ref
        try:
            target, sel = frame_target(page, ref)
            target.locator(sel).first.fill("", timeout=_SOFT_TIMEOUT_MS)
            if (field_value(target, sel) or "").strip():
                return False
        except Exception:
            return False
    return True


def optional_empty(page, refs) -> list:
    """Of these refs, the OPTIONAL boxes that hold nothing: left empty on purpose, not a doubt (SmartRecruiters' optional
    'Website', Redica 2026-10-25). A required box, or one that cannot be read, is never in the list."""
    out = []
    for ref in refs:
        try:
            target, sel = frame_target(page, ref)
            loc = target.locator(sel).first
            if not loc.evaluate(_OPTIONAL_BOX_JS, timeout=_SOFT_TIMEOUT_MS):
                continue
            # an optional tick box left unticked (a data-processing notice: tick only when compulsory, user 2026-10-25)
            if loc.evaluate("e => ['checkbox','radio'].includes(e.type)", timeout=_SOFT_TIMEOUT_MS):
                if not loc.is_checked(timeout=_SOFT_TIMEOUT_MS):
                    out.append(ref)
            elif not (field_value(target, sel) or "").strip():
                out.append(ref)
        except Exception:
            continue
    return out
