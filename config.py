"""Configurable initial implementation choices for QnaGen."""

import os


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return value


MAX_FILE_MB = _positive_int("QNAGEN_MAX_FILE_MB", 20)
UPLOAD_LIMITS_VERSION = 2
MAX_COMBINED_PAGES = _positive_int("QNAGEN_MAX_PAGES", 600)
CHUNK_CHARS = _positive_int("QNAGEN_CHUNK_CHARS", 6000)
MAX_CHUNKS = _positive_int("QNAGEN_MAX_CHUNKS", 8)
MAX_RETRIES = _positive_int("QNAGEN_MAX_RETRIES", 2)
OLLAMA_MODEL = "qwen3.5:9b"
MAX_QUESTIONS = 15
