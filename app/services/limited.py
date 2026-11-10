"""Учебный rate limit для `GET /api/limited`: N запросов за окно на ученика.

Ключ — код из `X-Student-Id`, без него — IP клиента. Скользящее окно в памяти
процесса (один процесс uvicorn, см. AGENTS.md). Это не защита сервера (её делает
slowapi), а учебный эндпоинт: ученик должен увидеть 429 и `Retry-After`.
"""

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

LIMIT = 3
WINDOW_SECONDS = 10


@dataclass
class Decision:
    allowed: bool
    remaining: int
    retry_after: int  # секунд до освобождения места (0, если разрешено)


class SlidingWindow:
    def __init__(
        self,
        limit: int = LIMIT,
        window: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> Decision:
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = max(1, math.ceil(hits[0] + self.window - now))
            return Decision(False, 0, retry)
        hits.append(now)
        self._cleanup(now)
        return Decision(True, self.limit - len(hits), 0)

    def _cleanup(self, now: float) -> None:
        if len(self._hits) < 1000:
            return
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


window = SlidingWindow()
