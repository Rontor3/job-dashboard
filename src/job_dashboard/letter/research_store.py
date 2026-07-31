"""Group a ResearchBundle into per-source Resources for user curation.

Pure logic: one Resource per unique source_url, the URL's top 1-2 fact texts
joined as its summary, order preserving the bundle's existing fact ranking,
capped at _MAX_RESOURCES. No I/O, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

from job_dashboard.letter.company_research import ResearchBundle

_MAX_RESOURCES = 6
_MAX_SUMMARY_CHARS = 240
_MAX_FACTS_PER_SOURCE = 2


@dataclass
class Resource:
    source_url: str
    title: str
    summary: str


def _host(url: str) -> str:
    host = (url or "").split("//", 1)[-1].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


def resources_from_bundle(bundle: ResearchBundle) -> list[Resource]:
    facts = getattr(bundle, "facts", None) or []
    by_url: dict[str, list[str]] = {}
    order: list[str] = []
    for f in facts:
        url = getattr(f, "source_url", "") or ""
        text = getattr(f, "text", "") or ""
        if not url or not text:
            continue
        if url not in by_url:
            by_url[url] = []
            order.append(url)
        by_url[url].append(text)

    resources: list[Resource] = []
    for url in order[:_MAX_RESOURCES]:
        summary = " … ".join(by_url[url][:_MAX_FACTS_PER_SOURCE])[:_MAX_SUMMARY_CHARS]
        resources.append(Resource(source_url=url, title=_host(url), summary=summary))
    return resources
