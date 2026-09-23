"""Execute fill decisions against a live page, and read values back for
verification. Never clicks submit — that is the run loop's decision."""
from __future__ import annotations

from ..orchestrator.mapper import FillDecision
from ..orchestrator.screen_review import _coerce_option
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


def apply_decisions(page, decisions: list[FillDecision], matcher=None) -> None:
    for d in decisions:
        if d.value is None:
            continue
        # Resolve which frame this field lives in (an embedded ATS iframe fills
        # via its own frame, not the top page); `sel` is the bare selector there.
        target, sel = frame_target(page, d.ref)
        if d.action == "combobox":
            # React "fake dropdown": open it, read the live options, map our
            # value to one (exact/word via _coerce_option, else the injected
            # llm matcher), and click it. No match -> leave blank for the human.
            try:
                try:
                    target.click(sel, timeout=_SOFT_TIMEOUT_MS)
                except Exception:
                    # Shadow DOM: CSS can't click it — fall back to a11y-tree click
                    # which pierces shadow roots (e.g. SR spl-autocomplete > spl-input).
                    if d.label:
                        target.get_by_label(d.label, exact=False).first.click(
                            timeout=_SOFT_TIMEOUT_MS)
                page.wait_for_timeout(300)      # let the listbox render
                # Scope to the listbox THIS combobox controls — reading every
                # [role=option] on the page grabs unrelated widgets (e.g. the
                # phone-country list has 247 options, one of them "Male").
                lb_id = target.get_attribute(sel, "aria-controls")
                scope = target.locator(f"#{lb_id}") if lb_id else target
                options = [t.strip() for t in
                           scope.locator("[role=option]").all_text_contents() if t.strip()]
                opt = _coerce_option(str(d.value), options)
                if opt is None and matcher is not None:
                    opt = matcher(d.label, str(d.value), options)
                if opt:
                    scope.get_by_role("option", name=opt, exact=True).first.click(
                        timeout=_SOFT_TIMEOUT_MS)
                else:
                    page.keyboard.press("Escape")
            except Exception:
                pass
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
        elif d.action == "check_group":
            # value is the intended option label; click the matching radio.
            try:
                target.get_by_label(str(d.value), exact=True).check(timeout=_SOFT_TIMEOUT_MS)
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
