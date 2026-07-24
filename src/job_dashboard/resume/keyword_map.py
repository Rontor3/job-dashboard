"""Truthful JD-keyword mapping for resume tailoring.

``propose_rephrasings`` asks an injected ``llm`` to reword existing segment
text so it surfaces a JD keyword the block is genuinely relevant to — never
to invent new tool/skill claims. The prompt to a real LLM implementation
forbids naming any tool/skill/framework absent from the block's own text
(see ``build_prompt``), but the prompt is only a courtesy: this module never
trusts it. Every proposal the injected ``llm`` returns is re-validated in
code by ``_integrity_violation`` before it is allowed to become a
``Rephrasing``. A proposal that fails validation is dropped and its JD
keyword is reported as a ``GapKeyword`` instead — a fabricated claim never
reaches the resume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from job_dashboard.resume.segments import Segment

VALID_CONFIDENCE = {"exact-synonym", "equivalent", "transferable"}

# Generic English stopwords stripped out of keyword extraction — deliberately
# small; the goal is salient-term overlap, not full NLP.
_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will",
    "have", "has", "this", "that", "from", "who", "can", "job", "role",
    "work", "team", "years", "year", "experience", "ability", "strong",
    "using", "into", "about", "such", "than", "they", "them", "their",
    "not", "all", "any", "able", "well", "including", "etc", "per",
    "plus", "must", "should", "would", "could", "may", "also", "new",
    "one", "two", "more", "most", "other", "some", "each", "which",
    "what", "when", "where", "how", "why", "then", "there", "here",
    "in", "is", "of", "to", "on", "as", "an", "be", "or", "at", "by",
    "it", "we",
}

# Tokens made of letters plus tool-ish punctuation (C++, Node.js, CI/CD, ...).
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./_-]*")

# Generic resume/tech English a rephrasing may freely use even when the word
# isn't literally in the block's own source text — deliberately generous but
# strictly GENERIC: no specific tool, product, or vendor proper nouns belong
# here (those go in _KNOWN_TOOLS, or must come from the source text itself).
_ALLOWED_GENERIC = _STOPWORDS | {
    "system", "systems", "production", "pipeline", "pipelines", "model",
    "models", "data", "engineering", "engineer", "engineers", "built",
    "build", "builds", "building", "developed", "developing", "develop",
    "design", "designed", "designing", "scalable", "distributed", "real",
    "time", "retrieval", "orchestration", "embedding", "embeddings",
    "inference", "training", "train", "trained", "deployment", "deploy",
    "deployed", "serving", "serve", "served", "api", "apis", "cloud",
    "backend", "frontend", "services", "service", "platform", "platforms",
    "automation", "automate", "automated", "analysis", "analyze",
    "analyzed", "learning", "machine", "deep", "neural", "language",
    "natural", "processing", "process", "processed", "vector", "vectors",
    "search", "searching", "semantic", "framework", "frameworks",
    "libraries", "library", "tools", "tool", "based", "architecture",
    "architected", "application", "applications", "software", "code",
    "coding", "algorithm", "algorithms", "database", "databases",
    "server", "servers", "network", "networks", "security", "testing",
    "test", "tests", "quality", "performance", "scale", "scalability",
    "reliability", "availability", "monitoring", "monitor", "monitored",
    "logging", "log", "logs", "metrics", "workflow", "workflows",
    "feature", "features", "module", "modules", "component", "components",
    "interface", "interfaces", "user", "users", "customer", "customers",
    "product", "products", "project", "projects", "stakeholders",
    "requirements", "solution", "solutions", "technical", "technology",
    "technologies", "tech", "stack", "full", "cross", "functional",
    "agile", "integration", "integrations", "delivery", "continuous",
    "devops", "ci", "cd", "event", "events", "streaming", "stream",
    "streams", "queue", "queues", "message", "messages", "messaging",
    "storage", "store", "stored", "compute", "container", "containers",
    "microservice", "microservices", "rest", "restful", "json", "xml",
    "http", "https", "web", "app", "apps", "mobile", "desktop", "script",
    "scripts", "scripting", "optimize", "optimized", "optimization",
    "improve", "improved", "improvement", "reduce", "reduced", "increase",
    "increased", "deliver", "delivered", "implement", "implemented",
    "manage", "managed", "lead", "led", "create", "created", "collaborate",
    "collaborated", "maintain", "maintained", "support", "supported",
    "high", "low", "level", "key", "core", "end", "multi", "primary",
    "secondary", "query", "queries", "serverless", "asynchronous",
    "synchronous", "concurrent", "concurrency", "parallel",
    "parallelism", "fault", "tolerant", "tolerance", "elastic",
    "elasticity", "horizontal", "vertical", "caching", "cache",
    "cached", "batch", "batches", "scheduled", "scheduler",
    "reactive", "resilient", "resiliency", "observability", "tracing",
    "trace", "alerting", "alert", "alerts", "dashboard", "dashboards",
    "visualization", "reporting", "warehouse", "warehousing",
    "governance", "compliance", "encryption", "encrypted",
    "authentication", "authorization", "auth", "token", "tokens",
    "session", "sessions", "endpoint", "endpoints", "schema",
    "schemas", "index", "indexes", "indexing", "transaction",
    "transactions", "throughput", "latency", "uptime", "cluster",
    "clusters", "clustering", "node", "nodes", "replication",
    "replica", "replicas", "backup", "backups", "recovery",
    "migration", "migrations", "migrate", "migrated", "versioning",
    "release", "releases", "rollback", "infrastructure", "infra",
    "provisioning", "provisioned", "networking", "autoscaling",
    "scaling", "scaled", "staging", "environment", "environments",
    "configuration",
}

# Known specific tool / product / vendor names, as phrases (space-separated
# for multi-word names). Case-insensitive substring net: if any of these
# appears in a proposed rephrasing's text but NOT in the block's own source
# text, that's a fabricated specific claim — even when every individual
# word in the phrase happens to look generic on its own (e.g. "Big Query").
_KNOWN_TOOLS = (
    "kafka", "langchain", "llamaindex", "llama index", "bigquery",
    "big query", "postgres", "postgresql", "spark", "airflow",
    "snowflake", "databricks", "kubernetes", "terraform", "tensorflow",
    "pytorch", "hadoop", "redis", "mongodb", "elasticsearch", "tableau",
    "powerbi", "power bi", "sagemaker", "vertex ai", "docker", "jenkins",
    "grafana", "prometheus", "kibana", "cassandra", "dynamodb",
    "rabbitmq", "mysql", "sqlite", "nginx", "react", "angular", "vue",
    "django", "flask", "fastapi", "numpy", "pandas", "scikit-learn",
    "sklearn", "keras", "opencv", "graphql", "jupyter", "matlab",
    "scala", "golang", "node.js", "nodejs", "express", "spring",
    "hibernate", "openai", "chatgpt", "gemini", "anthropic",
    "hugging face", "huggingface", "pinecone", "weaviate", "milvus",
    "qdrant", "faiss", "chroma", "chromadb",
)

_KNOWN_TOOL_PATTERNS = [
    (
        phrase,
        re.compile(r"\b" + r"\s+".join(re.escape(p) for p in phrase.split(" ")) + r"\b"),
    )
    for phrase in _KNOWN_TOOLS
]


@dataclass
class Rephrasing:
    block_id: str
    original_text: str
    proposed_text: str
    jd_keyword: str
    confidence: str  # exact-synonym | equivalent | transferable
    needs_interview_prep: bool


@dataclass
class GapKeyword:
    jd_keyword: str


@dataclass
class LlmProposal:
    """One raw proposal returned by an injected ``llm``, not yet validated."""

    block_id: str
    jd_keyword: str
    proposed_text: str
    confidence: str


LlmFn = Callable[[list[Segment], str], list[LlmProposal]]
DeepRankFn = Callable[[list[Segment], str], dict[str, float]]


def extract_keywords(text: str) -> list[str]:
    """Lowercase, deduped (order-preserving) salient tokens from ``text``."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for match in _TOKEN_RE.findall(text):
        word = match.lower()
        if len(word) < 3 or word in _STOPWORDS or word in seen_set:
            continue
        seen_set.add(word)
        seen.append(word)
    return seen


def simple_deep_rank(segments: list[Segment], jd_text: str) -> dict[str, float]:
    """Deterministic, network-free relevance score per segment.

    Score = number of JD keyword tokens also found in the segment's own
    text or tags. A placeholder for a real embedding-based deep-rank; good
    enough to drive exclusive-group tie-breaks and tests without a model.
    """
    jd_tokens = set(extract_keywords(jd_text))
    scores: dict[str, float] = {}
    for seg in segments:
        seg_tokens = set(extract_keywords(seg.text)) | {t.lower() for t in seg.tags}
        scores[seg.id] = float(len(jd_tokens & seg_tokens))
    return scores


def build_prompt(segment: Segment, jd_text: str) -> str:
    """Documentary prompt for a real ``llm`` implementation.

    Not parsed or trusted by this module — ``_integrity_violation`` is the
    actual enforcement. Kept here so the instruction a real LLM call sends
    is visible and testable independently of the code-side guard.
    """
    return (
        "You are rewording ONE resume bullet to surface a job-description "
        "keyword. You may ONLY use words, tools, and phrases that already "
        "appear in the bullet's own text below. Do NOT name any tool, "
        "skill, framework, or technology that is not already present in "
        "that text, even if the job description mentions it.\n\n"
        f"Bullet text:\n{segment.text}\n\n"
        f"Job description:\n{jd_text}\n\n"
        "Return a JSON object: block_id, jd_keyword, proposed_text, "
        "confidence (one of exact-synonym, equivalent, transferable)."
    )


def _integrity_violation(proposed_text: str, source_text: str) -> bool:
    """True if ``proposed_text`` introduces content the source can't back up.

    Whitelist model, not a classifier: EVERY token in ``proposed_text`` is
    tokenized and lowercased, then must be either (a) present in the
    block's own ``source_text`` tokens (case-insensitive), or (b) generic
    resume/tech English (``_ALLOWED_GENERIC``). Anything else is an
    unverifiable specific claim and the whole proposal is rejected. Being
    case-insensitive by construction, this catches a fabricated lowercase
    tool name ("kafka") exactly like a capitalized one ("Kafka") — the
    previous capitalized/digit-shape classifier missed lowercase entirely.

    A second, independent check nets multi-word product names whose
    component words might each look individually generic ("Big Query" ->
    "big" + "query"): any ``_KNOWN_TOOLS`` phrase found in ``proposed_text``
    but absent from ``source_text`` is a violation regardless of how its
    words classify on their own. This is the hard backstop: it runs
    regardless of what the llm claims, so a fabricated tool name can never
    reach a ``Rephrasing``. Bias is conservative — over-reject rather than
    let a fabrication through.
    """
    source_tokens_lower = {t.lower() for t in _TOKEN_RE.findall(source_text)}
    for token in _TOKEN_RE.findall(proposed_text):
        word = token.lower()
        if word in source_tokens_lower or word in _ALLOWED_GENERIC:
            continue
        return True

    proposed_lower = proposed_text.lower()
    source_lower = source_text.lower()
    for _phrase, pattern in _KNOWN_TOOL_PATTERNS:
        if pattern.search(proposed_lower) and not pattern.search(source_lower):
            return True

    return False


def _covered_keywords(segments: list[Segment], jd_keywords: list[str]) -> set[str]:
    """JD keywords already present verbatim in some segment's own text."""
    all_tokens: set[str] = set()
    for seg in segments:
        all_tokens |= set(extract_keywords(seg.text))
    return {kw for kw in jd_keywords if kw in all_tokens}


def propose_rephrasings(
    segments: list[Segment],
    jd_text: str,
    deep_rank: DeepRankFn,
    llm: LlmFn | None = None,
) -> list[Rephrasing | GapKeyword]:
    """Truthfully map JD keywords onto existing segment text, or report gaps.

    ``deep_rank(segments, jd_text)`` is computed (available for a real llm
    implementation to prioritize which blocks to reword; unused directly
    here beyond that contract). ``llm(segments, jd_text) -> list[LlmProposal]``
    is the injected model call — ``None`` means no rewording is attempted
    and every uncovered JD keyword is reported as a gap. Every proposal the
    llm returns is validated against the block's own source text before it
    is trusted; anything that fails validation becomes a ``GapKeyword``
    instead of a ``Rephrasing``.
    """
    deep_rank(segments, jd_text)  # computed for real-llm prioritization; not required for the guard

    seg_by_id = {seg.id: seg for seg in segments}
    jd_keywords = extract_keywords(jd_text)
    covered = _covered_keywords(segments, jd_keywords)

    if llm is None:
        return [GapKeyword(kw) for kw in jd_keywords if kw not in covered]

    proposals = llm(segments, jd_text)

    results: list[Rephrasing | GapKeyword] = []
    resolved: set[str] = set()  # keywords with >=1 accepted Rephrasing
    attempted: set[str] = set()  # keywords the llm tried (accepted or rejected)

    for proposal in proposals:
        attempted.add(proposal.jd_keyword)
        seg = seg_by_id.get(proposal.block_id)

        if (
            seg is None
            or proposal.confidence not in VALID_CONFIDENCE
            or _integrity_violation(proposal.proposed_text, seg.text)
        ):
            # Rejected proposal. Only surface it as a gap if the keyword
            # isn't already truthfully present elsewhere in source text —
            # a rejected reword of an already-covered term isn't a gap.
            if proposal.jd_keyword not in covered:
                results.append(GapKeyword(proposal.jd_keyword))
            continue

        results.append(
            Rephrasing(
                block_id=proposal.block_id,
                original_text=seg.text,
                proposed_text=proposal.proposed_text,
                jd_keyword=proposal.jd_keyword,
                confidence=proposal.confidence,
                needs_interview_prep=(proposal.confidence == "transferable"),
            )
        )
        resolved.add(proposal.jd_keyword)

    for kw in jd_keywords:
        if kw in covered or kw in resolved or kw in attempted:
            continue
        results.append(GapKeyword(kw))

    return results
