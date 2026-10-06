"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

import re

from ..orchestrator.mapper import FillDecision
from ..orchestrator.screen_review import _coerce_option
from .clicks import pace
from .perception import frame_target, split_ref


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


def _type_ahead_queries(value: str) -> list[str]:
    """What to type into a type-ahead: the whole value, then its comma-separated parts from the last
    ("Santacruz (E), Mumbai" -> "Mumbai"), since a list of cities will not match a street-level value."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return list(dict.fromkeys([value, *reversed(parts)]))


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
        # [role=option] on the page grabs unrelated widgets (e.g. the
        # phone-country list has 247 options, one of them "Male").
        lb_id = target.get_attribute(sel, "aria-controls")
        if lb_id:
            scope = target.locator(f"#{lb_id}")
        else:
            # No linking id (e.g. Workday's type-ahead multiselect) —
            # fall back to whichever [role=listbox] is actually visible,
            # not the whole page (other closed listboxes would pollute it).
            scope = target
            for lb in target.locator("[role=listbox]").all():
                if lb.is_visible():
                    scope = lb
                    break
        # react-select renders options as divs with "-option-" ids,
        # not role=option; a type-ahead shows none until you type.
        opt_sel = "[role=option], [id*='-option-']"

        def _options():
            return [t.strip() for t in scope.locator(opt_sel).all_text_contents() if t.strip()]

        options = _options()
        if not options:
            for q in _type_ahead_queries(str(d.value)):
                try:
                    target.locator(sel).first.fill(q, timeout=_SOFT_TIMEOUT_MS)
                except Exception:
                    page.keyboard.type(q)
                page.wait_for_timeout(1500)     # remote autocomplete round-trip
                if scope is not target and not scope.is_visible():
                    scope = target
                options = _options()
                if options:
                    break
        opt = _coerce_option(str(d.value), options)
        if opt is None and matcher is not None:
            opt = matcher(d.label, str(d.value), options)
        if opt:
            pace(page)
            scope.locator(opt_sel).filter(has_text=opt).first.click(timeout=_SOFT_TIMEOUT_MS)
        elif not target.locator(sel).first.evaluate(
                "e => !!e.closest('[role=dialog],[aria-modal=true],[class*=modal i]')"):
            # Escape closes the listbox — but inside a modal it closes
            # the whole application (Wellfound), so leave it open there.
            page.keyboard.press("Escape")
    except Exception:
        pass


def _pick_radio(page, target, want: str) -> None:
    """Select the radio option labelled `want`. Styled radios hide the real <input> (opacity 0, readonly)
    and often carry the question text in their aria-label, so try, in order: label match, the input by
    its value, then clicking the visible option wrapper / text."""
    q = want.replace('"', '\\"')
    attempts = (
        lambda: target.get_by_label(want, exact=True).check(timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator(f'input[type=radio][value="{q}" i]').first.check(force=True, timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator(f'input[type=radio][value="{q}" i]').first.locator("xpath=..").click(timeout=_SOFT_TIMEOUT_MS),
        lambda: target.get_by_role("radio", name=re.compile(r"^" + re.escape(want) + r"\b", re.I)).first.check(force=True, timeout=_SOFT_TIMEOUT_MS),
        lambda: target.locator("label").filter(has_text=want).first.click(timeout=_SOFT_TIMEOUT_MS),
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


def _shows_value(target, sel) -> bool:
    try:
        return bool((target.locator(sel).first.input_value() or "").strip())
    except Exception:
        return True                         # cannot tell -> do not retry blindly

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
            continue
        if d.action == "fill":
            value = str(d.value)
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
                        ok = target.evaluate(_SHADOW_FILL_JS, {"id": sel[1:], "value": str(d.value)})
                        filled = bool(ok)
                    except Exception:
                        pass
                if not filled and d.label:
                    try:
                        target.get_by_label(d.label, exact=False).first.fill(
                            str(d.value), timeout=_SOFT_TIMEOUT_MS)
                    except Exception:
                        pass
        elif d.action == "select":
            try:
                target.select_option(sel, label=str(d.value), timeout=_SOFT_TIMEOUT_MS)
            except Exception:
                pass
        elif d.action == "upload":
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
            _pick_radio(page, target, str(d.value))
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
                out[d.ref] = target.input_value(s)
            except Exception:
                pass
    return out
