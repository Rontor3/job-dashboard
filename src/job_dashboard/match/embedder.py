import hashlib
import math

from job_dashboard.db import jobs_needing_embed_score, upsert_embed_score

# Single source of truth for the embedding model, so a future swap here also
# changes the cache key below and existing scores don't get silently reused
# across incompatible models/vector spaces.
EMBED_MODEL_NAME = "Alibaba-NLP/gte-base-en-v1.5"
EMBED_MODEL_REVISION = "a829fd0e060bb84554da0dfd354d0de0f7712b7f"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _cache_key(profile_hash):
    """Fold the model identity into the cache key so switching models
    invalidates old scores instead of silently mixing vector spaces."""
    return hashlib.sha256(f"{profile_hash}:{EMBED_MODEL_NAME}".encode()).hexdigest()


# Self-attention cost is quadratic in sequence length. A handful of scraped
# descriptions run 10-15k+ chars (~8192+ tokens, the model's own cap) and
# batching even one of those with others blows past available memory (hit a
# 96GB alloc attempt at the full 16344-job scale). Clip to ~3000 tokens'
# worth of chars, which covers a JD's actual substance and stays far above
# the old model's 256-token window, plus keep batches small.
_MAX_CHARS = 6000
_ENCODE_BATCH_SIZE = 4
# upsert_embed_score commits per row, so progress is durable — but
# model.encode() only returns once its whole input list is done, so without
# chunking, one encode() call over all rows means a crash loses everything
# encoded so far. Chunking makes a crash mid-run resume for free next run
# (jobs_needing_embed_score skips whatever already has today's cache_key).
_CHUNK_SIZE = 200


def compute_embed_scores(conn, model, profile_text, profile_hash, on_progress=None):
    """Score every canonical job lacking a current-profile score. Returns count."""
    cache_key = _cache_key(profile_hash)
    rows = jobs_needing_embed_score(conn, cache_key)
    if not rows:
        return 0
    profile_vec = model.encode([profile_text[:_MAX_CHARS]])[0]
    for start in range(0, len(rows), _CHUNK_SIZE):
        chunk = rows[start:start + _CHUNK_SIZE]
        descriptions = [description[:_MAX_CHARS] for _, description in chunk]
        job_vecs = model.encode(descriptions, batch_size=_ENCODE_BATCH_SIZE)
        for (job_id, _), vec in zip(chunk, job_vecs):
            upsert_embed_score(conn, job_id, cosine(profile_vec, vec), cache_key)
        if on_progress:
            on_progress(min(start + _CHUNK_SIZE, len(rows)), len(rows))
    return len(rows)


def load_default_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Install it with: pip3 install sentence-transformers"
        )
    # 8192-token context (vs all-MiniLM-L6-v2's 256) so the full candidate
    # profile is embedded instead of being silently truncated to its first
    # ~250 words. trust_remote_code=True: this model ships custom modeling
    # code from Alibaba-NLP's official repo.
    return SentenceTransformer(
        EMBED_MODEL_NAME, trust_remote_code=True, revision=EMBED_MODEL_REVISION,
    )
