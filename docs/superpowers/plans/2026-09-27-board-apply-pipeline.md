# Board Apply Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply to jobs on the boards themselves (Naukri, LinkedIn, Indeed, iimjobs, Instahyre, Wellfound) with two data-driven drivers and the shared answer ladder, gated at the irreversible click and confirmed from the board's own response.

**Architecture:** `apply.py` routes a board URL (`boards.profiles.board_for`) to `boards.run.run_board` before the career-site drill runs. Board specifics are `board` nodes in `docs/career-agent/ats-graph.json`. Answers come from `orchestrator/answering.py`, extracted from `graph.fill_node` so both pipelines share one ladder.

**Tech Stack:** Python 3.11, Playwright (sync, CDP), pytest. Spec: `docs/superpowers/specs/2026-09-27-board-apply-pipeline-design.md`.

## Global Constraints

- Irreversible click (final button, or entry with `submits` yes/maybe) only if `do_submit` and (`autonomous` or `human.approve(card)`).
- `submitted=True` only when `signals.confirmed()` sees the board's own response / landing URL.
- Never create board accounts; logged-out → stop `logged_out`. Challenge → stop `challenge`.
- Board jobs never call `page_prep.reach_application_form`.
- Files < 500 lines. Tests: `PYTHONPATH=src python3 -m pytest tests/career_agent`; browser tests need `RUN_BROWSER_TESTS=1`.
- Commits: no Co-Authored-By trailer (project CLAUDE.md). Commit only files this plan touches (the tree has unrelated WIP).

---

### Task 1: Shared answer ladder (`orchestrator/answering.py`)

**Files:** Create `src/career_agent/orchestrator/answering.py`; Modify `src/career_agent/orchestrator/graph.py` (drop `_semantic_split`, fill_node ladder, human_gate learn loop); Test `tests/career_agent/test_board_answering.py`.

**Interfaces — Produces:** `semantic_split(fields, mem_router) -> (auto, rest)`, `answer_fields(fields, ctx: dict) -> (list[FillDecision], list[Field])`, `record_answers(fields, answers: dict, ctx: dict, events: dict|None) -> None`. `ctx` keys used: `learn`, `memory_router`, `profile`, `resume_pdf`, `judge_fn`.

- [ ] Step 1: failing test

```python
from career_agent.browser.form_model import Field
from career_agent.orchestrator.answering import answer_fields, record_answers
from career_agent.orchestrator.mapper import FillDecision


def _f(ref, label):
    return Field(ref, "text", label, True, [], None, None)


class Learn:
    def __init__(self):
        self.rec = []

    def recall(self, fields):
        hit = [f for f in fields if f.label == "Known"]
        return ([FillDecision(f.ref, f.kind, f.label, "42", "fill", "learned") for f in hit],
                [f for f in fields if f not in hit])

    def record(self, f, a):
        self.rec.append((f.label, a))


def test_ladder_order_recall_rules_judge(monkeypatch):
    import career_agent.orchestrator.screen_review as sr
    monkeypatch.setattr(sr, "map_screen", lambda fs, p, r=None: ([], list(fs)))
    judged = []

    def judge(needs):
        judged.extend(needs)
        return [FillDecision(needs[0].ref, "text", needs[0].label, "llm", "fill", "judge")], needs[1:], None

    d, needs = answer_fields([_f("a", "Known"), _f("b", "Why us"), _f("c", "Other")],
                             {"learn": Learn(), "profile": None, "judge_fn": judge})
    assert [x.value for x in d] == ["42", "llm"]
    assert [f.ref for f in needs] == ["c"]
    assert [f.ref for f in judged] == ["b", "c"]


def test_record_answers_router_skips_blank():
    calls = []

    class Router:
        def dispatch(self, op, p):
            calls.append((op, p["question"], p["answer"], p["event"]))

    record_answers([_f("a", "CTC"), _f("b", "Blank")], {"a": " 22 ", "b": "  "},
                   {"memory_router": Router()}, {"a": "edit"})
    assert calls == [("RECORD_FEEDBACK", "CTC", "22", "edit")]


def test_record_answers_falls_back_to_learn():
    learn = Learn()
    record_answers([_f("a", "CTC")], {"a": "22"}, {"learn": learn})
    assert learn.rec == [("CTC", "22")]
```

- [ ] Step 2: run → FAIL (`ModuleNotFoundError: career_agent.orchestrator.answering`).
- [ ] Step 3: implement `answering.py` (code in repo; ladder copied verbatim from `graph.fill_node`), then in `graph.py`: delete `_semantic_split`; in `fill_node` replace the recall/semantic/map_screen/judge block with `from .answering import answer_fields` / `decisions, needs = answer_fields(fillable, c)`; in `human_gate_node` replace the per-field feedback loop with `record_answers(fields, answers, c, events)`.
- [ ] Step 4: `PYTHONPATH=src python3 -m pytest tests/career_agent -q` → all pass (parity).
- [ ] Step 5: commit `refactor(agent): extract shared answer ladder into orchestrator/answering`.

### Task 2: Board profiles + data (`boards/profiles.py`, ats-graph `board` nodes)

**Files:** Create `src/career_agent/boards/__init__.py`, `src/career_agent/boards/profiles.py`; Modify `docs/career-agent/ats-graph.json` (+6 `board` nodes); Test `tests/career_agent/test_board_profiles.py`.

**Interfaces — Produces:** `load_boards(path=GRAPH) -> list[dict]` (defaults merged; `challenge` = defaults + node's), `board_for(url, boards=None) -> dict|None` (host == domain or subdomain), `json_path(obj, "jobs[0].questionnaire") -> value|None`.

- [ ] Step 1: failing test

```python
from career_agent.boards.profiles import board_for, json_path, load_boards

IDS = {"board:naukri", "board:linkedin", "board:indeed", "board:iimjobs", "board:instahyre", "board:wellfound"}


def test_graph_has_all_boards_with_required_fields():
    boards = load_boards()
    assert {b["id"] for b in boards} == IDS
    for b in boards:
        assert b["archetype"] in ("form", "chat")
        assert b["entry"]["selector"] and b["entry"]["submits"] in ("yes", "no", "maybe")
        assert b["confirm"] and b["daily_cap"] > 0


def test_board_for_matches_host_and_subdomains_only():
    assert board_for("https://www.naukri.com/job-listings-x-1")["id"] == "board:naukri"
    assert board_for("https://smartapply.indeed.com/beta/x")["id"] == "board:indeed"
    assert board_for("https://notnaukri.com/x") is None
    assert board_for("https://boards.greenhouse.io/x") is None
    assert board_for("") is None


def test_challenge_extends_defaults():
    li = board_for("https://www.linkedin.com/jobs/view/1")
    assert "verify you are human" in li["challenge"] and "checkpoint/challenge" in li["challenge"]


def test_json_path():
    o = {"jobs": [{"q": [1, 2]}], "success": True}
    assert json_path(o, "jobs[0].q") == [1, 2]
    assert json_path(o, "jobs[1].q") is None
    assert json_path(o, "success") is True
    assert json_path(None, "a") is None
```

- [ ] Step 2: run → FAIL (no module).
- [ ] Step 3: implement `profiles.py`; add the six board nodes (values from the spec table / memory `career-agent-board-probes.md`).
- [ ] Step 4: run → PASS. Step 5: commit `feat(boards): board profiles in ats-graph + loader`.

### Task 3: Pure signals + questionnaire parsing

**Files:** Create `src/career_agent/boards/signals.py`, `src/career_agent/boards/questions.py`; Tests `tests/career_agent/test_board_signals.py`, `tests/career_agent/test_board_questions.py`.

**Interfaces — Produces:** `is_challenge(board, url, text) -> bool`, `is_logged_out(board, url, text) -> bool`, `confirmed(board, responses, page_url="") -> bool` (rule keys: `capture`, `status`, `request_match`, `path`+`match`, or `page_url`); `questions.naukri(items) -> (list[Field], prefill: dict)`, `questions.PARSERS = {"naukri": naukri}`.

- [ ] Step 1: failing tests — one confirm case per board from the live traces (positive + a near-miss negative), challenge/logged-out text cases, Naukri questionnaire → Fields (ref `q:<questionId>`, `Text Box`→text, required, purpose `years_experience`, options from `answerOption`, prefill from `prefillData[0]`). (Code in repo.)
- [ ] Step 2: run → FAIL. Step 3: implement. Step 4: PASS. Step 5: commit `feat(boards): confirm/challenge signals + Naukri questionnaire parser`.

### Task 4: Drivers + `run_board`

**Files:** Create `src/career_agent/boards/drivers.py`, `src/career_agent/boards/run.py`; Test `tests/career_agent/test_board_run_browser.py` (Playwright, pages served by `page.route`, offline).

**Interfaces — Consumes:** Tasks 1–3. **Produces:** `run_board(page, board, ctx) -> dict` with keys `url, job_id, board, submitted, stopped_reason, decisions, pending_human`; ctx keys `deps, human, profile, do_submit, autonomous, job_id` (+ ladder keys). Drivers: `fields(page, board, ctx, cap)`, `prefill(board, cap)`, `put(page, board, ctx, fields, decisions)`, `next_control(page, board, ctx) -> (label, is_final)|None`, `click(page, label, ctx)`.

- [ ] Step 1: failing browser tests: one-click dry_run makes no request; one-click approved → submitted; approval declined → dry_run; form wizard with a required CTC answered by the human → submitted and the POST carries it; required answer missing → needs_human, no request; challenge text → challenge.
- [ ] Step 2: `RUN_BROWSER_TESTS=1 … test_board_run_browser.py` → FAIL. Step 3: implement. Step 4: PASS. Step 5: commit `feat(boards): form/chat drivers + gated run_board`.

### Task 5: Route board jobs in `apply.py`

**Files:** Modify `src/career_agent/apply.py` (board branch after the closed check, `_run_board` helper), `src/career_agent/reliability/rate_limiter.py` (`dry_run`, `challenge` outcomes); Test `tests/career_agent/test_board_route.py`.

- [ ] Step 1: failing test: `_run_board` returns `daily_cap` without touching the page when the limiter defers; otherwise calls `run_board` with `do_submit/autonomous/job_id` from args and records `map_outcome(stopped_reason)`.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: full suite PASS. Step 5: commit `feat(apply): route job-board URLs to the board pipeline`.
