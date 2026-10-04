# Long-answer Pipeline (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer long free-text application questions by planning the *needs* in the question, retrieving the right typed chunks per need (recipes), writing from only those chunks, and verifying — with a labelled eval set that measures retrieval before it is trusted.

**Architecture:** A new package `src/career_agent/longform/` holds a typed `KnowledgeBase` (ingredients, story slots, project stories, facts), a need planner (model call + regex fallback), recipe-based retrieval with a size budget, a writer that reuses the existing JSON reply/grounding code, and a verifier (project-leak and length checks). `judgment.py` calls it through one optional hook (`JudgmentContext.longform`), switched on by `--longform` / `CAREER_AGENT_LONGFORM=1`, with the existing drafter as fallback. The same typed tools are exposed through the existing MCP server.

**Tech Stack:** Python 3.11, sqlite3 (existing qbank), pytest, local Ollama model via `job_dashboard.letter.draft.make_default_llm`, existing `mcp` FastMCP server.

## Global Constraints

Copied from `docs/superpowers/specs/2026-10-04-knowledge-and-long-answers-design.md` and the repo's `CLAUDE.md`:

- Need set is exactly: `intro`, `one_project`, `projects_overview`, `why_company`, `why_role`, `looking_for`, `challenge`, `working_style`, `skills_list`, `other`; at most 3 needs per question.
- Typed tools: `get_facts(keys)`, `get_story(slot)`, `list_projects()`, `get_project(id, sections)`, `get_company_context(job)`.
- Project stories have sections `problem`, `built`, `tech`, `hardest`, `result`, `improve`; ingredient `source` is verbatim and never paraphrased.
- Per-company answers are never stored; long answers are always flagged for review; no auto-submit changes.
- No embeddings/similarity shortlist over projects (four projects today; revisit above ~10).
- Retrieval is evaluated separately from writing; the eval set lives in `tests/longform/eval_set.json`.
- Python, not npm: run tests with `PYTHONPATH=src python3 -m pytest <path> -q`. Test basenames must be unique across `tests/` (no `__init__.py`), so longform tests are prefixed `test_lf_`.
- Keep files under 500 lines. PII stays local: fixtures are synthetic, never the user's real ingredients.
- Commits: no `Co-Authored-By` trailer (project `CLAUDE.md`). Stage only the files named in the task.

## File Structure

| File | Responsibility |
|---|---|
| `src/career_agent/longform/__init__.py` | package marker |
| `src/career_agent/longform/kb.py` | `Chunk`, `KnowledgeBase` (the typed tools), section parsing, project ranking |
| `src/career_agent/longform/needs.py` | need set, `Plan`, regex fallback planner, model planner + validation |
| `src/career_agent/longform/recipes.py` | per-need recipes and `retrieve()` with budget |
| `src/career_agent/longform/write.py` | writer prompt and draft call |
| `src/career_agent/longform/verify.py` | project-leak check, length fit |
| `src/career_agent/longform/pipeline.py` | `answer_longform`, `prior_project`, `make_longform` |
| `src/career_agent/longform/tools.py` | `knowledge_dispatch` used by the MCP tool |
| `tests/longform/conftest.py` + `fixtures/ingredients.json` | synthetic knowledge fixture |
| `tests/longform/eval_set.json` + `test_lf_retrieval_eval.py` | labelled eval set and deterministic retrieval metrics |
| `scripts/longform_eval.py` | manual live eval (real model): plan accuracy, project-leak rate |
| Modify `src/career_agent/orchestrator/judgment.py` | optional `longform` hook |
| Modify `src/career_agent/orchestrator/qa_recorder.py` | record needs / project / chunks used |
| Modify `src/career_agent/apply.py` | `--longform` flag + env, builds the hook |
| Modify `src/career_agent/mcp_server.py` | `knowledge_access` tool |

---

### Task 1: KnowledgeBase and chunks

**Files:**
- Create: `src/career_agent/longform/__init__.py`, `src/career_agent/longform/kb.py`
- Create: `tests/longform/fixtures/ingredients.json`, `tests/longform/conftest.py`
- Test: `tests/longform/test_lf_kb.py`

**Interfaces:**
- Produces: `Chunk(id, kind, text, project_id=None, section=None)` (frozen dataclass; kinds: `card`, `project_story`, `source`, `story_slot`, `fact`, `jd`, `company`); `SECTIONS`; `tokens(text) -> set[str]`; `split_sections(text) -> dict[str, str]`; `KnowledgeBase(units, stories=None, project_stories=None, facts=None, skills=None)` with `load(conn, ingredients_path, contact=None)`, `projects() -> list[dict]`, `card(pid) -> Chunk | None`, `list_projects() -> list[Chunk]`, `get_project(pid, sections=None) -> list[Chunk]`, `get_story(slot) -> Chunk | None`, `story_slots() -> list[str]`, `get_facts(keys) -> list[Chunk]`, `skills_chunk() -> Chunk | None`, `rank_projects(text) -> list[tuple[str, int]]`.
- Chunk ids: `card:<pid>`, `project:<pid>:<section>`, `source:<pid>`, `story:<slot>`, `fact:<key>`, `skills:pool`.

- [ ] **Step 1: Create the synthetic fixture and shared conftest**

`tests/longform/fixtures/ingredients.json`:
```json
{
  "version": 1, "updated": "2026-10-04", "note": "synthetic test fixture",
  "skills_pool": ["Python", "SQL", "PyTorch", "AWS", "Docker"],
  "units": [
    {"id": "p-churn", "type": "project", "title": "Churn Prediction Service", "org": "Acme Corp",
     "problem": "customer churn was found too late", "approach": "gradient boosting models served behind a REST API",
     "tech": ["XGBoost", "FastAPI", "Docker"], "impact": ["cut churn 8%"], "tags": ["churn", "ML", "production", "API"],
     "source": "Churn Prediction Service - built gradient boosting churn models and served them via FastAPI."},
    {"id": "p-ocr", "type": "project", "title": "Document OCR Scoring", "org": "Acme Corp",
     "problem": "claim documents were reviewed by hand", "approach": "OCR plus a vision model to score document authenticity",
     "tech": ["OCR", "PyTorch", "Vision"], "impact": ["review time down 60%"], "tags": ["OCR", "vision", "documents", "LLM"],
     "source": "Document OCR Scoring - OCR and vision model scoring of claim documents."},
    {"id": "p-graph", "type": "project", "title": "Graph Entity Resolution", "org": "Acme Corp",
     "problem": "fraud rings were invisible in tabular data", "approach": "graph neural network to find communities of linked accounts",
     "tech": ["GNN", "NetworkX", "Neo4j"], "impact": ["found 40 rings"], "tags": ["graph-ML", "GNN", "fraud", "community-detection"],
     "source": "Graph Entity Resolution - GNN based community detection over account graphs."},
    {"id": "p-portfolio", "type": "project", "title": "Portfolio Optimizer", "org": "Acme Corp",
     "problem": "passive ETF allocation ignored risk", "approach": "Monte-Carlo simulation to optimise weights",
     "tech": ["Monte-Carlo", "cvxpy", "Pandas"], "impact": ["Sharpe +0.3"], "tags": ["quant-finance", "optimization", "ETF"],
     "source": "Portfolio Optimizer - Monte-Carlo driven ETF weight optimisation."},
    {"id": "role-current", "type": "work_experience", "title": "Data Scientist", "org": "Acme Corp",
     "problem": "", "approach": "", "tech": [], "impact": [], "tags": ["ML"], "source": "Data Scientist at Acme Corp."},
    {"id": "edu-btech", "type": "education", "title": "B.Tech", "org": "Some University",
     "problem": "", "approach": "", "tech": [], "impact": [], "tags": ["education"], "source": "B.Tech, Some University."}
  ]
}
```

`tests/longform/conftest.py`:
```python
import json
from pathlib import Path

import pytest

from career_agent.longform.kb import KnowledgeBase

FIXTURE = Path(__file__).parent / "fixtures" / "ingredients.json"

STORIES = {
    "story_looking_for": "I want to work on hard applied ML problems with real stakes.",
    "story_why_startups": "I like ownership and speed.",
    "story_proudest_work": "Shipping models people rely on every day.",
    "story_how_you_work": "I work in small teams with high ownership.",
    "story_problems": "Problems where data is messy and the cost of being wrong is real.",
}
PROJECT_STORIES = {
    "p-graph": "## problem\nFraud rings hid in plain sight.\n## hardest\nMaking the graph scale to millions of nodes.\n"
               "## result\nFound 40 rings in the first month.",
}
FACTS = {"current_title": "Data Scientist", "current_company": "Acme Corp", "years_experience": "3"}


@pytest.fixture
def kb():
    data = json.loads(FIXTURE.read_text())
    return KnowledgeBase(data["units"], dict(STORIES), dict(PROJECT_STORIES), dict(FACTS), data["skills_pool"])
```

- [ ] **Step 2: Write the failing tests**

`tests/longform/test_lf_kb.py`:
```python
import sqlite3

from career_agent.longform.kb import Chunk, KnowledgeBase, split_sections
from career_agent.memory import qbank
from tests.longform.conftest import FIXTURE  # noqa: F401  (path only)


def test_split_sections_known_headings_and_unknown_fall_into_body():
    got = split_sections("intro text\n## problem\nA\n## Hardest\nB\n## misc\nC")
    assert got == {"body": "intro text\nC", "problem": "A", "hardest": "B"}
    assert split_sections("") == {}


def test_projects_are_only_project_units(kb):
    assert [u["id"] for u in kb.projects()] == ["p-churn", "p-ocr", "p-graph", "p-portfolio"]


def test_cards_are_one_chunk_per_project(kb):
    cards = kb.list_projects()
    assert [c.id for c in cards] == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]
    assert all(c.kind == "card" and len(c.text) <= 400 for c in cards)
    assert "Neo4j" in kb.card("p-graph").text and kb.card("nope") is None


def test_get_project_returns_story_sections_then_verbatim_source(kb):
    ids = [c.id for c in kb.get_project("p-graph")]
    assert ids == ["project:p-graph:problem", "project:p-graph:hardest", "project:p-graph:result", "source:p-graph"]
    assert [c.id for c in kb.get_project("p-graph", ("hardest",))] == ["project:p-graph:hardest", "source:p-graph"]
    assert [c.id for c in kb.get_project("p-ocr")] == ["source:p-ocr"]          # no story written yet
    assert kb.get_project("nope") == []


def test_stories_and_facts_and_skills(kb):
    assert kb.get_story("story_looking_for").id == "story:story_looking_for"
    assert kb.get_story("missing") is None
    assert "story_how_you_work" in kb.story_slots()
    assert [c.id for c in kb.get_facts(("current_title", "nope"))] == ["fact:current_title"]
    assert kb.skills_chunk().text == "Skills: Python, SQL, PyTorch, AWS, Docker"


def test_rank_projects_by_overlap_with_the_text(kb):
    assert kb.rank_projects("graph neural networks to detect fraud rings")[0][0] == "p-graph"
    assert kb.rank_projects("OCR and document vision")[0][0] == "p-ocr"
    assert kb.rank_projects("unrelated words")[0][1] == 0


def test_load_reads_story_slots_and_project_stories_from_the_bank():
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)
    for eid, ans in (("story_looking_for", "ML at scale"), ("story_project_p-graph", "## result\nFound rings"),
                     ("story_empty", "")):
        qbank.upsert_entry(conn, {"id": eid, "question": eid, "topic": "story", "atype": "text"})
        if ans:
            qbank.set_answer(conn, eid, ans)
    from tests.longform.conftest import FIXTURE as path
    loaded = KnowledgeBase.load(conn, path, {"years_experience": "3"})
    assert loaded.story_slots() == ["story_looking_for"]
    assert [c.id for c in loaded.get_project("p-graph")][0] == "project:p-graph:result"
    assert [c.id for c in loaded.get_facts(("years_experience",))] == ["fact:years_experience"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_kb.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'career_agent.longform'`. (If importing `tests.longform.conftest` fails because `tests` is not a package, replace both `from tests.longform.conftest import ...` lines with `FIXTURE = Path(__file__).parent / "fixtures" / "ingredients.json"` plus `from pathlib import Path`.)

- [ ] **Step 4: Write the implementation**

`src/career_agent/longform/__init__.py`: empty file.

`src/career_agent/longform/kb.py`:
```python
"""Typed knowledge for long answers: résumé units, the candidate's own stories, facts. Every method here is
one of the retrieval tools; chunks carry a kind and an id so a draft can be traced to what it was built from."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SECTIONS = ("problem", "built", "tech", "hardest", "result", "improve")
_HEADING = re.compile(r"^\s*##\s*([A-Za-z ]+?)\s*$", re.M)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on", "at", "is", "are", "was", "were",
         "it", "that", "this", "you", "your", "i", "my", "we", "our", "how", "what", "why", "do", "does", "did",
         "have", "has"}
_CARD_MAX = 400


@dataclass(frozen=True)
class Chunk:
    id: str                 # card:<pid> | project:<pid>:<section> | source:<pid> | story:<slot> | fact:<key> | ...
    kind: str               # card | project_story | source | story_slot | fact | jd | company
    text: str
    project_id: str | None = None
    section: str | None = None


def tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower())) - _STOP


def split_sections(text: str) -> dict[str, str]:
    """'## problem ...' blocks keyed by section; text before the first heading, and unknown headings, go to 'body'."""
    parts = _HEADING.split(text or "")
    out: dict[str, str] = {}
    if parts[0].strip():
        out["body"] = parts[0].strip()
    for name, body in zip(parts[1::2], parts[2::2]):
        key = name.strip().lower()
        key = key if key in SECTIONS else "body"
        if body.strip():
            out[key] = (out.get(key, "") + "\n" + body.strip()).strip()
    return out


class KnowledgeBase:
    def __init__(self, units, stories=None, project_stories=None, facts=None, skills=None):
        self.units = {u["id"]: u for u in units}
        self._stories = stories or {}
        self._project_stories = project_stories or {}
        self._facts = facts or {}
        self.skills = skills or []

    @classmethod
    def load(cls, conn, ingredients_path, contact=None) -> "KnowledgeBase":
        data = json.loads(Path(ingredients_path).read_text())
        stories, project_stories = {}, {}
        for eid, ans in conn.execute("SELECT id, answer FROM qbank_entry WHERE topic='story' AND status='active' "
                                     "AND TRIM(COALESCE(answer, '')) != ''"):
            if eid.startswith("story_project_"):
                project_stories[eid[len("story_project_"):]] = ans
            else:
                stories[eid] = ans
        return cls(data.get("units", []), stories, project_stories, dict(contact or {}), data.get("skills_pool", []))

    # -- tools -----------------------------------------------------------------------------------
    def projects(self) -> list[dict]:
        return [u for u in self.units.values() if u.get("type") == "project"]

    def card(self, pid) -> Chunk | None:
        u = self.units.get(pid)
        if u is None:
            return None
        text = (f"{u.get('title', '')} ({u.get('org', '')}): {u.get('problem', '')}. Built: {u.get('approach', '')}. "
                f"Tech: {', '.join(u.get('tech', []))}. Impact: {'; '.join(u.get('impact', []))}")
        return Chunk(f"card:{pid}", "card", text[:_CARD_MAX], pid)

    def list_projects(self) -> list[Chunk]:
        return [self.card(u["id"]) for u in self.projects()]

    def get_project(self, pid, sections=None) -> list[Chunk]:
        u = self.units.get(pid)
        if u is None:
            return []
        story = split_sections(self._project_stories.get(pid, ""))
        out = [Chunk(f"project:{pid}:{name}", "project_story", story[name], pid, name)
               for name in (sections or (*SECTIONS, "body")) if name in story]
        if u.get("source"):
            out.append(Chunk(f"source:{pid}", "source", u["source"], pid))
        return out

    def story_slots(self) -> list[str]:
        return list(self._stories)

    def get_story(self, slot) -> Chunk | None:
        text = self._stories.get(slot, "")
        return Chunk(f"story:{slot}", "story_slot", text) if text.strip() else None

    def get_facts(self, keys) -> list[Chunk]:
        return [Chunk(f"fact:{k}", "fact", f"{k}: {self._facts[k]}") for k in keys if str(self._facts.get(k, "")).strip()]

    def skills_chunk(self) -> Chunk | None:
        return Chunk("skills:pool", "fact", "Skills: " + ", ".join(self.skills)) if self.skills else None

    def rank_projects(self, text: str) -> list[tuple[str, int]]:
        want = tokens(text)
        scored = []
        for u in self.projects():
            have = tokens(" ".join([u.get("title", ""), u.get("problem", ""), u.get("approach", ""),
                                    " ".join(u.get("tech", [])), " ".join(u.get("tags", []))]))
            scored.append((u["id"], len(want & have)))
        return sorted(scored, key=lambda t: (-t[1], t[0]))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_kb.py -q`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/longform/__init__.py src/career_agent/longform/kb.py tests/longform/conftest.py tests/longform/fixtures/ingredients.json tests/longform/test_lf_kb.py
git commit -m "feat(longform): typed knowledge base — chunks, project cards/stories, ranking"
```

---

### Task 2: Need planner

**Files:**
- Create: `src/career_agent/longform/needs.py`
- Test: `tests/longform/test_lf_needs.py`

**Interfaces:**
- Consumes: `KnowledgeBase` (`units`, `projects()`, `list_projects()`, `rank_projects()`) from Task 1.
- Produces: `NEEDS: tuple[str, ...]`, `PROJECT_NEEDS: set[str]`, `MAX_NEEDS = 3`, `Plan(needs: tuple[str, ...], project_id: str | None = None, reason: str = "", source: str = "model")` (frozen), `heuristic_needs(question) -> tuple[str, ...]`, `build_plan_prompt(question, jd, kb) -> str`, `parse_plan(reply, project_ids) -> Plan | None`, `plan_needs(question, jd, kb, llm=None, prior_project=None) -> Plan`.

- [ ] **Step 1: Write the failing tests**

`tests/longform/test_lf_needs.py`:
```python
import json

from career_agent.longform.needs import (NEEDS, Plan, build_plan_prompt, heuristic_needs, parse_plan, plan_needs)

IDS = {"p-churn", "p-ocr", "p-graph", "p-portfolio"}


def test_heuristics_map_common_questions():
    h = heuristic_needs
    assert h("Tell me about yourself") == ("intro",)
    assert h("Describe a project you are proud of") == ("one_project",)
    assert h("What interests you about working for this company?") == ("why_company",)
    assert h("Why do you want to join us?") == ("why_company",)
    assert h("What are you looking for in your next role?") == ("looking_for",)
    assert h("Please list down your skillset") == ("skills_list",)
    assert h("List your key projects") == ("projects_overview",)
    assert h("Anything else we should know?") == ("other",)


def test_a_mixed_question_yields_several_needs_in_order_capped_at_three():
    got = heuristic_needs("Share something about you, what you're looking for, or why Acme interests you.")
    assert got == ("intro", "why_company", "looking_for")
    assert len(heuristic_needs("yourself, proud of, why join us, looking for, skillset")) == 3


def test_parse_plan_validates_needs_and_project():
    ok = parse_plan(json.dumps({"needs": ["intro", "bogus", "why_company"], "project_id": "p-ocr", "reason": "r"}), IDS)
    assert ok == Plan(("intro", "why_company"), "p-ocr", "r", "model")
    assert parse_plan(json.dumps({"needs": ["bogus"]}), IDS) is None
    assert parse_plan("not json", IDS) is None
    assert parse_plan(json.dumps({"needs": ["intro"], "project_id": "edu-btech"}), IDS).project_id is None
    assert len(parse_plan(json.dumps({"needs": list(NEEDS)}), IDS).needs) == 3


def test_prompt_lists_needs_and_project_cards_but_no_stories(kb):
    p = build_plan_prompt("Tell me about a project", "We detect fraud rings with graph ML", kb)
    assert "one_project" in p and "p-graph" in p and "Graph Entity Resolution" in p
    assert "high ownership" not in p                                  # stories are not needed to plan


def test_model_plan_is_used_and_project_defaults_by_jd_when_a_need_requires_one(kb):
    llm = lambda p: json.dumps({"needs": ["one_project"], "project_id": None})
    plan = plan_needs("Describe a project you are proud of", "graph neural networks to detect fraud rings", kb, llm)
    assert plan.needs == ("one_project",) and plan.project_id == "p-graph" and plan.source == "model"


def test_falls_back_to_heuristics_when_the_model_fails_or_is_absent(kb):
    def boom(p): raise TimeoutError
    for llm in (None, boom, lambda p: "garbage"):
        plan = plan_needs("Tell me about yourself", "jd", kb, llm)
        assert plan.needs == ("intro",) and plan.source == "heuristic" and plan.project_id is None


def test_a_prior_choice_wins_and_is_marked(kb):
    llm = lambda p: json.dumps({"needs": ["one_project"], "project_id": "p-churn"})
    plan = plan_needs("Describe a project", "jd", kb, llm, prior_project="p-ocr")
    assert plan.project_id == "p-ocr" and plan.source == "prior"
    assert plan_needs("Describe a project", "jd", kb, llm, prior_project="nope").project_id == "p-churn"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_needs.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'career_agent.longform.needs'`

- [ ] **Step 3: Write the implementation**

`src/career_agent/longform/needs.py`:
```python
"""What does a long-answer question need? One model call lists the needs (from a fixed set) and picks a project;
a regex planner is the fallback and the eval baseline. Output is always validated against the allowed ids."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

NEEDS = ("intro", "one_project", "projects_overview", "why_company", "why_role", "looking_for", "challenge",
         "working_style", "skills_list", "other")
PROJECT_NEEDS = {"one_project", "challenge", "why_company", "why_role"}
MAX_NEEDS = 3


@dataclass(frozen=True)
class Plan:
    needs: tuple[str, ...]
    project_id: str | None = None
    reason: str = ""
    source: str = "model"              # model | heuristic | prior


# order matters: it is the order needs are reported in
_HEURISTICS = [
    ("intro", r"about yourself|about you\b|introduce yourself|tell us about you"),
    ("one_project", r"proud of|proudest|most proud|(a|one|your|favou?rite|challenging) project|project (you|that you)"),
    ("projects_overview", r"(list|key|main|notable) projects"),
    ("why_company", r"why (do you want to )?(join|work (at|for|with)|us\b|this company)|interests? you|"
                    r"interested in (us|this company|working)|what interests"),
    ("why_role", r"why (this|the) (role|position|job)"),
    ("looking_for", r"looking for|next role|career goals?"),
    ("challenge", r"challeng|difficult|problem you (solved|faced)|hardest"),
    ("working_style", r"how do you (like to )?work|working style|ownership"),
    ("skills_list", r"skill ?set|list (down )?(your )?skills|technical skills|tech stack"),
]
_COMPILED = [(need, re.compile(rx, re.I)) for need, rx in _HEURISTICS]


def heuristic_needs(question: str) -> tuple[str, ...]:
    found = [need for need, rx in _COMPILED if rx.search(question or "")]
    return tuple(found[:MAX_NEEDS]) or ("other",)


def build_plan_prompt(question, jd, kb) -> str:
    projects = "\n".join(f"- {c.project_id}: {c.text}" for c in kb.list_projects())
    return (
        "A job application asks one free-text question. Decide what material is needed to answer it.\n\n"
        f'QUESTION: "{question}"\n\nJOB (excerpt): {(jd or "")[:1200]}\n\nCANDIDATE PROJECTS:\n{projects}\n\n'
        f"Allowed needs (choose 1-{MAX_NEEDS}): {', '.join(NEEDS)}.\n"
        "intro = about the candidate; one_project = a specific project in depth; projects_overview = several projects; "
        "why_company / why_role = fit with this company / role; looking_for = goals; challenge = a hard problem solved; "
        "working_style = how they work; skills_list = skills; other = anything else.\n"
        "If a need uses a project, give the id of the ONE project that best fits the job and question.\n"
        'Reply with ONLY a JSON object: {"needs": ["..."], "project_id": "<id or null>", "reason": "<one short line>"}'
    )


def parse_plan(reply, project_ids) -> Plan | None:
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S), flags=re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("needs"), list):
        return None
    needs = tuple(n for n in d["needs"] if n in NEEDS)[:MAX_NEEDS]
    if not needs:
        return None
    pid = d.get("project_id") if d.get("project_id") in project_ids else None
    reason = d.get("reason") if isinstance(d.get("reason"), str) else ""
    return Plan(needs, pid, reason, "model")


def plan_needs(question, jd, kb, llm=None, prior_project=None) -> Plan:
    ids = {u["id"] for u in kb.projects()}
    plan = None
    if llm is not None:
        try:
            plan = parse_plan(llm(build_plan_prompt(question, jd, kb)), ids)
        except Exception:
            plan = None
    if plan is None:
        plan = Plan(heuristic_needs(question), None, "", "heuristic")
    pid, source = plan.project_id, plan.source
    if prior_project in ids:
        pid, source = prior_project, "prior"
    if pid is None and set(plan.needs) & PROJECT_NEEDS:
        ranked = kb.rank_projects(f"{question} {jd}")
        pid = ranked[0][0] if ranked else None
    return Plan(plan.needs, pid, plan.reason, source)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_needs.py -q`
Expected: PASS (7 passed). If `test_a_mixed_question…` fails on the 3-need cap example, check that `heuristic_needs` slices to `MAX_NEEDS` after collecting all matches.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/longform/needs.py tests/longform/test_lf_needs.py
git commit -m "feat(longform): need planner — model plan with validation, regex fallback"
```

---

### Task 3: Recipes and retrieval

**Files:**
- Create: `src/career_agent/longform/recipes.py`
- Test: `tests/longform/test_lf_recipes.py`

**Interfaces:**
- Consumes: `Chunk`, `KnowledgeBase` (Task 1), `Plan`, `NEEDS` (Task 2).
- Produces: `Ctx(project_id, question, jd_text, company_text)` dataclass; `RECIPES: dict[str, Callable[[KnowledgeBase, Ctx], list[Chunk]]]` with one entry per need in `NEEDS`; `retrieve(plan, kb, *, question="", jd_text="", company_text="", budget_chars=6000) -> list[Chunk]` (deduplicated by chunk id, in recipe order, trimmed to the budget but never below one chunk).

- [ ] **Step 1: Write the failing tests**

`tests/longform/test_lf_recipes.py`:
```python
from career_agent.longform.needs import NEEDS, Plan
from career_agent.longform.recipes import RECIPES, retrieve


def ids(chunks):
    return [c.id for c in chunks]


def test_every_need_has_a_recipe():
    assert set(RECIPES) == set(NEEDS)


def test_intro_has_own_words_facts_and_a_card_for_every_project(kb):
    got = ids(retrieve(Plan(("intro",)), kb))
    assert {"story:story_how_you_work", "story:story_looking_for", "fact:current_title"} <= set(got)
    assert [i for i in got if i.startswith("card:")] == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]
    assert not any(i.startswith(("project:", "source:")) for i in got)


def test_one_project_is_that_project_only(kb):
    got = ids(retrieve(Plan(("one_project",), "p-graph"), kb))
    assert got == ["project:p-graph:problem", "project:p-graph:hardest", "project:p-graph:result", "source:p-graph"]


def test_challenge_pulls_only_hardest_and_result(kb):
    assert ids(retrieve(Plan(("challenge",), "p-graph"), kb)) == [
        "project:p-graph:hardest", "project:p-graph:result", "source:p-graph"]


def test_why_company_mixes_goals_company_the_project_and_one_more_card(kb):
    got = ids(retrieve(Plan(("why_company",), "p-graph"), kb, question="q", jd_text="jd", company_text="Acme fights fraud"))
    assert got[:2] == ["story:story_looking_for", "story:story_why_startups"]
    assert "company" in got and "project:p-graph:result" in got
    cards = [i for i in got if i.startswith("card:")]
    assert len(cards) == 1 and cards != ["card:p-graph"]                    # a second project, as a one-liner only


def test_why_company_without_company_facts_falls_back_to_the_job_description(kb):
    got = ids(retrieve(Plan(("why_company",), "p-graph"), kb, jd_text="We build fraud tools"))
    assert "company" not in got and "jd" in got


def test_projects_overview_is_cards_only(kb):
    assert ids(retrieve(Plan(("projects_overview",)), kb)) == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]


def test_simple_needs(kb):
    assert ids(retrieve(Plan(("looking_for",)), kb)) == ["story:story_looking_for", "story:story_problems"]
    assert ids(retrieve(Plan(("working_style",)), kb)) == ["story:story_how_you_work"]
    assert ids(retrieve(Plan(("skills_list",)), kb)) == ["skills:pool"]


def test_other_is_small_and_relevant(kb):
    got = retrieve(Plan(("other",)), kb, question="graph fraud detection experience")
    assert len(got) <= 4 and "card:p-graph" in ids(got)


def test_several_needs_dedupe_and_keep_order(kb):
    got = ids(retrieve(Plan(("intro", "looking_for")), kb))
    assert len(got) == len(set(got)) and got[0] == "story:story_how_you_work"


def test_budget_drops_from_the_end_but_keeps_the_first_chunk(kb):
    full = retrieve(Plan(("intro",)), kb)
    small = retrieve(Plan(("intro",)), kb, budget_chars=200)
    assert small[0].id == full[0].id and 1 <= len(small) < len(full)
    assert retrieve(Plan(("intro",)), kb, budget_chars=1)[0].id == full[0].id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_recipes.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'career_agent.longform.recipes'`

- [ ] **Step 3: Write the implementation**

`src/career_agent/longform/recipes.py`:
```python
"""Recipes: which chunks each need pulls, in what order. A recipe is plain code on purpose — the mix is reviewable
('about yourself' always includes every project card) and testable, unlike a similarity score."""
from __future__ import annotations

from dataclasses import dataclass

from .kb import Chunk, KnowledgeBase, tokens

_JD_MAX = 1500
_FACT_KEYS = ("current_title", "current_company", "years_experience")


@dataclass
class Ctx:
    project_id: str | None = None
    question: str = ""
    jd_text: str = ""
    company_text: str = ""


def _stories(kb, *slots) -> list[Chunk]:
    return [c for c in (kb.get_story(s) for s in slots) if c]


def _project(kb, ctx, sections=None) -> list[Chunk]:
    return kb.get_project(ctx.project_id, sections) if ctx.project_id else []


def _company(ctx) -> list[Chunk]:
    if ctx.company_text.strip():
        return [Chunk("company", "company", ctx.company_text.strip())]
    return [Chunk("jd", "jd", ctx.jd_text.strip()[:_JD_MAX])] if ctx.jd_text.strip() else []


def _second_card(kb, ctx) -> list[Chunk]:
    ranked = [pid for pid, _ in kb.rank_projects(f"{ctx.question} {ctx.jd_text}") if pid != ctx.project_id]
    card = kb.card(ranked[0]) if ranked else None
    return [card] if card else []


def _intro(kb, ctx):
    return _stories(kb, "story_how_you_work", "story_looking_for") + kb.get_facts(_FACT_KEYS) + kb.list_projects()


def _why_company(kb, ctx):
    return (_stories(kb, "story_looking_for", "story_why_startups") + _company(ctx)
            + _project(kb, ctx) + _second_card(kb, ctx))


def _why_role(kb, ctx):
    jd = [Chunk("jd", "jd", ctx.jd_text.strip()[:_JD_MAX])] if ctx.jd_text.strip() else []
    return _stories(kb, "story_looking_for", "story_problems") + jd + _project(kb, ctx, ("problem", "result"))


def _skills(kb, ctx):
    chunk = kb.skills_chunk()
    return [chunk] if chunk else []


def _other(kb, ctx):
    want = tokens(ctx.question)
    ranked = [pid for pid, score in kb.rank_projects(ctx.question) if score > 0][:2]
    slots = sorted(kb.story_slots(), key=lambda s: -len(want & tokens(kb.get_story(s).text if kb.get_story(s) else "")))
    return [kb.card(pid) for pid in ranked] + _stories(kb, *slots[:2])


RECIPES = {
    "intro": _intro,
    "one_project": lambda kb, ctx: _project(kb, ctx),
    "projects_overview": lambda kb, ctx: kb.list_projects(),
    "why_company": _why_company,
    "why_role": _why_role,
    "looking_for": lambda kb, ctx: _stories(kb, "story_looking_for", "story_problems"),
    "challenge": lambda kb, ctx: _project(kb, ctx, ("hardest", "result")),
    "working_style": lambda kb, ctx: _stories(kb, "story_how_you_work"),
    "skills_list": _skills,
    "other": _other,
}


def _within_budget(chunks: list[Chunk], budget: int) -> list[Chunk]:
    kept = list(chunks)
    while len(kept) > 1 and sum(len(c.text) for c in kept) > budget:
        kept.pop()
    return kept


def retrieve(plan, kb: KnowledgeBase, *, question="", jd_text="", company_text="", budget_chars=6000) -> list[Chunk]:
    ctx = Ctx(plan.project_id, question, jd_text, company_text)
    chunks, seen = [], set()
    for need in plan.needs:
        for chunk in RECIPES[need](kb, ctx):
            if chunk is not None and chunk.id not in seen:
                seen.add(chunk.id)
                chunks.append(chunk)
    return _within_budget(chunks, budget_chars)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_recipes.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/longform/recipes.py tests/longform/test_lf_recipes.py
git commit -m "feat(longform): recipes and budgeted retrieval per need"
```

---

### Task 4: Writer and verifier

**Files:**
- Create: `src/career_agent/longform/write.py`, `src/career_agent/longform/verify.py`
- Test: `tests/longform/test_lf_write_verify.py`

**Interfaces:**
- Consumes: `Chunk`, `KnowledgeBase` (Task 1). Reuses `_parse_reply` from `job_dashboard.apply.screening` (returns `(answer, confidence, basis)`).
- Produces: `build_prompt(question, chunks, job, limit=None, avoid=()) -> str`; `draft(question, chunks, job, llm, limit=None, avoid=()) -> dict` with keys `answer` (str | None), `confidence`, `basis`, `prompt`; `distinct_terms(kb, pid) -> set[str]`; `leak_check(answer, chunks, kb) -> list[str]` (ids of projects whose distinctive terms appear although their chunks were not retrieved); `fit_length(answer, limit) -> tuple[str, bool]`.

- [ ] **Step 1: Write the failing tests**

`tests/longform/test_lf_write_verify.py`:
```python
import json

from career_agent.longform.kb import Chunk
from career_agent.longform.verify import distinct_terms, fit_length, leak_check
from career_agent.longform.write import build_prompt, draft

JOB = {"title": "ML Engineer", "company": "Acme", "description": "fraud detection"}
CHUNKS = [Chunk("story:story_looking_for", "story_slot", "I want hard ML problems."),
          Chunk("project:p-graph:result", "project_story", "Found 40 rings.", "p-graph", "result"),
          Chunk("source:p-graph", "source", "Graph Entity Resolution - GNN community detection.", "p-graph")]


def test_prompt_labels_chunks_forbids_blending_and_states_the_limit():
    p = build_prompt("Why us?", CHUNKS, JOB, limit=300, avoid=("Churn Prediction Service",))
    assert "[CANDIDATE'S OWN WORDS]" in p and "[PROJECT STORY · p-graph]" in p and "[RÉSUMÉ TEXT (verbatim) · p-graph]" in p
    assert "Found 40 rings." in p and "under 300 characters" in p and "Do not mention: Churn Prediction Service" in p
    assert "separate" in p.lower() and '"confidence"' in p


def test_draft_parses_the_models_json_and_survives_failure():
    ok = draft("q", CHUNKS, JOB, lambda p: json.dumps({"answer": "Hello", "confidence": 88, "basis": "story"}))
    assert (ok["answer"], ok["confidence"], ok["basis"]) == ("Hello", 88, "story") and "prompt" in ok

    def boom(p): raise TimeoutError
    assert draft("q", CHUNKS, JOB, boom)["answer"] is None
    assert draft("q", CHUNKS, JOB, lambda p: "")["answer"] is None


def test_distinct_terms_are_unique_to_the_project(kb):
    graph = distinct_terms(kb, "p-graph")
    assert {"neo4j", "gnn", "graph entity resolution", "fraud"} <= graph and "ml" not in graph
    assert "docker" in distinct_terms(kb, "p-churn") and "pytorch" in distinct_terms(kb, "p-ocr")


def test_leak_check_flags_only_projects_that_were_not_retrieved(kb):
    used = [Chunk("source:p-churn", "source", "x", "p-churn")]
    assert leak_check("I used XGBoost and FastAPI.", used, kb) == []
    assert leak_check("I also built a GNN on Neo4j.", used, kb) == ["p-graph"]
    everyone = [Chunk(f"card:{p}", "card", "x", p) for p in ("p-churn", "p-ocr", "p-graph", "p-portfolio")]
    assert leak_check("GNN, Neo4j, OCR, Monte-Carlo", everyone, kb) == []     # an overview may mention all of them


def test_fit_length_trims_at_a_sentence_boundary():
    assert fit_length("Short.", 100) == ("Short.", False)
    assert fit_length("Short.", None) == ("Short.", False)
    text, trimmed = fit_length("First sentence. Second sentence is longer. Third.", 40)
    assert trimmed and text == "First sentence." and len(text) <= 40
    text, trimmed = fit_length("x" * 100, 30)
    assert trimmed and len(text) == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_write_verify.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'career_agent.longform.write'`

- [ ] **Step 3: Write the implementation**

`src/career_agent/longform/write.py`:
```python
"""Writer: one model call that sees ONLY the retrieved chunks. Projects that were not retrieved are not in the
prompt, so they cannot be blended into the answer."""
from __future__ import annotations

from job_dashboard.apply.screening import _parse_reply

_LABELS = {"card": "PROJECT SUMMARY", "project_story": "PROJECT STORY", "source": "RÉSUMÉ TEXT (verbatim)",
           "story_slot": "CANDIDATE'S OWN WORDS", "fact": "FACT", "jd": "JOB DESCRIPTION", "company": "COMPANY FACTS"}


def _render(chunks) -> str:
    blocks = []
    for c in chunks:
        label = _LABELS.get(c.kind, c.kind.upper()) + (f" · {c.project_id}" if c.project_id else "")
        blocks.append(f"[{label}]\n{c.text}")
    return "\n\n".join(blocks)


def build_prompt(question, chunks, job, limit=None, avoid=()) -> str:
    company = (job.get("company") if isinstance(job, dict) else None) or "the company"
    title = (job.get("title") if isinstance(job, dict) else None) or "the role"
    size = f"Keep it under {limit} characters." if limit else "Answer in 4-8 sentences."
    avoid_line = f"Do not mention: {', '.join(avoid)}.\n" if avoid else ""
    return (
        "You are answering ONE free-text question on a job application, in the candidate's own voice, first person.\n\n"
        "STRICT RULES (truthfulness is mandatory):\n"
        "1. Use ONLY the material below. Never invent an achievement, tool, metric or company fact.\n"
        "2. Projects are separate: describe each one on its own and never merge details of different projects.\n"
        "3. Company specifics only if they appear under COMPANY FACTS or JOB DESCRIPTION.\n"
        f"4. Be concrete and specific. {size}\n{avoid_line}\n"
        f"ROLE: {title} at {company}\nQUESTION: {question}\n\nMATERIAL:\n{_render(chunks)}\n\n"
        'Reply with ONLY a JSON object: {"answer": "<the answer text>", "confidence": <0-100, how sure you are this '
        'answers the question correctly from the material above>, "basis": "<one short line: what it rests on>"}'
    )


def draft(question, chunks, job, llm, limit=None, avoid=()) -> dict:
    prompt = build_prompt(question, chunks, job, limit, avoid)
    answer = confidence = basis = None
    try:
        raw = llm(prompt)
        if isinstance(raw, str) and raw.strip():
            answer, confidence, basis = _parse_reply(raw)
    except Exception:
        answer = confidence = basis = None
    return {"answer": answer or None, "confidence": confidence, "basis": basis, "prompt": prompt}
```

`src/career_agent/longform/verify.py`:
```python
"""Verifier: catch a draft that talks about a project whose material was not retrieved, and enforce a length limit."""
from __future__ import annotations

import re


def _terms(unit) -> set[str]:
    return ({str(unit.get("title", "")).lower(), *(t.lower() for t in unit.get("tech", [])),
             *(t.lower() for t in unit.get("tags", []))} - {""})


def distinct_terms(kb, pid) -> set[str]:
    """Terms (title, tech, tags) that belong to this project and to no other unit."""
    others: set[str] = set()
    for oid, unit in kb.units.items():
        if oid != pid:
            others |= _terms(unit)
    return {t for t in _terms(kb.units[pid]) - others if len(t) >= 3}


def leak_check(answer, chunks, kb) -> list[str]:
    used = {c.project_id for c in chunks if c.project_id}
    low = (answer or "").lower()
    leaks = []
    for unit in kb.projects():
        if unit["id"] in used:
            continue
        if any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low) for t in distinct_terms(kb, unit["id"])):
            leaks.append(unit["id"])
    return leaks


def fit_length(answer, limit) -> tuple[str, bool]:
    if not limit or len(answer) <= limit:
        return answer, False
    cut = answer[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?:\s|$)", cut)]
    return (cut[:ends[-1]].strip() if ends else cut), True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_write_verify.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/longform/write.py src/career_agent/longform/verify.py tests/longform/test_lf_write_verify.py
git commit -m "feat(longform): writer prompt over retrieved chunks; project-leak and length verifier"
```

---

### Task 5: Pipeline, prior choice and the hook factory

**Files:**
- Create: `src/career_agent/longform/pipeline.py`
- Test: `tests/longform/test_lf_pipeline.py`

**Interfaces:**
- Consumes: `plan_needs`/`Plan` (Task 2), `retrieve` (Task 3), `draft`/`build_prompt` (Task 4), `leak_check`/`fit_length` (Task 4), `KnowledgeBase` (Task 1); `job_dashboard.letter.grounding.check_grounding(answer, research, profile_text, job_text)` and `job_dashboard.apply.screening._facts_block`, `_general_answer`.
- Produces: `answer_longform(question, *, job, kb, llm, research=None, limit=None, prior=None) -> dict` with keys `answer, flags, unsupported_company_claims, confidence, basis, prompt, needs, project_id, used` (a superset of `draft_screening_answer`'s return); `prior_project(conn, job_id, label) -> str | None`; `make_longform(conn, job, contact, llm, research, ingredients_path) -> Callable[[str, object | None], dict]`.
- Flags used: `general_fallback`, `project_leak:<ids>`, `trimmed_to_limit`.

- [ ] **Step 1: Write the failing tests**

`tests/longform/test_lf_pipeline.py`:
```python
import json
import sqlite3
from types import SimpleNamespace as NS

from career_agent import longform
from career_agent.longform.pipeline import answer_longform, make_longform, prior_project
from career_agent import longform as _lf  # noqa: F401
from job_dashboard import qa_store

JOB = {"id": 7, "title": "ML Engineer", "company": "Acme", "description": "graph neural networks to detect fraud rings"}


def scripted(plan, answers):
    """A fake model: first call = the plan, later calls = drafts (consumed in order)."""
    replies = iter(answers)

    def llm(prompt):
        return json.dumps(plan) if "Allowed needs" in prompt else next(replies)
    return llm


def reply(text, conf=90):
    return json.dumps({"answer": text, "confidence": conf, "basis": "story"})


def test_end_to_end_one_project_answer_records_how_it_was_built(kb):
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"}, [reply("I found 40 fraud rings with a graph model.")])
    out = answer_longform("Describe a project you are proud of", job=JOB, kb=kb, llm=llm)
    assert out["answer"].startswith("I found 40") and out["confidence"] == 90 and out["flags"] == []
    assert out["needs"] == ["one_project"] and out["project_id"] == "p-graph"
    assert out["used"][-1] == "source:p-graph" and not any("churn" in u for u in out["used"])
    assert "Found 40 rings in the first month." in out["prompt"] and "Docker" not in out["prompt"]   # other projects are not in the prompt


def test_a_leaked_project_is_redrafted_once_then_flagged(kb):
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"},
                   [reply("I built a GNN, and also a XGBoost churn model."), reply("I built a GNN and used Neo4j.")])
    clean = answer_longform("Describe a project", job=JOB, kb=kb, llm=llm)
    assert "XGBoost" not in clean["answer"] and clean["flags"] == []

    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"},
                   [reply("GNN plus XGBoost."), reply("Still GNN plus XGBoost.")])
    flagged = answer_longform("Describe a project", job=JOB, kb=kb, llm=llm)
    assert flagged["flags"] == ["project_leak:p-churn"]


def test_length_limit_is_enforced_and_flagged(kb):
    llm = scripted({"needs": ["looking_for"]}, [reply("First sentence. " + "Second sentence is rather long. " * 5)])
    out = answer_longform("What are you looking for?", job=JOB, kb=kb, llm=llm, limit=40)
    assert len(out["answer"]) <= 40 and out["flags"] == ["trimmed_to_limit"]


def test_a_failing_model_falls_back_to_a_general_answer_and_never_raises(kb):
    def boom(p): raise TimeoutError
    out = answer_longform("Tell me about yourself", job=JOB, kb=kb, llm=boom)
    assert out["answer"] and "general_fallback" in out["flags"] and out["needs"] == ["intro"]


def test_company_claims_not_in_the_material_are_reported(kb):
    llm = scripted({"needs": ["why_company"], "project_id": "p-graph"},
                   [reply("Acme's $2B Series C and its Phoenix platform excite me.")])
    out = answer_longform("Why do you want to join us?", job=JOB, kb=kb, llm=llm, research=None)
    assert isinstance(out["unsupported_company_claims"], list)


def test_prior_project_is_read_from_the_recorded_draft():
    conn = sqlite3.connect(":memory:")
    qa_store.ensure(conn)
    assert prior_project(conn, 7, "Describe a project") is None
    qa_store.record(conn, job_id=7, run_key="r", ref="x", label="Describe a project", kind="textarea", status="filled",
                    context_json={"project_id": "p-ocr", "needs": ["one_project"]})
    assert prior_project(conn, 7, "Describe a project") == "p-ocr"
    assert prior_project(conn, 8, "Describe a project") is None


def test_make_longform_loads_once_and_reuses_the_prior_choice(tmp_path, kb):
    from career_agent.memory import qbank
    from tests.longform.conftest import FIXTURE
    conn = sqlite3.connect(":memory:")
    qbank.ensure(conn)                                                   # KnowledgeBase.load reads the story entries
    qa_store.ensure(conn)
    qa_store.record(conn, job_id=7, run_key="r", ref="x", label="Describe a project", kind="textarea", status="filled",
                    context_json={"project_id": "p-ocr"})
    llm = scripted({"needs": ["one_project"], "project_id": "p-graph"}, [reply("About OCR scoring.")])
    run = make_longform(conn, JOB, {"years_experience": "3"}, llm, None, FIXTURE)
    out = run("Describe a project", NS(label="Describe a project"))
    assert out["project_id"] == "p-ocr"                                  # the user's earlier choice sticks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_pipeline.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'career_agent.longform.pipeline'`. (If importing `tests.longform.conftest` fails, use `FIXTURE = Path(__file__).parent / "fixtures" / "ingredients.json"` as in Task 1.)

- [ ] **Step 3: Write the implementation**

`src/career_agent/longform/pipeline.py`:
```python
"""plan -> retrieve -> write -> verify. Same return shape as draft_screening_answer (plus how the answer was built),
so judgment.py can use either. Never raises."""
from __future__ import annotations

import json

from job_dashboard.apply.screening import _facts_block, _general_answer
from job_dashboard.letter.grounding import check_grounding

from .kb import KnowledgeBase
from .needs import plan_needs
from .recipes import retrieve
from .verify import fit_length, leak_check
from .write import draft


def _company_text(research) -> str:
    block = _facts_block(research)
    return "" if block.strip() == "(none)" else block


def answer_longform(question, *, job, kb, llm, research=None, limit=None, prior=None) -> dict:
    jd = (job.get("description") if isinstance(job, dict) else "") or ""
    plan = plan_needs(question, jd, kb, llm, prior)
    chunks = retrieve(plan, kb, question=question, jd_text=jd, company_text=_company_text(research))
    flags: list[str] = []

    out = draft(question, chunks, job, llm, limit)
    answer = out["answer"]
    if answer is not None:
        leaks = leak_check(answer, chunks, kb)
        if leaks:                                    # one redraft, naming what to leave out
            names = tuple(kb.units[p]["title"] for p in leaks)
            retry = draft(question, chunks, job, llm, limit, avoid=names)
            if retry["answer"]:
                out, answer = retry, retry["answer"]
                leaks = leak_check(answer, chunks, kb)
            if leaks:
                flags.append("project_leak:" + ",".join(leaks))
    if answer is None:
        answer = _general_answer(job, " ".join(c.text for c in chunks))
        flags.append("general_fallback")
    answer, trimmed = fit_length(answer, limit)
    if trimmed:
        flags.append("trimmed_to_limit")

    try:
        job_text = " ".join(str(job.get(k) or "") for k in ("title", "company", "description")) if isinstance(job, dict) else ""
        unsupported = check_grounding(answer, research, "\n".join(c.text for c in chunks), job_text).unsupported_company_claims
    except Exception:
        unsupported = []
    return {"answer": answer, "flags": flags, "unsupported_company_claims": unsupported,
            "confidence": out["confidence"], "basis": out["basis"], "prompt": out["prompt"],
            "needs": list(plan.needs), "project_id": plan.project_id, "used": [c.id for c in chunks]}


def prior_project(conn, job_id, label) -> str | None:
    """The project recorded for this job's earlier draft of this question (the user's override sticks)."""
    try:
        row = conn.execute("SELECT context_json FROM application_qa WHERE job_id=? AND label=? "
                           "AND context_json LIKE '%project_id%' ORDER BY id DESC LIMIT 1", (job_id, label)).fetchone()
        return (json.loads(row[0]) if row and row[0] else {}).get("project_id")
    except Exception:
        return None


def make_longform(conn, job, contact, llm, research, ingredients_path):
    """The callable judgment.py uses: run(question, field) -> result dict. The knowledge base is loaded once."""
    kb = KnowledgeBase.load(conn, ingredients_path, contact)

    def run(question, field=None):
        prior = prior_project(conn, job.get("id"), question) if isinstance(job, dict) and job.get("id") else None
        return answer_longform(question, job=job, kb=kb, llm=llm, research=research, prior=prior)
    return run
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_pipeline.py -q`
Expected: PASS (7 passed). If `test_a_leaked_project…` fails with an unexpected `unsupported_company_claims` interaction, only the `flags` assertions matter there — do not weaken them.

- [ ] **Step 5: Commit**

```bash
git add src/career_agent/longform/pipeline.py tests/longform/test_lf_pipeline.py
git commit -m "feat(longform): plan-retrieve-write-verify pipeline with leak redraft and sticky project choice"
```

---

### Task 6: Eval set, retrieval metrics and the live eval script

**Files:**
- Create: `tests/longform/eval_set.json`, `tests/longform/test_lf_retrieval_eval.py`, `scripts/longform_eval.py`

**Interfaces:**
- Consumes: `retrieve` (Task 3), `heuristic_needs`, `Plan` (Task 2), `answer_longform` (Task 5), the `kb` fixture (Task 1).
- Produces: `eval_set.json` = list of cases `{id, question, jd, company, gold_needs, gold_project, must_include, must_exclude, max_chunks, heuristic}`; deterministic metrics (required-chunk recall, over-inclusion) asserted in tests; `scripts/longform_eval.py` prints plan accuracy and project-leak rate with the real local model.

- [ ] **Step 1: Write the eval set**

`tests/longform/eval_set.json`:
```json
[
  {"id": "intro", "question": "Tell me about yourself", "jd": "ML engineer for fraud detection", "company": "",
   "gold_needs": ["intro"], "gold_project": null, "heuristic": true, "max_chunks": 10,
   "must_include": ["story:story_how_you_work", "story:story_looking_for", "card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"],
   "must_exclude": ["project:p-graph:hardest", "source:p-graph"]},
  {"id": "mixed-start-a-conversation", "question": "Share something about you, what you're looking for, or why Acme interests you.",
   "jd": "graph neural networks to detect fraud rings", "company": "Acme builds fraud detection software",
   "gold_needs": ["intro", "why_company", "looking_for"], "gold_project": "p-graph", "heuristic": true, "max_chunks": 16,
   "must_include": ["story:story_looking_for", "company", "project:p-graph:result", "card:p-churn"], "must_exclude": ["source:p-churn"]},
  {"id": "proud-project", "question": "Describe a project you are proud of", "jd": "graph neural networks to detect fraud rings", "company": "",
   "gold_needs": ["one_project"], "gold_project": "p-graph", "heuristic": true, "max_chunks": 5,
   "must_include": ["project:p-graph:hardest", "project:p-graph:result", "source:p-graph"],
   "must_exclude": ["card:p-churn", "source:p-churn", "source:p-ocr", "story:story_looking_for"]},
  {"id": "why-company", "question": "What interests you about working for this company?", "jd": "graph neural networks to detect fraud rings",
   "company": "Acme builds fraud detection software", "gold_needs": ["why_company"], "gold_project": "p-graph", "heuristic": true, "max_chunks": 8,
   "must_include": ["story:story_looking_for", "company", "project:p-graph:result"], "must_exclude": ["source:p-churn", "project:p-churn:result"]},
  {"id": "why-join-us", "question": "Why do you want to join us?", "jd": "OCR and document vision for claims", "company": "",
   "gold_needs": ["why_company"], "gold_project": "p-ocr", "heuristic": true, "max_chunks": 8,
   "must_include": ["story:story_looking_for", "jd", "source:p-ocr"], "must_exclude": ["source:p-graph"]},
  {"id": "challenge", "question": "Describe a challenging problem you solved", "jd": "OCR and document vision for claims", "company": "",
   "gold_needs": ["challenge"], "gold_project": "p-ocr", "heuristic": true, "max_chunks": 3,
   "must_include": ["source:p-ocr"], "must_exclude": ["source:p-graph", "card:p-graph"]},
  {"id": "looking-for", "question": "What are you looking for in your next role?", "jd": "", "company": "",
   "gold_needs": ["looking_for"], "gold_project": null, "heuristic": true, "max_chunks": 2,
   "must_include": ["story:story_looking_for", "story:story_problems"], "must_exclude": ["card:p-graph", "source:p-graph"]},
  {"id": "working-style", "question": "How do you like to work?", "jd": "", "company": "",
   "gold_needs": ["working_style"], "gold_project": null, "heuristic": true, "max_chunks": 1,
   "must_include": ["story:story_how_you_work"], "must_exclude": ["card:p-graph"]},
  {"id": "skills", "question": "Please list down your skillset", "jd": "", "company": "",
   "gold_needs": ["skills_list"], "gold_project": null, "heuristic": true, "max_chunks": 1,
   "must_include": ["skills:pool"], "must_exclude": ["story:story_looking_for"]},
  {"id": "key-projects", "question": "List your key projects", "jd": "", "company": "",
   "gold_needs": ["projects_overview"], "gold_project": null, "heuristic": true, "max_chunks": 4,
   "must_include": ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"], "must_exclude": ["source:p-graph", "project:p-graph:result"]},
  {"id": "why-role", "question": "Why this role?", "jd": "OCR and document vision for claims", "company": "",
   "gold_needs": ["why_role"], "gold_project": "p-ocr", "heuristic": true, "max_chunks": 6,
   "must_include": ["story:story_looking_for", "story:story_problems", "jd", "source:p-ocr"], "must_exclude": ["source:p-graph"]},
  {"id": "anything-else", "question": "Anything else you'd like us to know?", "jd": "", "company": "",
   "gold_needs": ["other"], "gold_project": null, "heuristic": true, "max_chunks": 4,
   "must_include": [], "must_exclude": ["project:p-graph:hardest"]}
]
```

- [ ] **Step 2: Write the deterministic eval test**

`tests/longform/test_lf_retrieval_eval.py`:
```python
import json
from pathlib import Path

import pytest

from career_agent.longform.needs import Plan, heuristic_needs
from career_agent.longform.recipes import retrieve

CASES = json.loads((Path(__file__).parent / "eval_set.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_retrieval_for_the_gold_plan_has_full_recall_and_no_overinclusion(kb, case):
    plan = Plan(tuple(case["gold_needs"]), case["gold_project"], "", "gold")
    got = {c.id for c in retrieve(plan, kb, question=case["question"], jd_text=case["jd"], company_text=case["company"])}
    missing = set(case["must_include"]) - got
    extra = set(case["must_exclude"]) & got
    assert not missing, f"missing required chunks: {sorted(missing)}"
    assert not extra, f"over-included chunks: {sorted(extra)}"
    assert len(got) <= case["max_chunks"], f"{len(got)} chunks > {case['max_chunks']}: {sorted(got)}"


@pytest.mark.parametrize("case", [c for c in CASES if c["heuristic"]], ids=lambda c: c["id"])
def test_the_regex_planner_finds_the_gold_needs(case):
    assert set(heuristic_needs(case["question"])) == set(case["gold_needs"])


def test_eval_set_is_well_formed():
    assert len(CASES) >= 12 and len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert set(c) >= {"id", "question", "jd", "company", "gold_needs", "gold_project", "must_include", "must_exclude", "max_chunks"}
```

- [ ] **Step 3: Run the eval test**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_retrieval_eval.py -q`
Expected: PASS (12 + 12 + 1 = 25 passed). A failure here is a real finding about a recipe or the regexes: fix the **recipe or heuristic**, not the case, unless the case itself contradicts the spec's recipe table (§6).

- [ ] **Step 4: Write the live eval script**

`scripts/longform_eval.py`:
```python
#!/usr/bin/env python3
"""Live eval with the real local model: need-planning accuracy and project-leak rate over tests/longform/eval_set.json.
Needs Ollama running; stop it afterwards (`pkill -f "Ollama.app"`). Not part of the test suite.

    PYTHONPATH=src python3 scripts/longform_eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "longform"))

from career_agent.longform.kb import KnowledgeBase                      # noqa: E402
from career_agent.longform.needs import plan_needs                       # noqa: E402
from career_agent.longform.pipeline import answer_longform               # noqa: E402
from job_dashboard.letter.draft import make_default_llm                 # noqa: E402

FIXTURES = ROOT / "tests" / "longform"


def main() -> int:
    from conftest import FACTS, PROJECT_STORIES, STORIES                  # the same synthetic knowledge the tests use
    data = json.loads((FIXTURES / "fixtures" / "ingredients.json").read_text())
    kb = KnowledgeBase(data["units"], dict(STORIES), dict(PROJECT_STORIES), dict(FACTS), data["skills_pool"])
    cases = json.loads((FIXTURES / "eval_set.json").read_text())
    llm = make_default_llm()
    exact = jaccard = leaks = 0
    for c in cases:
        plan = plan_needs(c["question"], c["jd"], kb, llm)
        gold, got = set(c["gold_needs"]), set(plan.needs)
        exact += gold == got
        jaccard += len(gold & got) / len(gold | got)
        out = answer_longform(c["question"], job={"title": "ML Engineer", "company": "Acme", "description": c["jd"]},
                              kb=kb, llm=llm, prior=c["gold_project"])
        leak = any(f.startswith("project_leak") for f in out["flags"])
        leaks += leak
        print(f"{c['id']:28s} needs={sorted(got)} gold={sorted(gold)} project={plan.project_id} "
              f"flags={out['flags']} {'LEAK' if leak else ''}")
    n = len(cases)
    print(f"\nplan exact match {exact}/{n} | mean Jaccard {jaccard / n:.2f} | drafts with a project leak {leaks}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Smoke-check the script imports (no model call)**

Run: `PYTHONPATH=src python3 -c "import ast,sys; ast.parse(open('scripts/longform_eval.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 6: Commit**

```bash
git add tests/longform/eval_set.json tests/longform/test_lf_retrieval_eval.py scripts/longform_eval.py
git commit -m "test(longform): labelled eval set, retrieval metrics, live eval script"
```

---

### Task 7: Wire into the judgment tier (opt-in)

**Files:**
- Modify: `src/career_agent/orchestrator/judgment.py` (dataclass at lines 14-21; text path at lines ~203-214)
- Modify: `src/career_agent/orchestrator/qa_recorder.py` (`on_draft`, lines 57-62)
- Modify: `src/career_agent/apply.py` (argparse near the `--claude-assist` flag; `JudgmentContext(...)` at ~line 204)
- Test: `tests/longform/test_lf_wiring.py`

**Interfaces:**
- Consumes: `make_longform` (Task 5).
- Produces: `JudgmentContext.longform: object = None` (callable `(question, field) -> dict | None`); `judge()` uses it for prose fields and falls back to `draft_screening_answer` when it is absent, raises or returns None; `QARecorder.on_draft` stores `needs`, `project_id`, `used` inside `context_json`; CLI `--longform` / env `CAREER_AGENT_LONGFORM=1`.

- [ ] **Step 1: Write the failing tests**

`tests/longform/test_lf_wiring.py`:
```python
from types import SimpleNamespace as NS

from career_agent.orchestrator import judgment
from career_agent.orchestrator.judgment import JudgmentContext, judge


def field(label="Why do you want to join us?"):
    return NS(ref="r1", kind="textarea", label=label, purpose=None, required=True, options=[], description="")


def test_the_longform_hook_answers_prose_fields_instead_of_the_old_drafter(monkeypatch):
    def old_drafter(*a, **k): raise AssertionError("the old drafter must not run")
    monkeypatch.setattr(judgment, "draft_screening_answer", old_drafter)
    res = {"answer": "From longform.", "confidence": 90, "flags": [], "unsupported_company_claims": [], "basis": "b",
           "prompt": "p", "needs": ["why_company"], "project_id": "p-graph", "used": ["story:x"]}
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"}, longform=lambda q, f: res)
    seen = []
    answered, still, _ = judge([field()], ctx, llm=lambda p: "", on_draft=lambda f, r, filled: seen.append(r))
    assert [d.value for d in answered] == ["From longform."] and still == []
    assert seen[0]["project_id"] == "p-graph"


def test_a_failing_or_empty_hook_falls_back_to_the_old_drafter(monkeypatch):
    calls = []
    monkeypatch.setattr(judgment, "draft_screening_answer",
                        lambda *a, **k: calls.append(1) or {"answer": "Old.", "confidence": 80, "flags": [],
                                                           "unsupported_company_claims": []})

    def boom(q, f): raise RuntimeError("longform broke")
    for hook in (boom, lambda q, f: None):
        ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"}, longform=hook)
        answered, _, _ = judge([field()], ctx, llm=lambda p: "")
        assert [d.value for d in answered] == ["Old."]
    assert len(calls) == 2


def test_without_a_hook_nothing_changes(monkeypatch):
    monkeypatch.setattr(judgment, "draft_screening_answer",
                        lambda *a, **k: {"answer": "Old.", "confidence": 80, "flags": [], "unsupported_company_claims": []})
    ctx = JudgmentContext(job={"title": "t", "company": "c", "description": "d"})
    assert [d.value for d in judge([field()], ctx, llm=lambda p: "")[0]] == ["Old."]


def test_the_recorder_keeps_how_the_draft_was_built():
    from career_agent.orchestrator.qa_recorder import QARecorder
    rec = QARecorder.__new__(QARecorder)
    captured = {}
    rec._rec = lambda ref, label, **kw: captured.update(kw)
    rec.on_draft(field(), {"answer": "A", "confidence": 90, "basis": "b", "prompt": "P", "needs": ["intro"],
                           "project_id": "p-ocr", "used": ["card:p-ocr"], "unsupported_company_claims": []}, True)
    assert captured["context_json"] == {"prompt": "P", "needs": ["intro"], "project_id": "p-ocr", "used": ["card:p-ocr"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_wiring.py -q`
Expected: FAIL — `TypeError: JudgmentContext.__init__() got an unexpected keyword argument 'longform'`

- [ ] **Step 3: Modify `judgment.py`**

In the `JudgmentContext` dataclass add the field after `story_text`:
```python
    longform: object = None        # callable(question, field) -> dict | None: the need-based long-answer pipeline
```
In `judge()`, replace the drafting call (`res = draft_screening_answer(ctx.job, f.label, profile_text, ctx.research, ctx.resume_text, llm=llm, story_text=ctx.story_text)`) with:
```python
            res = None
            if ctx.longform is not None:
                try:
                    res = ctx.longform(f.label, f)
                except Exception:
                    res = None                       # never let the new pipeline stop an application
            if res is None:
                res = draft_screening_answer(ctx.job, f.label, profile_text,
                                             ctx.research, ctx.resume_text, llm=llm,
                                             story_text=ctx.story_text)
```
(Keep the surrounding `calls += 1`, `conf = res.get("confidence")` etc. unchanged.)

- [ ] **Step 4: Modify `qa_recorder.py`**

Replace `context_json={"prompt": res.get("prompt")},` in `on_draft` with:
```python
                  context_json={"prompt": res.get("prompt"), "needs": res.get("needs"),
                                "project_id": res.get("project_id"), "used": res.get("used")},
```

- [ ] **Step 5: Modify `apply.py`**

Next to the `--claude-assist` argument add:
```python
    ap.add_argument("--longform", action="store_true",
                    help="long free-text answers via the need-based pipeline (plan -> retrieve -> write -> verify); "
                         "also on if CAREER_AGENT_LONGFORM=1. Falls back to the old drafter on any failure.")
```
Immediately after `ctx = JudgmentContext(...)` (the statement that builds it, around line 204) add:
```python
            if args.longform or os.getenv("CAREER_AGENT_LONGFORM") == "1":
                from .longform.pipeline import make_longform
                ctx.longform = make_longform(conn, job, contact, llm, ctx.research,
                                             _RunPath(args.db).parent / "answer_style" / "ingredients.json")
                print("[longform] need-based long answers ON", flush=True)
```
Use the profile-contact dict already available in that block (the same object `profile_to_text(profile)` reads; if it is `profile.contact`, pass `getattr(profile, "contact", {})`). `_RunPath` is the existing `pathlib.Path` alias already imported at the top of `apply.py`.

- [ ] **Step 6: Run the new tests and the career_agent suite**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_wiring.py tests/career_agent -q`
Expected: PASS (4 new + the existing career_agent tests, no regressions)

- [ ] **Step 7: Commit**

```bash
git add src/career_agent/orchestrator/judgment.py src/career_agent/orchestrator/qa_recorder.py src/career_agent/apply.py tests/longform/test_lf_wiring.py
git commit -m "feat(longform): opt-in hook in the judgment tier; record needs/project/chunks used"
```

---

### Task 8: MCP exposure of the typed tools

**Files:**
- Create: `src/career_agent/longform/tools.py`
- Modify: `src/career_agent/mcp_server.py` (`set_session` signature near line 30; new tool after `memory_access`)
- Test: `tests/longform/test_lf_tools.py`

**Interfaces:**
- Consumes: `KnowledgeBase` (Task 1).
- Produces: `knowledge_dispatch(kb, op, args) -> list[dict]` (each `{"id", "kind", "text"}`) for ops `LIST_PROJECTS`, `GET_PROJECT` (`project_id`, optional `sections`), `GET_STORY` (`slot`), `GET_FACTS` (`keys`); an MCP tool `knowledge_access(op, args)`; `set_session(..., knowledge=None)`.

- [ ] **Step 1: Write the failing tests**

`tests/longform/test_lf_tools.py`:
```python
import pytest

from career_agent.longform.tools import knowledge_dispatch


def test_list_projects_and_get_project(kb):
    cards = knowledge_dispatch(kb, "LIST_PROJECTS", {})
    assert [c["id"] for c in cards] == ["card:p-churn", "card:p-ocr", "card:p-graph", "card:p-portfolio"]
    got = knowledge_dispatch(kb, "GET_PROJECT", {"project_id": "p-graph", "sections": ["hardest"]})
    assert [c["id"] for c in got] == ["project:p-graph:hardest", "source:p-graph"]
    assert set(got[0]) == {"id", "kind", "text"}


def test_story_and_facts(kb):
    assert knowledge_dispatch(kb, "GET_STORY", {"slot": "story_looking_for"})[0]["kind"] == "story_slot"
    assert knowledge_dispatch(kb, "GET_STORY", {"slot": "nope"}) == []
    assert [c["id"] for c in knowledge_dispatch(kb, "GET_FACTS", {"keys": ["current_title", "nope"]})] == ["fact:current_title"]


def test_unknown_ops_and_missing_args_are_clear_errors(kb):
    with pytest.raises(ValueError, match="unknown op"):
        knowledge_dispatch(kb, "DELETE_EVERYTHING", {})
    with pytest.raises(ValueError, match="project_id"):
        knowledge_dispatch(kb, "GET_PROJECT", {})


def test_the_mcp_tool_uses_the_session_knowledge(kb):
    pytest.importorskip("mcp")                                # the MCP package is optional in some environments
    from career_agent import mcp_server
    mcp_server.set_session(knowledge=kb)
    got = mcp_server.knowledge_access("LIST_PROJECTS", {})
    assert len(got) == 4
    mcp_server.set_session()                                  # leave no session behind
    with pytest.raises(RuntimeError):
        mcp_server.knowledge_access("LIST_PROJECTS", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_tools.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'career_agent.longform.tools'`

- [ ] **Step 3: Write `tools.py`**

`src/career_agent/longform/tools.py`:
```python
"""The retrieval tools as one dispatcher, so the MCP server (and any other caller) shares the pipeline's code."""
from __future__ import annotations


def _out(chunks) -> list[dict]:
    return [{"id": c.id, "kind": c.kind, "text": c.text} for c in chunks if c is not None]


def knowledge_dispatch(kb, op, args) -> list[dict]:
    args = args or {}
    if op == "LIST_PROJECTS":
        return _out(kb.list_projects())
    if op == "GET_PROJECT":
        if not args.get("project_id"):
            raise ValueError("GET_PROJECT needs project_id")
        return _out(kb.get_project(args["project_id"], tuple(args["sections"]) if args.get("sections") else None))
    if op == "GET_STORY":
        return _out([kb.get_story(args.get("slot", ""))])
    if op == "GET_FACTS":
        return _out(kb.get_facts(tuple(args.get("keys", ()))))
    raise ValueError(f"unknown op {op!r}; expected LIST_PROJECTS, GET_PROJECT, GET_STORY or GET_FACTS")
```

- [ ] **Step 4: Modify `mcp_server.py`**

Add `knowledge: Any = None,` to the `set_session` keyword-only parameters and `knowledge=knowledge,` to the dict assigned to `_session`. After the `memory_access` tool add:
```python
@mcp.tool()
def knowledge_access(op: str, args: dict[str, Any]) -> Any:
    """Long-answer knowledge: typed chunks of the candidate's projects, stories and facts.

    op:
      LIST_PROJECTS                          — one-line card per project
      GET_PROJECT(project_id, sections?)     — story sections + verbatim résumé text (sections: problem, built, tech, hardest, result, improve)
      GET_STORY(slot)                        — one of the candidate's own-words story answers
      GET_FACTS(keys)                        — short profile facts
    """
    from .longform.tools import knowledge_dispatch
    kb = _require().get("knowledge")
    if kb is None:
        raise RuntimeError("No knowledge base in session")
    return knowledge_dispatch(kb, op, args)
```
Where `apply.py` calls `set_session(...)` (search for `set_session(`), pass `knowledge=ctx.longform_kb` only if one is built; if the call site does not exist in the current code path, leave `apply.py` unchanged here — the tool is available whenever a caller registers a session with `knowledge=`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/longform/test_lf_tools.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/career_agent/longform/tools.py src/career_agent/mcp_server.py tests/longform/test_lf_tools.py
git commit -m "feat(longform): expose the typed retrieval tools through the MCP server"
```

---

### Task 9: Full verification and the first live eval

**Files:** none created (results are recorded in the PR description / commit message of this task).

- [ ] **Step 1: Run the whole suite**

Run: `PYTHONPATH=src python3 -m pytest tests -q`
Expected: all pass; the only new tests are under `tests/longform/` (about 65). Fix any regression before continuing.

- [ ] **Step 2: Start the local model, run the live eval, stop the model**

```bash
open -a Ollama
until curl -s -m 2 localhost:11434/api/tags >/dev/null; do sleep 2; done
PYTHONPATH=src python3 scripts/longform_eval.py
pkill -f "Ollama.app"; sleep 2; pgrep -fl "ollama|llama-server" || echo "ollama stopped"
```
Expected: one line per case plus a summary `plan exact match X/12 | mean Jaccard Y | drafts with a project leak Z/12`. Ollama must be stopped afterwards (global rule).

- [ ] **Step 3: Record the baseline and decide**

Write the three summary numbers into the commit message below. Acceptance for turning the feature on by default: plan exact match ≥ 9/12 **and** project-leak drafts 0/12. If it falls short, do not change defaults — open a follow-up to tune the planner prompt or recipes, using the failing case ids from the output.

- [ ] **Step 4: Commit the baseline note**

```bash
git commit --allow-empty -m "test(longform): phase 1 baseline — plan exact X/12, Jaccard Y, project leaks Z/12 (qwen3:14b)"
```
(Replace X, Y, Z with the measured numbers before running this command.)

---

## Self-Review (done while writing)

**Spec coverage (§6, §8, §9 phase 1):** need set and planner → Task 2; recipes table (intro, one_project, why_company, challenge, looking_for/working_style, skills_list, other, plus projects_overview and why_role) → Task 3; typed tools `get_facts / get_story / list_projects / get_project` → Task 1 and MCP exposure → Task 8; `get_company_context` is covered by the company/JD chunks built inside `retrieve` (Task 3) rather than a separate callable, because the company text already comes from the run's research bundle; writer sees only retrieved chunks → Task 4; leak check, redraft once then flag, length limit → Tasks 4-5; per-job sticky project choice → Task 5 (`prior_project`) and Task 7 (recording `project_id`); always flagged for review → unchanged existing behaviour (drafts keep the `judgment` source and confidence gate); eval set, metrics measured separately from writing, live script → Task 6; baseline run → Task 9. The review-card "which chunks were used, switch project" UI is Phase 2; Phase 1 only records `needs`/`project_id`/`used`.

**Placeholder scan:** none; Task 9's commit message has X/Y/Z to fill with measured numbers, which is a measurement not a missing design.

**Type consistency:** `Chunk` fields and ids, `Plan(needs, project_id, reason, source)`, `retrieve(plan, kb, *, question, jd_text, company_text, budget_chars)`, `draft(...)`/`build_prompt(...)`, `leak_check(answer, chunks, kb)`, `answer_longform(...)` keys and `make_longform(...)` are used identically across Tasks 1-8.

**Known gaps the engineer should treat as decisions already made:** the five story slots have no dedicated "about you" slot, so `intro` uses `story_how_you_work` + `story_looking_for`; field length limits are not yet read from the form (Phase 1 passes `limit=None`), so `fit_length` is exercised by tests only.
