"""Semantic Behavior vault: vector store of past behavioral Q&A + confidence.

Uses ChromaDB with its built-in ONNX embeddings (all-MiniLM-L6-v2, local).
No Ollama, no cloud calls — PII stays on-device.

Confidence lifecycle:
  new entry      → confidence = 0.0
  approve event  → confidence += 1/AUTONOMY_THRESHOLD  (reaches 1.0 after 3)
  edit event     → answer overwritten, confidence reset to 0.0

An entry with confidence >= 1.0 is AUTONOMOUS: the fill node uses it silently
without a Telegram gate. This is the §8 graduated-autonomy hook.
"""
from __future__ import annotations

import hashlib
import re

import chromadb

AUTONOMY_THRESHOLD = 3      # approvals needed to flip a mapping AUTONOMOUS
_MATCH_DISTANCE = 0.85      # cosine distance ceiling; above = no match returned
_COLLECTION = "behavioral_qa"


def _qid(question: str) -> str:
    """Stable, collision-resistant ID for a normalised question text."""
    norm = re.sub(r"\s+", " ", (question or "").strip().lower())
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


class SemanticBehaviorVault:
    """ChromaDB-backed behavioral vault.

    persist_dir=None  → in-memory client (use in tests / one-off runs).
    persist_dir=<path> → durable PersistentClient at that directory.
    """

    def __init__(self, persist_dir: str | None = None):
        if persist_dir:
            self._client = chromadb.PersistentClient(path=persist_dir)
        else:
            self._client = chromadb.Client()
        self._col = self._client.get_or_create_collection(
            _COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    # ── read ──────────────────────────────────────────────────────────────────

    def semantic_match(self, question: str) -> dict | None:
        """Cosine-nearest behavioral answer, or None if nothing is close enough."""
        if self._col.count() == 0:
            return None
        results = self._col.query(query_texts=[question], n_results=1)
        if not results["ids"][0]:
            return None
        distance = results["distances"][0][0]
        if distance > _MATCH_DISTANCE:
            return None
        meta = results["metadatas"][0][0]
        confidence = meta.get("confidence", 0.0)
        return {
            "answer": meta["answer"],
            "confidence": confidence,
            "question": results["documents"][0][0],
            "distance": distance,
            "autonomous": confidence >= 1.0,
        }

    def get(self, question: str) -> dict | None:
        """Direct lookup by exact question (for testing / introspection)."""
        r = self._col.get(ids=[_qid(question)], include=["documents", "metadatas"])
        if not r["ids"]:
            return None
        return {"question": r["documents"][0], **r["metadatas"][0]}

    # ── write ─────────────────────────────────────────────────────────────────

    def record_feedback(self, question: str, answer: str, event: str) -> dict:
        """Record human feedback.

        event='approve' → use answer as-is, increment confidence.
        event='edit'    → overwrite stored answer with human's correction, reset confidence.

        Returns the updated metadata dict.
        """
        if event not in ("approve", "edit"):
            raise ValueError(f"event must be 'approve' or 'edit', got {event!r}")

        qid = _qid(question)
        existing = self._col.get(ids=[qid], include=["metadatas", "documents"])

        if existing["ids"]:
            meta = existing["metadatas"][0]
            approved_count = meta.get("approved_count", 0)
            if event == "approve":
                approved_count += 1
                new_answer = meta["answer"]
            else:
                approved_count = 0
                new_answer = answer
            confidence = min(approved_count / AUTONOMY_THRESHOLD, 1.0)
            new_meta = {
                "answer": new_answer,
                "confidence": confidence,
                "approved_count": approved_count,
            }
        else:
            approved_count = 1 if event == "approve" else 0
            new_meta = {
                "answer": answer,
                "confidence": min(approved_count / AUTONOMY_THRESHOLD, 1.0),
                "approved_count": approved_count,
            }

        self._col.upsert(ids=[qid], documents=[question], metadatas=[new_meta])
        return new_meta
