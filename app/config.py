import os

MAX_JOBS = 100
MAX_PDF_BYTES = 10 * 1024 * 1024
DETAIL_CONCURRENCY = 5
SEARCH_TTL_SECONDS = 60 * 60
MAX_STORED_SEARCHES = 50
DEFAULT_THRESHOLD = 60

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")


def ai_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))
