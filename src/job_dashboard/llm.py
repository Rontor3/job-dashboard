"""The one LLM client: an OpenAI-compatible Responses API call (``POST {LLM_BASE_URL}/responses``).

Every model call in both halves goes through ``complete`` / ``complete_json``, so swapping the model is env-only:

    LLM_BASE_URL          default http://localhost:11434/v1 (local Ollama); e.g. https://api.openai.com/v1
    LLM_API_KEY           default "ollama" (Ollama ignores it)
    LLM_MODEL             default $OLLAMA_MODEL, else qwen3:14b
    LLM_TIMEOUT           seconds, default 180
    LLM_REASONING_EFFORT  none|low|medium|high; default "none" for local Ollama (no thinking), unset elsewhere
    LLM_NO_TEMPERATURE    1 = never send temperature (models that reject it, e.g. OpenAI reasoning models)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3:14b"

PostFn = Callable[[str, dict], dict]


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float
    reasoning_effort: str | None
    send_temperature: bool

    @property
    def is_local_ollama(self) -> bool:
        u = urlparse(self.base_url)
        return u.hostname in ("localhost", "127.0.0.1", "::1") and u.port == 11434


def config() -> LlmConfig:
    base = (os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    effort = os.getenv("LLM_REASONING_EFFORT")
    cfg = LlmConfig(
        base_url=base,
        api_key=os.getenv("LLM_API_KEY") or "ollama",
        model=os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or DEFAULT_MODEL,
        timeout=float(os.getenv("LLM_TIMEOUT") or 180),
        reasoning_effort=effort or None,
        send_temperature=os.getenv("LLM_NO_TEMPERATURE", "").strip().lower() not in ("1", "true", "yes"),
    )
    if effort is None and cfg.is_local_ollama:
        cfg = LlmConfig(**{**cfg.__dict__, "reasoning_effort": "none"})
    return cfg


def _http_post(cfg: LlmConfig) -> PostFn:
    def post(url: str, body: dict) -> dict:
        import requests  # lazy: only needed for a real call
        r = requests.post(url, json=body, timeout=cfg.timeout,
                          headers={"Authorization": f"Bearer {cfg.api_key}"})
        if r.status_code >= 400:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
        return r.json()
    return post


def build_request(prompt: str, cfg: LlmConfig, *, json_mode: bool = False, temperature: float | None = None,
                  instructions: str | None = None, model: str | None = None) -> dict:
    body: dict = {"model": model or cfg.model, "input": prompt, "store": False}
    if instructions:
        body["instructions"] = instructions
    if temperature is not None and cfg.send_temperature:
        body["temperature"] = temperature
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}
    if cfg.reasoning_effort:
        body["reasoning"] = {"effort": cfg.reasoning_effort}
    return body


def output_text(resp: dict) -> str:
    """The assistant text of a Responses API result (``output_text`` convenience field, else the message parts)."""
    if not isinstance(resp, dict):
        raise ValueError("LLM response is not an object")
    if isinstance(resp.get("output_text"), str):
        return resp["output_text"]
    parts = [c.get("text", "") for item in resp.get("output") or [] if item.get("type") == "message"
             for c in item.get("content") or [] if c.get("type") == "output_text"]
    if not parts:
        raise ValueError(f"LLM response has no output_text (error: {resp.get('error')})")
    return "".join(parts)


def complete(prompt: str, *, json_mode: bool = False, temperature: float | None = None,
             instructions: str | None = None, model: str | None = None, post: PostFn | None = None) -> str:
    """Model text for ``prompt``. Raises on transport/shape errors — callers own their fallback."""
    cfg = config()
    body = build_request(prompt, cfg, json_mode=json_mode, temperature=temperature,
                         instructions=instructions, model=model)
    return output_text((post or _http_post(cfg))(f"{cfg.base_url}/responses", body))


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def parse_json(text: str):
    """JSON from model text, tolerating a ```json fence or prose around the object."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start:end + 1])


def complete_json(prompt: str, **kw) -> dict:
    out = parse_json(complete(prompt, json_mode=True, **kw))
    if not isinstance(out, dict):
        raise ValueError("LLM JSON output is not an object")
    return out
