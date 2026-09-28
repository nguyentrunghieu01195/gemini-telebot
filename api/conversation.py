"""Thread-safe, bounded conversation history for one serverless instance."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Hashable


class ConversationMemory:
    def __init__(self, max_messages: int = 16, max_characters: int = 24_000):
        if max_messages < 2 or max_characters < 1:
            raise ValueError("Conversation limits must be positive")
        self.max_messages = max_messages
        self.max_characters = max_characters
        self._histories: dict[Hashable, deque[dict[str, object]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> list[dict[str, object]]:
        """Return a copy suitable for passing to the Gemini SDK."""
        with self._lock:
            return [
                {"role": item["role"], "parts": [{"text": item["parts"][0]["text"]}]}
                for item in self._histories.get(key, ())
            ]

    def add_exchange(self, key: Hashable, user_text: str, model_text: str) -> None:
        with self._lock:
            history = self._histories[key]
            history.append({"role": "user", "parts": [{"text": user_text}]})
            history.append({"role": "model", "parts": [{"text": model_text}]})
            self._trim(history)

    def clear(self, key: Hashable) -> bool:
        with self._lock:
            return self._histories.pop(key, None) is not None

    def _trim(self, history: deque[dict[str, object]]) -> None:
        def character_count() -> int:
            return sum(len(item["parts"][0]["text"]) for item in history)

        # Remove complete user/model exchanges so roles stay correctly paired.
        while len(history) > self.max_messages or character_count() > self.max_characters:
            history.popleft()
            if history:
                history.popleft()
