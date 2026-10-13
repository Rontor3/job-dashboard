# Action-Confirm navigation (2026-10-13)

## Problem
The Python agent clicked, slept a fixed time, then read/screenshot the page. Partial loads (SPA routes, spinners,
late iframes) were read as the next step, and further clicks landed on a half-drawn page. The settle primitive
(`clicks.settle_after_click`) existed but only the advance click used it, and it judged "stable" by a body-text hash,
blind to spinners, enabled/disabled buttons and in-flight requests. `networkidle` rarely fires on SPAs.

## Design
One chokepoint, `browser/clicks.py::act(page, do_click) -> Observation`:

1. `pace` (min gap between clicks), snapshot, click **once**.
2. Settle: a watcher injected per page/application frame (`_WATCH_JS`: MutationObserver on content + clickable-state
   attributes, fetch/XHR in-flight counter). Quiet = no mutation 500ms, no request in flight (ignored after 3s of DOM
   quiet: long-polls), no visible `[aria-busy]`/progressbar/spinner, `readyState != loading`. Text-hash fallback where
   the watcher can't run. Captcha/ads/chat frames are excluded (`perception.is_denied_frame`).
3. Observation: active page (a new tab the click opened is followed), `changed`, `stable`, `modal`, and `intercepts`
   — JS dialogs (dismissed, `beforeunload` accepted), new tab, tab closed, host change, visible modal.

`wait_until_stable` uses the same watcher, so `perceive_node`, boards and `wait_for_change` get the stronger signal
without changes. Routed through `act`: `_hop` (Apply drill + Claude assist clicks), `_click_first` (consent/modal
dismiss), `_advance` (email-auth), `BrowserDeps.click` (form advance). `_hop` writes intercepts to the run trail, which
the Claude-assist prompt already includes. Claude assist screenshots only after `wait_until_stable`.

Perception stays DOM/accname-first (text before vision); vision only labels fields the DOM could not.

## Not done (YAGNI)
Per-step LLM navigator; `aria_snapshot` tree; automatic go_back on host change (moving from a company site to its
ATS is normal — the host change is reported, the caller decides). `boards/run.py` still has a fixed 2.5s after its
driver click before `wait_for_change`.

## Tests
`tests/career_agent/test_settle_act.py` (+ `fixtures/settle_act.html`, browser cases behind `RUN_BROWSER_TESTS=1`):
quiet rule, spinner + two-part delayed render, JS confirm logged, new tab followed, non-text DOM change seen in <5s
(was the full 25s timeout).
