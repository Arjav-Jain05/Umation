"""Thread-safe event broadcaster connecting pipeline worker to SSE API consumers."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger("app.core.events")


class Subscriber:
    """Subscriber encapsulation holding queue and associated event loop."""

    def __init__(self, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop) -> None:
        self.queue = queue
        self.loop = loop

    def put_event(self, event_obj: dict[str, Any]) -> None:
        if self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event_obj)


class Broadcaster:
    """Thread-safe in-memory pub/sub broker for job-specific SSE streams."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[Subscriber]] = {}
        self._lock = threading.Lock()

    def publish(self, job_id: str, event: str, data: Any) -> None:
        """Publish an event to all active subscribers for job_id."""
        if not isinstance(data, (dict, list, str, int, float, bool)) and data is not None:
            # If Pydantic model or similar
            if hasattr(data, "model_dump"):
                payload_data = data.model_dump(mode="json")
            else:
                payload_data = str(data)
        else:
            payload_data = data

        payload = {
            "event": event,
            "data": payload_data if isinstance(payload_data, str) else json.dumps(payload_data),
        }

        with self._lock:
            subs = list(self._subscribers.get(job_id, set()))

        for sub in subs:
            try:
                sub.put_event(payload)
            except Exception as e:
                logger.debug("Failed to deliver event to subscriber: %s", e)

    async def subscribe(self, job_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to live events for job_id, yielding formatted event dicts."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        sub = Subscriber(queue, loop)

        with self._lock:
            if job_id not in self._subscribers:
                self._subscribers[job_id] = set()
            self._subscribers[job_id].add(sub)

        try:
            while True:
                item = await queue.get()
                yield item
                queue.task_done()
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            with self._lock:
                if job_id in self._subscribers:
                    self._subscribers[job_id].discard(sub)
                    if not self._subscribers[job_id]:
                        del self._subscribers[job_id]


broadcaster = Broadcaster()
