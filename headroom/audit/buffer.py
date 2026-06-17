"""In-memory async buffer for batch-writing audit logs to Neo4j.

Requests are accumulated in a ``collections.deque`` and flushed in batch
when either 50 entries accumulate or 5 seconds elapse since the last flush.
This keeps audit logging off the hot path — the client response is never
blocked waiting for a Neo4j write.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

log = logging.getLogger("headroom.audit.buffer")

DEFAULT_MAX_SIZE = 5000
DEFAULT_BATCH_SIZE = 50
DEFAULT_FLUSH_INTERVAL = 5.0


class AuditBuffer:
    """Async buffer that flushes batches to a ``store.insert_batch()`` callable.

    Parameters:
        store_insert: Callable ``(list[dict]) -> int`` — typically
            ``AuditStore.insert_batch``.
        max_size: Hard cap on buffer entries. Oldest are dropped when exceeded.
        batch_size: Flush when this many entries accumulate.
        flush_interval_seconds: Flush when this much time has elapsed.
    """

    def __init__(
        self,
        store_insert: Any,
        max_size: int = DEFAULT_MAX_SIZE,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        self._insert = store_insert
        self._max_size = max_size
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._deque: deque[dict[str, Any]] = deque()
        self._task: asyncio.Task | None = None
        self._running = False
        self._drained: list[dict[str, Any]] = []

    def enqueue(self, entry: dict[str, Any]) -> None:
        """Append an entry. Drops the oldest entry with a warning if at capacity."""
        if len(self._deque) >= self._max_size:
            dropped = self._deque.popleft()
            log.warning(
                "audit-buffer: at capacity (%d), dropped oldest entry (user=%s)",
                self._max_size,
                dropped.get("username", "?"),
            )
        self._deque.append(entry)

    async def start(self) -> None:
        """Launch the background flush loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._flush_loop())
        log.info(
            "audit-buffer: started (batch=%d, interval=%.1fs, max=%d)",
            self._batch_size,
            self._flush_interval,
            self._max_size,
        )

    async def stop(self) -> None:
        """Flush remaining entries and cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Final drain
        while self._deque:
            self._drained.append(self._deque.popleft())
        if self._drained:
            await self._do_flush(self._drained)
        log.info("audit-buffer: stopped (%d entries flushed)", len(self._drained))

    async def _flush_loop(self) -> None:
        """Background coroutine: flush on size or time."""
        last_flush = asyncio.get_event_loop().time()
        while self._running:
            elapsed = asyncio.get_event_loop().time() - last_flush
            should_flush = (
                len(self._deque) >= self._batch_size
                or (self._deque and elapsed >= self._flush_interval)
            )
            if should_flush:
                batch = []
                for _ in range(min(len(self._deque), self._batch_size)):
                    batch.append(self._deque.popleft())
                await self._do_flush(batch)
                last_flush = asyncio.get_event_loop().time()
            await asyncio.sleep(0.5)

    async def _do_flush(self, batch: list[dict[str, Any]]) -> None:
        """Write *batch* to Neo4j with one retry."""
        try:
            self._insert(batch)
            log.debug("audit-buffer: flushed %d entries", len(batch))
        except Exception:
            log.warning(
                "audit-buffer: flush failed (%d entries), retrying in 1s...",
                len(batch),
            )
            await asyncio.sleep(1.0)
            try:
                self._insert(batch)
                log.debug("audit-buffer: retry succeeded (%d entries)", len(batch))
            except Exception as exc:
                log.error(
                    "audit-buffer: retry failed, dropping %d entries: %s",
                    len(batch),
                    exc,
                )
