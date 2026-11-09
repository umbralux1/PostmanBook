"""Простой in-process брокер событий для SSE (фаза 2).

Подходит для одного процесса uvicorn. Для нескольких воркеров замените
на Redis pub/sub — интерфейс publish/subscribe останется тем же.
"""

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any


class Broker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))

    def publish(self, topic: str, event: dict[str, Any]) -> int:
        queues = list(self._subscribers.get(topic, ()))
        for q in queues:
            if q.qsize() < 100:
                q.put_nowait(event)
        return len(queues)

    async def subscribe(self, topic: str, heartbeat: float = 15.0) -> AsyncIterator[str]:
        """Генератор строк в формате text/event-stream."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[topic].add(queue)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                data = json.dumps(event, ensure_ascii=False, default=str)
                yield f"event: request\ndata: {data}\n\n"
        finally:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)


broker = Broker()
