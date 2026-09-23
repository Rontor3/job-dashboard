"""Memory Access Router — single boundary the LangGraph fill node calls.

memory_access(op, args, router=router) dispatches to one of the three vaults:

  GET_PROFILE_CHUNK(section)                    → Factual Core (static JSON)
  EXACT_TECH_SEARCH(keywords)                   → Exact Tech vault (verbatim source)
  SEMANTIC_MATCH(question)                      → Semantic Behavior (vector + confidence)
  RECORD_FEEDBACK(question, answer, event,      → Semantic Behavior + FTS5 dual-write
                  purpose?)
"""
from __future__ import annotations

_OPS = frozenset({
    "GET_PROFILE_CHUNK",
    "EXACT_TECH_SEARCH",
    "SEMANTIC_MATCH",
    "RECORD_FEEDBACK",
})


def memory_access(op: str, args: dict, *, router: "MemoryRouter") -> object:
    """Thin dispatcher so call sites stay op-string–based (keeps context lean)."""
    if op not in _OPS:
        raise ValueError(f"unknown op {op!r}; valid: {sorted(_OPS)}")
    return router.dispatch(op, args)


class MemoryRouter:
    """Wires the three vaults together and exposes the 4-op interface.

    Parameters
    ----------
    profile       dict loaded by factual_core.load_profile()
    exact_tech    ExactTechVault instance
    semantic      SemanticBehaviorVault instance
    answer_memory AnswerMemory (FTS5) instance — optional; enables dual-write
                  on RECORD_FEEDBACK so the FTS5 fast-path stays in sync
    """

    def __init__(self, *, profile: dict, exact_tech, semantic, answer_memory=None):
        self._profile = profile
        self._exact_tech = exact_tech
        self._semantic = semantic
        self._answer_memory = answer_memory

    def dispatch(self, op: str, args: dict) -> object:
        if op == "GET_PROFILE_CHUNK":
            from ..memory.factual_core import get_profile_chunk
            return get_profile_chunk(self._profile, args["section"])

        if op == "EXACT_TECH_SEARCH":
            return self._exact_tech.search(args["keywords"])

        if op == "SEMANTIC_MATCH":
            return self._semantic.semantic_match(args["question"])

        if op == "RECORD_FEEDBACK":
            question = args["question"]
            answer = args["answer"]
            event = args["event"]           # "approve" | "edit"
            meta = self._semantic.record_feedback(question, answer, event)
            # Dual-write: keep the FTS5 fast-path in sync
            if self._answer_memory is not None:
                from ..browser.form_model import Field
                f = Field(
                    ref="_feedback",
                    kind="text",
                    label=question,
                    required=False,
                    purpose=args.get("purpose"),
                )
                self._answer_memory.record(f, answer)
            return meta

        raise ValueError(f"unhandled op {op!r}")   # unreachable; _OPS gate above
