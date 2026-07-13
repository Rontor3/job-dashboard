import math

from job_dashboard.db import jobs_needing_embed_score, upsert_embed_score


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_embed_scores(conn, model, profile_text, profile_hash):
    """Score every canonical job lacking a current-profile score. Returns count."""
    rows = jobs_needing_embed_score(conn, profile_hash)
    if not rows:
        return 0
    profile_vec = model.encode([profile_text])[0]
    descriptions = [description for _, description in rows]
    job_vecs = model.encode(descriptions)
    for (job_id, _), vec in zip(rows, job_vecs):
        upsert_embed_score(conn, job_id, cosine(profile_vec, vec), profile_hash)
    return len(rows)


def load_default_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Install it with: pip3 install sentence-transformers"
        )
    return SentenceTransformer("all-MiniLM-L6-v2")
