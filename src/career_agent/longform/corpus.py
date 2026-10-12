"""One searchable corpus over everything an answer may need, so retrieval methods can be compared on equal terms.

Item kinds:  passage  a paragraph of a project / work-experience write-up        (id passage:<unit>:<k>, project_id = unit)
             fact     role, education, years, skills                             (id fact:role / fact:education / fact:skills)
             story    the applicant's own-words answers (looking for, why startups, how I work ...)
             practice industry-standard guidance (general knowledge, NOT the applicant's experience)
             company  pieces of the job posting being applied to

search() ranks by BM25 + embedding cosine (each scaled to its best, averaged); search_multi() fuses several queries with
reciprocal-rank fusion. Nothing is stored: vectors are computed once per process and cached."""
from __future__ import annotations

import re

import numpy as np

from .kb import Chunk, KnowledgeBase, _STOP, _WORD, _stem

PERSONAL = {"passage", "fact", "story"}
_RRF_K = 60


class Corpus:
    def __init__(self, kb: KnowledgeBase, job: dict | None = None, company_chars: int = 650):
        self.kb = kb
        self.items: list[Chunk] = list(self._static(kb)) + self._company(job or {}, company_chars)
        self._docs = [self._tok(c.text) for c in self.items]
        self._vecs = None

    # -- build ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def _tok(text: str) -> list[str]:
        return [_stem(w) for w in _WORD.findall((text or "").lower()) if w not in _STOP]

    @staticmethod
    def _static(kb: KnowledgeBase) -> list[Chunk]:
        cached = getattr(kb, "_corpus_static", None)
        if cached is not None:
            return cached
        out: list[Chunk] = []
        for pid, u in kb.units.items():
            if u.get("type") in ("project", "work_experience"):
                for k, block in enumerate(re.split(r"\n\s*\n|\n(?=[A-Z][^\n]{0,60}\n)", u.get("source") or "")):
                    if len(block.strip()) >= 80:
                        out.append(Chunk(f"passage:{pid}:{k}", "passage", f"[{u.get('title', pid)}] {block.strip()[:700]}", pid))
        facts = kb._facts or {}
        for u in kb.units.values():
            if u.get("type") == "work_experience" and str(u.get("to", "")).lower() == "present":
                yrs = f" {facts['years_experience']} years of experience in data science." if facts.get("years_experience") else ""
                out.append(Chunk("fact:role", "fact", f"Current role: {u.get('title')} at {u.get('org')} since {u.get('from')}.{yrs}"))
            if u.get("type") == "education":
                out.append(Chunk("fact:education", "fact", f"Education: {u.get('title')} in {u.get('field')} at {u.get('org')} ({u.get('from')} to {u.get('to')})."))
        if kb.skills:
            out.append(Chunk("fact:skills", "fact", "Skills: " + ", ".join(kb.skills)))
        for slot in kb.story_slots():
            ch = kb.get_story(slot)
            if ch:
                out.append(Chunk(f"story:{slot}", "story", ch.text[:800]))
        for r in kb.practices:
            out.append(Chunk(f"practice:{r['id']}", "practice", f"{r.get('title', '')}. {r.get('body', '')[:900]}"))
        kb._corpus_static = out
        return out

    @staticmethod
    def _company(job: dict, size: int) -> list[Chunk]:
        text = re.sub(r"\s+", " ", job.get("description") or "").strip()
        return [Chunk(f"company:{i}", "company", f"[{job.get('company', 'company')}] {text[s:s + size]}")
                for i, s in enumerate(range(0, min(len(text), size * 4), size))] if text else []

    # -- search --------------------------------------------------------------------------------------------------------
    def _vectors(self):
        if self._vecs is None and self.kb.embed is not None:
            cache = getattr(self.kb, "_corpus_vec", {})                      # vectors are cached per text across corpora
            missing = [c.text for c in self.items if c.text not in cache]
            if missing:
                for t, v in zip(missing, np.asarray(self.kb.embed(missing))):
                    cache[t] = v
                self.kb._corpus_vec = cache
            self._vecs = np.asarray([cache[c.text] for c in self.items])
        return self._vecs

    def scores(self, query: str) -> np.ndarray:
        if not (query or "").strip() or not self.items:
            return np.zeros(len(self.items))
        lex = np.array(self.kb._bm25(self.items, self._docs, query), dtype="float64")
        score = lex / lex.max() if lex.max() else lex
        vecs = self._vectors()
        if vecs is not None:
            try:
                sim = np.clip(vecs @ np.asarray(self.kb.embed([query[:1500]])[0]), 0.0, None)
                score = (score + (sim / sim.max() if sim.max() > 0 else sim)) / 2
            except Exception:
                pass
        return score

    def _pick(self, order, n: int, kinds, per_unit) -> list[Chunk]:
        out, per = [], {}
        for i in order:
            c = self.items[i]
            if kinds and c.kind not in kinds:
                continue
            if per_unit and c.project_id:
                if per.get(c.project_id, 0) >= per_unit:
                    continue
                per[c.project_id] = per.get(c.project_id, 0) + 1
            out.append(c)
            if len(out) >= n:
                break
        return out

    def search(self, query: str, n: int = 5, kinds=None, per_unit=None, floor: float = 0.3) -> list[Chunk]:
        s = self.scores(query)
        order = [i for i in np.argsort(-s) if s[i] >= floor]
        return self._pick(order, n, kinds, per_unit)

    def close(self, query: str, n: int = 2, kinds=None, min_cos: float = 0.30, per_unit=None) -> list[Chunk]:
        """Records that REALLY match: raw embedding cosine >= `min_cos` (not scaled to the best match, so it can return nothing).
        Calibrated on this corpus: technical-knowledge questions match no practice note above 0.20, genuine method questions never
        fall below 0.37. Without an embedder it falls back to the hybrid ranking with a high floor."""
        vecs = self._vectors()
        if vecs is None or not (query or "").strip():
            return self.search(query, n, kinds=kinds, per_unit=per_unit, floor=0.9)
        sim = vecs @ np.asarray(self.kb.embed([query[:1500]])[0])
        order = [i for i in np.argsort(-sim) if sim[i] >= min_cos]
        return self._pick(order, n, kinds, per_unit)

    def search_multi(self, queries: list[str], n: int = 6, kinds=None, per_unit=2, floor: float = 0.3) -> list[Chunk]:
        """Reciprocal-rank fusion over several queries."""
        fused: dict[int, float] = {}
        for q in queries:
            s = self.scores(q)
            ranked = [i for i in np.argsort(-s) if s[i] >= floor][:12]
            for rank, i in enumerate(ranked):
                fused[i] = fused.get(i, 0.0) + 1.0 / (_RRF_K + rank + 1)
        return self._pick(sorted(fused, key=lambda i: -fused[i]), n, kinds, per_unit)

    # -- structured access used by the agentic tools --------------------------------------------------------------------
    def overview(self) -> list[Chunk]:
        """The best passage of EVERY project / work unit: breadth across the applicant's work rather than depth in one."""
        s = self.scores("what I built, the problem it solved and its result")
        best: dict[str, int] = {}
        for i, c in enumerate(self.items):
            if c.kind == "passage" and (c.project_id not in best or s[i] > s[best[c.project_id]]):
                best[c.project_id] = i
        return [self.items[i] for i in sorted(best.values(), key=lambda i: -s[i])]

    def by_id(self, *ids) -> list[Chunk]:
        want = set(ids)
        return [c for c in self.items if c.id in want]

    def facts(self) -> list[Chunk]:
        """Who the applicant is: current role first, then education (skills are a separate chunk)."""
        order = {"fact:role": 0, "fact:education": 1}
        return sorted((c for c in self.items if c.kind == "fact" and c.id != "fact:skills"), key=lambda c: order.get(c.id, 9))
