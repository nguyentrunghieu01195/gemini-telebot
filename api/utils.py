"""Small, dependency-free helpers shared by production code and tests."""

from __future__ import annotations


TELEGRAM_TEXT_LIMIT = 4096


def split_telegram_text(text: str, limit: int = 4000) -> list[str]:
    """Split text without exceeding Telegram's message length limit."""
    if not text:
        return [""]
    if limit < 1 or limit > TELEGRAM_TEXT_LIMIT:
        raise ValueError("limit must be between 1 and 4096")

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at < 1:
            split_at = limit

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    if remaining or not chunks:
        chunks.append(remaining)
    return chunks
