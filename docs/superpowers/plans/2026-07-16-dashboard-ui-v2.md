# Dashboard UI v2 (Teal-inspired warm register) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reskin the working dashboard to the approved Teal-inspired register (Poppins, cream/forest-green/gold, warm illustrated header), add an Overview panel (applications ring + pipeline bars), and extend statuses with interviewing/offer/rejected.

**Architecture:** No new backend surface except status-set + stats extension. Frontend: tokens v2 replace pastel tokens (light-only), one new `Overview.jsx` component + header SVG, restyle existing components in place. All existing functionality and tests preserved (suites: pytest 69 → 70, vitest 14 → 16+).

**Tech Stack:** unchanged + `@fontsource/poppins`.

## Global Constraints

- Register v2 per spec (2026-07-16 section) — exact hexes there are binding; **light-only: delete the dark-mode token block deliberately**.
- Statuses: `saved/applied/interviewing/offer/rejected/dismissed/NULL`; only `dismissed` is excluded from the default feed. Pipeline bars show Saved/Applied/Interviewing/Offer/Rejected.
- Scores never gate; duplicates never deleted; db.py only SQL — all unchanged and must stay true.
- No emoji/unicode glyphs; SVG only. Motion behaviors from v1 carry over (stagger/count-up/hover/reduced-motion kill).
- Weekly applications goal = constant `10` in v1 (frontend constant `WEEKLY_GOAL`).

---

### Task 1: Backend — extended statuses + pipeline stats

**Files:** Modify `src/job_dashboard/db.py`; Test `tests/test_db_dashboard.py` (extend)

**Interfaces:** `VALID_STATUSES = {"saved","applied","interviewing","offer","rejected","dismissed"}`; `dashboard_stats` returns existing keys PLUS `interviewing`, `offer`, `rejected` counts.

- [ ] Step 1 — failing tests (append to tests/test_db_dashboard.py):

```python
def test_response_statuses_are_valid_and_counted(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ids = [_seed(conn, n) for n in (1, 2, 3, 4)]
    set_job_status(conn, ids[0], "interviewing")
    set_job_status(conn, ids[1], "offer")
    set_job_status(conn, ids[2], "rejected")

    stats = dashboard_stats(conn)
    assert stats["interviewing"] == 1
    assert stats["offer"] == 1
    assert stats["rejected"] == 1
    assert stats["new"] == 1

    rows, total = query_jobs(conn)  # response statuses stay in default feed
    assert total == 4
```

- [ ] Step 2 — run `python3 -m pytest tests/test_db_dashboard.py -v` → new test FAILS (ValueError: invalid status).
- [ ] Step 3 — implement: extend `VALID_STATUSES`; in `dashboard_stats` add the three `one(...)` count lines mirroring `saved`.
- [ ] Step 4 — `python3 -m pytest` → all pass (70).
- [ ] Step 5 — commit `feat: interviewing/offer/rejected statuses with pipeline counts`.

---

### Task 2: Frontend design system v2 — Poppins + warm tokens + component reskin

**Files:** Modify `frontend/package.json` (dep), `frontend/src/styles/tokens.css` (replace), `frontend/src/styles/app.css`, `frontend/src/main.jsx` (font imports), and restyle `App.jsx`, `FilterBar.jsx`, `Feed.jsx`, `ScoreBadge.jsx`, `JobDetail.jsx`, `RefreshButton.jsx`, `DuplicatesSection.jsx`. Tests: existing vitest suite must stay green (they assert text/behavior, not colors).

- [ ] Step 1 — `cd frontend && npm install @fontsource/poppins`
- [ ] Step 2 — `main.jsx` add BEFORE the css import:

```javascript
import "@fontsource/poppins/400.css";
import "@fontsource/poppins/500.css";
import "@fontsource/poppins/600.css";
import "@fontsource/poppins/700.css";
```

- [ ] Step 3 — replace `tokens.css` entirely:

```css
:root {
  --canvas: #FAF6F0; --card: #FFFFFF; --hairline: #E8E0D4;
  --green: #1E4744; --green-mid: #3F7266; --green-soft: #6E9C8F; --sage: #9DBBB2;
  --green-tint: #E4EFEA;
  --gold: #E9B23F; --gold-ink: #4A3208;
  --peach: #F6C99F; --peach-deep: #E8A87C; --warm-band: #FBEED9;
  --warm-tint: #FBEED9; --warm-ink: #8A5A1C;
  --dupe-bg: #F5E9E4; --dupe-ink: #8A4A38; --rejected-bar: #D9B8A6;
  --ink: #26312E; --ink-soft: #7A6A52; --ink-faint: #A89B85;
  --ring-track: #EFE7DA;
  --radius-card: 14px; --radius-tag: 6px; --radius-pill: 999px;
  --font-sans: 'Poppins', 'Helvetica Neue', system-ui, sans-serif;
  --font-mono: 'SF Mono', 'JetBrains Mono', ui-monospace, monospace;
  --dur-quick: 200ms; --dur-enter: 600ms;
  --ease-pop: cubic-bezier(0.34, 1.4, 0.64, 1);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --hover-shadow: 0 2px 8px rgba(74, 58, 30, 0.08);
}
```

(No dark block — deliberate register decision.)

- [ ] Step 4 — `app.css`: `body { background: var(--canvas); color: var(--ink); }` (font-family already `var(--font-sans)`); keep keyframes + reduced-motion kill unchanged.
- [ ] Step 5 — reskin components, exact mappings (old token → new):
  - Any `--paper-dim` → `--canvas`; `--paper` → `--card`.
  - `App.jsx` header: background `var(--warm-band)`, title color `var(--green)` fontWeight 700 fontSize 20, stats color `var(--ink-soft)`; live-dot background `var(--green-soft)`. (Header illustration itself lands in Task 3.)
  - `FilterBar.jsx`: search + inactive chips/selects → white bg, `1px solid var(--hairline)` (inactive chip border `#CBBFA9`), text `var(--ink-soft)`; ACTIVE chip → `background: var(--green); color: #FFFFFF` (single active style — drop per-chip pastel `on` styles).
  - `Feed.jsx`: replace the single `<ul>` list with a column of white cards: container `display:flex; flexDirection:column; gap:10px; padding:"10px 0 0"`, each row `background: var(--card); border: 0.5px solid var(--hairline); borderRadius: var(--radius-card); padding: "14px 18px"` (keep onClick/hover/stagger/animation exactly); selected row: `border: 1.5px solid var(--green)` instead of background swap; monogram: `background: var(--green); color: var(--peach)`, borderRadius 12; title fontWeight 600 color `var(--ink)`; verdict pill → `background: var(--gold); color: var(--gold-ink)` when "Strong Fit", else `background: var(--green-tint); color: var(--green-mid)`; "Ranking…" pill `background: #F1EBE0; color: var(--ink-soft)`; status chip `background: var(--green-tint); color: var(--green-mid)`; score number color `var(--green)` fontWeight 700.
  - `ScoreBadge.jsx`: color `var(--green)`, fontWeight 700.
  - `JobDetail.jsx`: panel `background: var(--card); border: 0.5px solid var(--hairline)`; score chip `background: var(--green); color: #FFFFFF` (sublabel `#CFE0D8`); Save button `var(--green-tint)/var(--green)`; Applied `var(--gold)/var(--gold-ink)`; Dismiss `#F1EBE0/var(--ink-faint)`; Apply link `var(--green)/#FFFFFF`; Strengths card `var(--green-tint)`, title `var(--green)`, items `var(--green-mid)`; Gaps card `var(--warm-tint)`, title/items `var(--warm-ink)`; flags pills keep semantics but map pink→`--dupe-*`, peach→`--warm-*`.
  - `RefreshButton.jsx`: button `background: var(--gold); color: var(--gold-ink); fontWeight: 600`; warning banner `var(--warm-tint)/var(--warm-ink)`; error text `var(--dupe-ink)`.
  - `DuplicatesSection.jsx`: strip `background: var(--dupe-bg); color: var(--dupe-ink)`; expanded list rows `var(--card)`.
- [ ] Step 6 — `cd frontend && npx vitest run` → 14 pass unchanged (they assert text/testids, not colors). Fix any incidental breakage.
- [ ] Step 7 — commit `feat: Teal-inspired v2 design system — Poppins, cream/green/gold reskin`.

---

### Task 3: Overview panel + warm illustrated header

**Files:** Create `frontend/src/components/Overview.jsx`, `frontend/src/components/HeaderScene.jsx`; Modify `App.jsx`; Test `frontend/src/__tests__/overview.test.jsx`

**Interfaces:** `<Overview stats />` renders ring (applied vs `WEEKLY_GOAL = 10`) + pipeline bars from stats keys saved/applied/interviewing/offer/rejected. `<HeaderScene />` is the flat SVG sunset (absolute-positioned, `aria-hidden`, pointer-events none) inside the header band.

- [ ] Step 1 — failing tests:

```javascript
// frontend/src/__tests__/overview.test.jsx
import { render, screen } from "@testing-library/react";
import { test, expect } from "vitest";
import Overview from "../components/Overview.jsx";

const STATS = { total: 30, new: 10, saved: 14, applied: 7,
                interviewing: 3, offer: 1, rejected: 2, dismissed: 3, unranked: 12 };

test("renders applications ring with applied count and goal", () => {
  render(<Overview stats={STATS} />);
  expect(screen.getByText("7")).toBeDefined();
  expect(screen.getByText(/Weekly goal: 10/)).toBeDefined();
});

test("renders a pipeline bar with count per stage", () => {
  render(<Overview stats={STATS} />);
  for (const [label, n] of [["Saved", "14"], ["Applied", "7"], ["Interviewing", "3"], ["Offer", "1"], ["Rejected", "2"]]) {
    expect(screen.getByText(label)).toBeDefined();
    expect(screen.getByText(n)).toBeDefined();
  }
});
```

- [ ] Step 2 — `npx vitest run` → FAIL (module missing).
- [ ] Step 3 — implement:

```javascript
// frontend/src/components/Overview.jsx
import React from "react";

export const WEEKLY_GOAL = 10;
const STAGES = [
  { key: "saved", label: "Saved", color: "var(--sage)" },
  { key: "applied", label: "Applied", color: "var(--green-soft)" },
  { key: "interviewing", label: "Interviewing", color: "var(--green-mid)" },
  { key: "offer", label: "Offer", color: "var(--green)" },
  { key: "rejected", label: "Rejected", color: "var(--rejected-bar)" },
];
const CARD = { background: "var(--card)", border: "0.5px solid var(--hairline)", borderRadius: "var(--radius-card)", padding: "16px 18px" };

export default function Overview({ stats }) {
  if (!stats) return null;
  const applied = stats.applied ?? 0;
  const frac = Math.min(applied / WEEKLY_GOAL, 1);
  const dash = 2 * Math.PI * 38;
  const max = Math.max(...STAGES.map((s) => stats[s.key] ?? 0), 1);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 14, marginTop: 14 }}>
      <div style={{ ...CARD, textAlign: "center" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--green)", marginBottom: 8 }}>Applications</div>
        <svg width="92" height="92" viewBox="0 0 92 92" aria-hidden="true">
          <circle cx="46" cy="46" r="38" fill="none" stroke="var(--ring-track)" strokeWidth="9" />
          <circle cx="46" cy="46" r="38" fill="none" stroke="var(--green)" strokeWidth="9"
                  strokeDasharray={`${dash * frac} ${dash}`} strokeLinecap="round"
                  transform="rotate(-90 46 46)"
                  style={{ transition: "stroke-dasharray var(--dur-enter) var(--ease-out)" }} />
          <text x="46" y="52" textAnchor="middle" fontSize="24" fontWeight="700" fill="var(--green)">{applied}</text>
        </svg>
        <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 4 }}>Weekly goal: {WEEKLY_GOAL}</div>
      </div>
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--green)", marginBottom: 10 }}>Job search pipeline</div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, color: "var(--ink-soft)" }}>
          <tbody>
            {STAGES.map((s) => {
              const n = stats[s.key] ?? 0;
              return (
                <tr key={s.key}>
                  <td style={{ width: 92, padding: "3px 0", fontWeight: 500 }}>{s.label}</td>
                  <td>
                    <div style={{ height: 12, width: `${(n / max) * 100}%`, minWidth: n ? 8 : 0,
                                  background: s.color, borderRadius: 6,
                                  transition: "width var(--dur-enter) var(--ease-out)" }} />
                  </td>
                  <td style={{ width: 28, textAlign: "right", fontWeight: 600, color: "var(--green)" }}>{n}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

```javascript
// frontend/src/components/HeaderScene.jsx
import React from "react";

export default function HeaderScene() {
  return (
    <svg viewBox="0 0 800 90" preserveAspectRatio="none" aria-hidden="true"
         style={{ position: "absolute", left: 0, bottom: 0, width: "100%", height: 70, pointerEvents: "none" }}>
      <path d="M0,90 L0,55 Q120,20 240,50 T480,45 T800,55 L800,90 Z" fill="var(--peach)" />
      <path d="M0,90 L0,70 Q200,40 400,68 T800,72 L800,90 Z" fill="var(--peach-deep)" />
      <path d="M540,58 L560,18 L584,58 Z" fill="#8A7BA8" opacity="0.85" />
      <path d="M600,62 L618,30 L638,62 Z" fill="#6E5F94" opacity="0.8" />
      <circle cx="700" cy="22" r="10" fill="#FFFFFF" opacity="0.9" />
    </svg>
  );
}
```

- [ ] Step 4 — `App.jsx`: header gets `position: "relative", overflow: "hidden"`, `<HeaderScene />` first child, content wrapped in `position: relative` div; `<Overview stats={stats} />` between header and FilterBar.
- [ ] Step 5 — `npx vitest run` → 16 pass. Commit `feat: overview panel (ring + pipeline) and warm illustrated header`.

---

### Task 4: Response-status controls + live verification

**Files:** Modify `frontend/src/components/JobDetail.jsx`; extend `frontend/src/__tests__/detail.test.jsx`; rebuild dist.

- [ ] Step 1 — failing test (append):

```javascript
test("response status buttons PATCH interviewing/offer/rejected", async () => {
  const onStatusChange = vi.fn();
  render(<JobDetail id={1} onStatusChange={onStatusChange} onClose={() => {}} />);
  await waitFor(() => screen.getByText("Interviewing"));
  fireEvent.click(screen.getByText("Interviewing"));
  await waitFor(() => expect(onStatusChange).toHaveBeenCalledWith("interviewing"));
  const patch = global.fetch.mock.calls.find(([, o]) => o && o.method === "PATCH");
  expect(JSON.parse(patch[1].body)).toEqual({ status: "interviewing" });
});
```

- [ ] Step 2 — vitest → FAIL. Step 3 — implement: JobDetail button row becomes two rows: primary (Save `--green-tint/--green`, Applied `--gold/--gold-ink`, Dismiss `#F1EBE0/--ink-faint`, Apply link right) + response row labeled "Response:" with Interviewing / Offer / Rejected pills (`--green-tint/--green-mid`, Offer `--green/#FFFFFF`, Rejected `--dupe-bg/--dupe-ink`), each `setStatus("interviewing"|"offer"|"rejected")`.
- [ ] Step 4 — full suites: pytest (70) + vitest (17). `cd frontend && npm run build`.
- [ ] Step 5 — commit `feat: response status controls (interviewing/offer/rejected) in detail panel`.
- [ ] Step 6 — controller (not subagent) verifies live in browser: reload :8000, screenshot header/overview/feed/detail, mark statuses on seeded jobs to light up the pipeline.

## Not covered (unchanged from v1 spec)

Outcome archiving (/outcome), impeccable audit pass (follows this), MacTeX, real refresh.
