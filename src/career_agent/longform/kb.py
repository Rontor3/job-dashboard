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


def _stem(w: str) -> str:
    """Just enough that "deployed/deploys/deploying" and "models/model" meet: strip a common ending."""
    for end in ("ing", "ed", "es", "s"):
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[: -len(end)]
    return w


_PRACTICES_PATH = Path(__file__).with_name("practices.json")


def _load_practices() -> list[dict]:
    """Industry-standard practice entries (general knowledge, never the candidate's own experience)."""
    try:
        return json.loads(_PRACTICES_PATH.read_text()).get("practices", [])
    except (OSError, ValueError):
        return []


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
    def __init__(self, units, stories=None, project_stories=None, facts=None, skills=None, embed=None):
        self.embed = embed                       # texts -> unit vectors; None = word matching only
        self.practices = _load_practices()
        self.units = {u["id"]: u for u in units}
        self._stories = stories or {}
        self._project_stories = project_stories or {}
        self._facts = facts or {}
        self.skills = skills or []

    @classmethod
    def load(cls, conn, ingredients_path, contact=None, embed=None) -> "KnowledgeBase":
        data = json.loads(Path(ingredients_path).read_text())
        stories, project_stories = {}, {}
        for eid, ans in conn.execute("SELECT id, answer FROM qbank_entry WHERE topic='story' AND status='active' "
                                     "AND TRIM(COALESCE(answer, '')) != ''"):
            if eid.startswith("story_project_"):
                project_stories[eid[len("story_project_"):]] = ans
            else:
                stories[eid] = ans
        return cls(data.get("units", []), stories, project_stories, dict(contact or {}), data.get("skills_pool", []), embed=embed)

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

    def _bm25(self, units, docs, text: str) -> list[float]:
        import math
        want = {_stem(w) for w in _WORD.findall((text or "").lower()) if w not in _STOP}
        n, avg = len(docs), (sum(map(len, docs)) / len(docs) if docs else 1) or 1
        out = []
        for doc in docs:
            score = 0.0
            for w in want:
                tf = doc.count(w)
                if not tf:
                    continue
                df = sum(1 for d in docs if w in d)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * len(doc) / avg))
            out.append(score)
        return out

    def _unit_vectors(self, units):
        """Embedding of each unit's whole record, computed once (None when no embedder is set or it fails)."""
        cached = getattr(self, "_uvec", None)
        if cached is not None and cached[0] == [u["id"] for u in units]:
            return cached[1]
        vecs = None
        if self.embed is not None:
            try:
                texts = [" ".join([u.get("title", ""), u.get("problem", ""), u.get("approach", ""),
                                   " ".join(u.get("tech", [])), (u.get("source", "") or "")[:1200]]) for u in units]
                vecs = self.embed(texts)
            except Exception:
                vecs = None
        self._uvec = ([u["id"] for u in units], vecs)
        return vecs

    def rank_projects(self, text: str, context: str = "") -> list[tuple[str, float]]:
        """Projects ranked for `text` (the question). Two signals on each unit's whole record, title/tech/tags double:
        BM25 (words the question and a project share, rare ones count most) and, when an embedder is set, cosine
        similarity (meaning: "LLM" ~ "Claude Sonnet"). Each is scaled to its best project and averaged. `context`
        (the job description) only breaks ties, at a tenth of the weight, so a long description never drowns the
        question. 0 = nothing matches."""
        import numpy as np
        units = self.projects()
        docs = []
        for u in units:
            core = " ".join([u.get("title", ""), " ".join(u.get("tech", [])), " ".join(u.get("tags", []))])
            rest = " ".join([u.get("problem", ""), u.get("approach", ""), u.get("source", "")])
            docs.append([_stem(w) for w in _WORD.findall((core + " " + core + " " + rest).lower()) if w not in _STOP])
        lex = self._bm25(units, docs, text)
        top = max(lex, default=0.0)
        score = np.array([x / top if top else 0.0 for x in lex], dtype="float64")
        vecs = self._unit_vectors(units)
        if vecs is not None and (text or "").strip():
            try:
                sim = np.asarray(vecs) @ np.asarray(self.embed([text])[0])
                sim = np.clip(sim, 0.0, None)
                score = (score + (sim / sim.max() if sim.max() > 0 else sim)) / 2
            except Exception:
                pass
        if (context or "").strip():
            ctx = self._bm25(units, docs, context)
            cmax = max(ctx, default=0.0)
            if cmax:
                score = score + 0.1 * np.array(ctx) / cmax
        scored = [(u["id"], round(float(sc), 4)) for u, sc in zip(units, score)]
        return sorted(scored, key=lambda t: (-t[1], t[0]))

    def practice_chunks(self, question: str, n: int = 2) -> list[Chunk]:
        """The `n` best-matching industry-practice entries for `question`, ranked like projects: BM25 over title,
        tags and body, plus embedding similarity when an embedder is set. Only entries that match at all."""
        import numpy as np
        recs = self.practices
        if not recs:
            return []
        docs = [[_stem(w) for w in _WORD.findall((r.get("title", "") + " " + " ".join(r.get("tags", [])) * 2 + " "
                                                   + r.get("body", "")).lower()) if w not in _STOP] for r in recs]
        lex = self._bm25(recs, docs, question)
        top = max(lex, default=0.0)
        score = np.array([x / top if top else 0.0 for x in lex], dtype="float64")
        if self.embed is not None and (question or "").strip():
            try:
                vecs = getattr(self, "_pvec", None)
                if vecs is None:
                    vecs = self._pvec = np.asarray(self.embed([r.get("title", "") + ". " + r.get("body", "")[:900] for r in recs]))
                sim = np.clip(vecs @ np.asarray(self.embed([question])[0]), 0.0, None)
                score = (score + (sim / sim.max() if sim.max() > 0 else sim)) / 2
            except Exception:
                pass
        order = [i for i in np.argsort(-score) if score[i] > 0.15][:n]
        return [Chunk(f"practice:{recs[i]['id']}", "practice", f"{recs[i].get('title', '')}\n{recs[i].get('body', '')}")
                for i in order]

    def passages(self, query: str, n: int = 5, max_chars: int = 700, project_id: str | None = None) -> list[Chunk]:
        """The `n` passages (paragraph-sized pieces of project / work-experience source text) that best match `query`,
        across all projects: BM25 plus embedding similarity, each scaled to its best. A passage is the unit of
        retrieval, so a long project write-up no longer has to fit whole or be cut after its first characters."""
        import numpy as np
        paras = []
        for pid, u in self.units.items():
            if u.get("type") not in ("project", "work_experience") or (project_id and pid != project_id):
                continue
            for k, block in enumerate(re.split(r"\n\s*\n|\n(?=[A-Z][^\n]{0,60}\n)", u.get("source") or "")):
                if len(block.strip()) >= 80:
                    paras.append((pid, k, f"[{u.get('title', pid)}] {block.strip()[:max_chars]}"))
        if not paras or not (query or "").strip():
            return []
        docs = [[_stem(w) for w in _WORD.findall(t.lower()) if w not in _STOP] for _, _, t in paras]
        lex = np.array(self._bm25(paras, docs, query), dtype="float64")
        score = lex / lex.max() if lex.max() else lex
        if self.embed is not None:
            try:
                key = len(paras)
                cache = getattr(self, "_passvec", None)
                if cache is None or cache[0] != key:
                    cache = self._passvec = (key, np.asarray(self.embed([t for _, _, t in paras])))
                sim = np.clip(cache[1] @ np.asarray(self.embed([query])[0]), 0.0, None)
                score = (score + (sim / sim.max() if sim.max() > 0 else sim)) / 2
            except Exception:
                pass
        order = [i for i in np.argsort(-score) if score[i] > 0.25][:n]
        return [Chunk(f"passage:{paras[i][0]}:{paras[i][1]}", "passage", paras[i][2], paras[i][0]) for i in order]

    def main_project(self, question: str) -> str | None:
        """The one project an answer's personal pieces should all draw on: the project owning the best-ranked passages
        for the whole question (rank-weighted), so one answer never blends several projects."""
        score: dict[str, float] = {}
        for rank, c in enumerate(self.passages(question, 8)):
            score[c.project_id] = score.get(c.project_id, 0.0) + 1.0 / (rank + 1)
        return max(score, key=score.get) if score else None
