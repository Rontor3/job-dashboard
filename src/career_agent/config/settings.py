"""Runtime settings for the career agent. Env-overridable, local-first."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PROFILE_DIR = str(
    Path(__file__).resolve().parents[1] / "chrome-profile"
)


@dataclass(frozen=True)
class Settings:
    user_data_dir: str
    headed: bool
    cdp_url: str | None        # e.g. "http://localhost:9222"; None = launch fresh Playwright
    ollama_host: str
    ollama_model: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    remote_solve_port: int
    remote_solve_ttl: int
    remote_solve_allow_public: bool
    tailscale_host: str | None
    rate_limit_domain_day: int
    rate_limit_hour: int
    rate_limit_pace: str


def _as_bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "")


def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE (or export KEY=VALUE) from path without overriding set vars."""
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.removeprefix("export").strip()
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


def load_settings() -> Settings:
    _load_dotenv()
    return Settings(
        user_data_dir=os.getenv("CAREER_AGENT_USER_DATA_DIR", _DEFAULT_PROFILE_DIR),
        headed=_as_bool(os.getenv("CAREER_AGENT_HEADED"), True),
        cdp_url=os.getenv("CAREER_AGENT_CDP_URL") or None,
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        remote_solve_port=int(os.getenv("REMOTE_SOLVE_PORT", "8765")),
        remote_solve_ttl=int(os.getenv("REMOTE_SOLVE_TTL", "300")),
        remote_solve_allow_public=_as_bool(os.getenv("REMOTE_SOLVE_ALLOW_PUBLIC"), False),
        tailscale_host=os.getenv("TAILSCALE_HOST") or None,
        rate_limit_domain_day=int(os.getenv("RATE_LIMIT_DOMAIN_DAY", "5")),
        rate_limit_hour=int(os.getenv("RATE_LIMIT_HOUR", "10")),
        rate_limit_pace=os.getenv("RATE_LIMIT_PACE", "medium"),
    )
