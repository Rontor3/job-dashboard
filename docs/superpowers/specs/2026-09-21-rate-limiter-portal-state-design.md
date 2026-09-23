# Rate Limiter + Portal State — Design Spec
**Date:** 2026-09-21
**Status:** Approved

## Problem

The bulk runner has no domain awareness — it fires jobs sequentially with a flat 3-second pause regardless of how the portal is behaving. There is no per-domain daily cap, no cooldown after repeated captchas, and no pace jitter. This risks triggering bot-detection and account bans on portals that see burst traffic.

---

## Goals

- Per-domain daily cap: stop applying to a portal once it's been hit N times today
- Exponential backoff: after K captchas on a portal, cool down for increasing durations
- Human-pace jitter: randomised gap between runs (configurable via `--pace`)
- Defer-to-end: capped/cooling jobs are dequeued and retried once after the main queue
- Persistent portal state across runs: survives restarts and daily boundaries
- Both `apply.py` (single-URL) and `run_bulk_applications.py` stay updated

---

## Out of Scope

- Parallel/concurrent runs (always sequential — no locking needed)
- Per-portal login rate limiting (handled by `credential_provider.py`)
- Inbox security-email watch (separate spec)

---

## Architecture

```
src/career_agent/reliability/
    __init__.py
    portal_state.py     # durable per-domain tracking + cooldown
    rate_limiter.py     # policy: caps, pace jitter, defer decision
```

`PortalState` is the storage layer — reads/writes `~/.career_agent/portal_state.json`.
`RateLimiter` is the policy layer — wraps `PortalState`, enforces caps, adds pace.
Both the bulk runner and `apply.py` import `RateLimiter` only; `PortalState` is internal.

---

## PortalState

### Storage

`~/.career_agent/portal_state.json` — one entry per domain key.

Domain key normalisation: strip `jobs.`, `careers.`, `apply.`, `www.` prefixes so `jobs.greenhouse.io` and `greenhouse.io` map to the same key.

```json
{
  "greenhouse.io": {
    "apps_today": 3,
    "apps_today_date": "2026-09-21",
    "apps_total": 47,
    "escalation_count": 2,
    "cooldown_until": null,
    "cooldown_base_s": 3600,
    "last_run": "2026-09-21T14:32:00"
  }
}
```

### Operations

| Method | Behaviour |
|---|---|
| `get(domain)` | Returns entry; creates blank if new; resets `apps_today` if date changed |
| `record_outcome(domain, outcome)` | Updates counters; triggers cooldown on captcha |
| `is_cooling(domain)` | `True` if `cooldown_until` is in the future |
| `reset_cooldown(domain)` | Manual escape hatch — clears cooldown without editing JSON |

### Outcome mapping

`outcome` ∈ `{submitted, dry_run, captcha, blocked, error}`

| Outcome | Effect |
|---|---|
| `submitted` / `dry_run` | `apps_today += 1`, `apps_total += 1`, reset `escalation_count` and cooldown |
| `captcha` | `escalation_count += 1`, set `cooldown_until = now + cooldown_base_s * 2^escalation_count` |
| `blocked` | Same as `captcha` but also doubles `cooldown_base_s` |
| `error` | No counter change; logs only |

Cooldown series: 1h → 2h → 4h → 8h → 16h per successive captcha escalation.
A successful submit resets `escalation_count` to 0 and clears the cooldown.

File is read on every `get()` and written on every `record_outcome()`. Sequential runs make locking unnecessary.

---

## RateLimiter

### Caps (all configurable)

| Limit | Default | Env var |
|---|---|---|
| Per-domain daily cap | 5 apps/domain/day | `RATE_LIMIT_DOMAIN_DAY` |
| Hourly cap (all domains) | 10 apps/hour | `RATE_LIMIT_HOUR` |

Hourly counter is in-memory (no persistence needed — resets on process restart).

### Pace presets (`--pace` flag)

| Preset | Gap between runs |
|---|---|
| `fast` | 30–90s uniform random |
| `medium` (default) | 2–5 min uniform random |
| `slow` | 8–15 min uniform random |

### `check(domain) → str`

```
if is_cooling(domain)         → "cooldown_until:<iso_ts>"
if apps_today >= domain_cap   → "defer"
if apps_this_hour >= hour_cap → "defer"
else                          → "ok"
```

### `record(domain, outcome)`

Thin pass-through to `PortalState.record_outcome()` + increments in-memory hourly counter.

### `wait_pace(domain)`

`sleep(uniform(pace_min, pace_max))` — called by bulk runner after each successful run.

---

## Integration

### `run_bulk_applications.py`

Replace `time.sleep(3)` with `RateLimiter`. Add `--pace` argument.

```python
rl = RateLimiter(pace=args.pace)
queue = list(urls)
deferred = []

for url in queue:
    domain = rl.domain_key(url)
    decision = rl.check(domain)
    if decision != "ok":
        deferred.append(url); continue
    rec = run_one(url, idx)
    rl.record(domain, _outcome(rec["stopped_reason"]))
    rl.wait_pace(domain)

# One retry pass for deferred jobs
for url in deferred:
    domain = rl.domain_key(url)
    if rl.check(domain) == "ok":
        rec = run_one(url, idx)
        rl.record(domain, _outcome(rec["stopped_reason"]))
        rl.wait_pace(domain)
    else:
        log as skipped_rate_limit
```

### `apply.py`

One `record()` call after the graph/walk completes — keeps portal state accurate for future bulk runs. No `check()` needed (single-URL mode always runs).

```python
from .reliability.rate_limiter import RateLimiter
rl = RateLimiter()
rl.record(rl.domain_key(args.url), _outcome(stopped_reason))
```

---

## Testing

### Unit tests (no browser)

**`tests/career_agent/test_portal_state.py`**
- New domain entry is blank with today's date
- `record_outcome("captcha")` sets `cooldown_until` to ~1h from now
- Second captcha doubles the cooldown
- `record_outcome("submitted")` resets `escalation_count` and clears cooldown
- `apps_today` auto-resets when date rolls over
- `is_cooling()` returns False after `cooldown_until` passes
- All tests use a tmp file, never write to `~/.career_agent`

**`tests/career_agent/test_rate_limiter.py`**
- `check()` returns `"ok"` on a fresh domain
- `check()` returns `"defer"` when `apps_today >= domain_cap`
- `check()` returns `"cooldown_until:..."` when portal is cooling
- Hourly counter blocks at cap; resets after an hour
- `domain_key()` normalises `jobs.greenhouse.io` → `greenhouse.io`

### Live integration test

**`scripts/test_rate_limiter_live.py`**

1. Scrape 10 LinkedIn data scientist jobs with external ATS links (not Easy Apply) using the LinkedIn job search skill
2. Set `RATE_LIMIT_DOMAIN_DAY=1` so the second job from any domain triggers a defer
3. Run bulk against those 10 URLs (dry-run, no submit)
4. Assert:
   - At least one defer occurred
   - Deferred jobs appear in the retry pass log
   - `portal_state.json` has entries for all domains hit
   - Pace jitter was applied (elapsed > n_runs * pace_min)

---

## File Map

```
src/career_agent/reliability/__init__.py
src/career_agent/reliability/portal_state.py
src/career_agent/reliability/rate_limiter.py
scripts/run_bulk_applications.py         (modified)
scripts/test_rate_limiter_live.py        (new)
src/career_agent/apply.py                (modified — record call)
src/career_agent/config/settings.py      (modified — RATE_LIMIT_* vars + pace presets)
tests/career_agent/test_portal_state.py  (new)
tests/career_agent/test_rate_limiter.py  (new)
```
