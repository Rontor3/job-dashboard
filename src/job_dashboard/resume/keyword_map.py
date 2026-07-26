"""Truthful JD-keyword mapping for resume tailoring.

``propose_rephrasings`` asks an injected ``llm`` to reword existing segment
text so it surfaces a JD keyword the block is genuinely relevant to — never
to invent new tool/skill claims. The prompt to a real LLM implementation
forbids naming any tool/skill/framework absent from the block's own text
(see ``build_prompt``), but the prompt is only a courtesy: this module never
trusts it. Every proposal the injected ``llm`` returns is re-validated in
code by ``_integrity_violation`` before it is allowed to become a
``Rephrasing``. A proposal that fails validation is dropped and its JD
keyword is reported as a ``GapKeyword`` instead.

Honest scope of ``_integrity_violation``: it is a BEST-EFFORT pattern filter
for common fabrication shapes (a fabricated tool token, a known multi-word
product name, a natural-cased proper noun spaced across generic words). It
is NOT a hard guarantee — perfect programmatic detection of "does this
rephrasing claim something the candidate can't back up" is NLI-hard, and an
adversarial or unusually-phrased proposal can still slip past a
regex/whitelist filter (see ``_natural_casing_violation`` for one documented
residual). The filter is one layer of a larger control stack, not the sole
line of defense:

(a) the LLM prompt itself forbids fabrication (``build_prompt``);
(b) this code-side filter catches what the prompt alone wouldn't stop;
(c) — the authoritative control — every ``Rephrasing`` this module produces
    is a proposed diff that requires mandatory human approval before it
    enters the actual resume; nothing here auto-applies to output;
(d) any accepted ``Rephrasing`` with ``confidence == "transferable"`` is
    flagged via ``needs_interview_prep`` so the candidate is prompted to be
    ready to honestly discuss the connection in an interview.
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
    # Connective/attribution words: truthful rephrasings routinely need
    # these to honestly describe HOW an existing (source-backed) tool was
    # used, without themselves naming anything new.
    "used", "via", "leveraging", "leveraged", "across", "within",
    "through", "enabling", "enabled", "reducing", "improving",
    "delivering", "owning", "owned", "utilizing", "incorporating",
    "involved", "working", "involving",
    # Generic (non-product) capability words a TRANSFERABLE rephrasing
    # needs to make a real adjacency explicit — e.g. reframing a
    # candidate's own "multi-agent architecture" bullet as adjacent to a
    # JD's "agent frameworks" ask. None of these name a specific tool,
    # product, or vendor (contrast "agent"/"agents" with "LangChain";
    # "scheduling"/"containerization" describe a capability category, not
    # a product like "Airflow" or "Docker" — those stay source-only via
    # _KNOWN_TOOLS). "orchestration"/"workflow(s)"/"distributed"/
    # "streaming"/"pipelines" were already generic above; only the four
    # below are new.
    "agent", "agents", "scheduling", "containerization",
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

# Trailing punctuation that ``_TOKEN_RE`` glues onto a sentence-final word
# (its continuation class includes "."), e.g. "...agent frameworks." tokenizes
# as "frameworks." — a different string from the whitelist entry
# "frameworks". This carries no semantic content and is unrelated to
# fabrication detection, but left unstripped it makes the whitelist
# over-reject a truthful, already-allowed word for the sole reason that the
# model happened to end a sentence right after it. Stripped symmetrically
# from BOTH the token under test and the source/whitelist comparison sets
# below, so it only removes this false-positive path — it cannot let a real
# fabrication through: "kafka." still normalizes to "kafka", still absent
# from source and from _ALLOWED_GENERIC, so it's still rejected. Internal
# punctuation that IS part of a real tool token ("Node.js", "C++", "CI/CD")
# is untouched — none of those tokens end in one of these characters.
_TRAILING_PUNCT = ".,;:!?"


def _normalize_guard_token(token: str) -> str:
    return token.lower().rstrip(_TRAILING_PUNCT)

# A run of 2+ consecutive Capitalized (or ALL-CAPS) words in ORIGINAL
# casing — the shape a resume actually uses for a multi-word proper noun:
# "Elastic Search", "Cloud Search", "Big Query", "Vertex AI".
_CAP_WORD_RUN_RE = re.compile(r"[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)+")

# A token with an internal lower->upper case transition — the shape of a
# CamelCase / internal-caps product name: "BigQuery", "PyTorch",
# "LangChain". Pure acronyms ("AWS", "API", "SQL") have no such
# transition and are not matched.
_CAMEL_CASE_RE = re.compile(r"[a-z][A-Z]")


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


def _natural_casing_violation(proposed_text: str, source_text: str) -> bool:
    """Catches a proper-noun tool spelled the way resumes actually write it.

    Closes a STRUCTURAL gap the token-whitelist in ``_integrity_violation``
    can't see: a real tool made of two ordinary-looking words spaced apart
    ("Elastic Search" for Elasticsearch, "Cloud Search" for AWS
    CloudSearch) passes that whitelist because each word, on its own, is
    generic English already in ``_ALLOWED_GENERIC`` — and ``_KNOWN_TOOLS``
    only has an entry for the contiguous form, not the spaced one.

    Unlike ``_integrity_violation``, this checks ``proposed_text`` in its
    ORIGINAL casing (not lowercased) for the visual shape a proper noun
    takes on a resume:

    (a) a run of 2+ consecutive Capitalized/ALL-CAPS words
        ("Elastic Search", "Cloud Search", "Big Query", "Vertex AI"), or
    (b) a single CamelCase / internal-caps token
        ("BigQuery", "PyTorch", "LangChain").

    Either shape is a violation unless that same phrase/token also appears
    (case-insensitively) in the block's own ``source_text`` — i.e. the
    candidate's resume genuinely already names it.

    Documented accepted residual: an ALL-LOWERCASE spaced tool name
    ("elastic search", no capitals at all) still slips past both this
    check and the whitelist. That casing is not how a human actually
    writes a tool name on a resume — it is an adversarial-only input, not
    a realistic fabrication path — and closing it would mean banning
    ordinary lowercase word pairs outright, which is not worth the
    false-positive cost. See the module docstring: this function is one
    layer of a best-effort filter, not a hard guarantee.
    """
    for match in _CAP_WORD_RUN_RE.findall(proposed_text):
        words = match.split()
        pattern = re.compile(
            r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b", re.IGNORECASE
        )
        if not pattern.search(source_text):
            return True

    source_tokens_lower = {
        _normalize_guard_token(t) for t in _TOKEN_RE.findall(source_text)
    }
    for token in _TOKEN_RE.findall(proposed_text):
        if not _CAMEL_CASE_RE.search(token):
            continue
        word = _normalize_guard_token(token)
        if word in source_tokens_lower or word in _ALLOWED_GENERIC:
            continue
        return True

    return False


def _integrity_violation(proposed_text: str, source_text: str) -> bool:
    """True if ``proposed_text`` introduces content the source can't back up.

    BEST-EFFORT filter, not a hard guarantee — see the module docstring
    for the full control stack this is one layer of. Perfect programmatic
    detection of "did this rephrasing invent a claim" is NLI-hard; this is
    pattern-based defense in depth, not a proof.

    Three checks, in order:

    1. Whitelist model, not a classifier: EVERY token in ``proposed_text``
       is tokenized and lowercased, then must be either (a) present in the
       block's own ``source_text`` tokens (case-insensitive), or (b)
       generic resume/tech English (``_ALLOWED_GENERIC``). Anything else
       is an unverifiable specific claim and the whole proposal is
       rejected. Being case-insensitive by construction, this catches a
       fabricated lowercase tool name ("kafka") exactly like a
       capitalized one ("Kafka").
    2. A second, independent check nets multi-word product names whose
       component words might each look individually generic ("Big Query"
       -> "big" + "query"): any ``_KNOWN_TOOLS`` phrase found in
       ``proposed_text`` but absent from ``source_text`` is a violation
       regardless of how its words classify on their own.
    3. ``_natural_casing_violation`` nets the residual gap in (1)+(2):
       a real tool spelled as natural-cased spaced generic words that
       aren't a literal ``_KNOWN_TOOLS`` entry ("Elastic Search", "Cloud
       Search") — see that function's docstring for what's still not
       covered.

    Bias is conservative — over-reject rather than let a fabrication
    through — but "reject" here means "route to interview-prep-flagged
    human review or a GapKeyword," not "impossible to fabricate."
    """
    source_tokens_lower = {
        _normalize_guard_token(t) for t in _TOKEN_RE.findall(source_text)
    }
    for token in _TOKEN_RE.findall(proposed_text):
        word = _normalize_guard_token(token)
        if word in source_tokens_lower or word in _ALLOWED_GENERIC:
            continue
        return True

    proposed_lower = proposed_text.lower()
    source_lower = source_text.lower()
    for _phrase, pattern in _KNOWN_TOOL_PATTERNS:
        if pattern.search(proposed_lower) and not pattern.search(source_lower):
            return True

    if _natural_casing_violation(proposed_text, source_text):
        return True

    return False


def _covered_keywords(segments: list[Segment], jd_keywords: list[str]) -> set[str]:
    """JD keywords already present verbatim in some segment's own text.

    Comparison is case-insensitive so a caller-supplied keyword (e.g. a
    stored deep-rank gap like ``"Kubernetes"``) still matches the
    lowercased tokens ``extract_keywords`` produces from segment text,
    while the keyword itself is returned in its original casing.
    """
    all_tokens: set[str] = set()
    for seg in segments:
        all_tokens |= set(extract_keywords(seg.text))
    return {kw for kw in jd_keywords if kw.lower() in all_tokens}


def propose_rephrasings(
    segments: list[Segment],
    jd_text: str,
    deep_rank: DeepRankFn,
    llm: LlmFn | None = None,
    keywords: list[str] | None = None,
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

    ``keywords``, when given, REPLACES the crude ``extract_keywords(jd_text)``
    tokenization as the salient-keyword source (e.g. a job's stored
    deep-rank ``gaps`` — real tech terms rather than raw JD stopwords).
    Falls back to ``extract_keywords(jd_text)`` when ``None`` or empty.

    The ``llm`` call is wrapped: any exception it raises (e.g. Ollama
    unreachable) is treated the same as it returning no proposals — every
    JD keyword becomes a gap instead of the whole call failing.
    """
    deep_rank(segments, jd_text)  # computed for real-llm prioritization; not required for the guard

    seg_by_id = {seg.id: seg for seg in segments}
    jd_keywords = list(keywords) if keywords else extract_keywords(jd_text)
    covered = _covered_keywords(segments, jd_keywords)

    if llm is None:
        return [GapKeyword(kw) for kw in jd_keywords if kw not in covered]

    try:
        proposals = llm(segments, jd_text)
    except Exception:
        # Ollama down/unreachable or any other llm failure -> no proposals,
        # every uncovered keyword falls through to the gap loop below.
        proposals = []

    results: list[Rephrasing | GapKeyword] = []
    resolved: set[str] = set()  # keywords with >=1 accepted Rephrasing
    attempted: set[str] = set()  # keywords the llm tried (accepted or rejected)

    for proposal in proposals:
        attempted.add(proposal.jd_keyword)
        seg = seg_by_id.get(proposal.block_id)

        if (
            seg is None
            or not proposal.proposed_text.strip()
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
