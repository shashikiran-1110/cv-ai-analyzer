from __future__ import annotations

import os

MAX_JOBS = 500
MAX_PDF_BYTES = 10 * 1024 * 1024
DETAIL_CONCURRENCY = 5
SEARCH_TTL_SECONDS = 60 * 60
MAX_STORED_SEARCHES = 50
DEFAULT_THRESHOLD = 60

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


def server_key_allowed() -> bool:
    """ROADMAP D13: a server-side AI key is spend anyone who can reach the server can use. Off unless explicitly
    allowed (run.sh allows it because it binds to 127.0.0.1 only)."""
    return os.getenv("ALLOW_SERVER_KEY_ANON", "false").strip().lower() in ("1", "true", "yes")


def ai_provider() -> str | None:
    """'openai' | 'anthropic' | None. AI_PROVIDER forces a choice; otherwise OpenAI wins if both keys are set."""
    if not server_key_allowed():
        return None
    forced = os.getenv("AI_PROVIDER", "").lower()
    if forced == "openai" and os.getenv("OPENAI_API_KEY"):
        return "openai"
    if forced == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def ai_available() -> bool:
    return ai_provider() is not None
