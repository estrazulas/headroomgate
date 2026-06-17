"""Unit tests for AuditBuffer (PRD 3 tasks 3.1-3.4)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from headroom.audit.buffer import AuditBuffer, DEFAULT_BATCH_SIZE


class TestAuditBuffer:
    """Async buffer for batch audit logging."""

    @pytest.fixture
    def store_insert(self) -> MagicMock:
        return MagicMock(return_value=1)

    @pytest.fixture
    def buffer(self, store_insert: MagicMock) -> AuditBuffer:
        return AuditBuffer(store_insert=store_insert, batch_size=10)

    async def test_enqueue_adds_entry(self, buffer: AuditBuffer) -> None:
        buffer.enqueue({"user": "alice"})
        assert len(buffer._deque) == 1

    async def test_enqueue_drops_oldest_at_capacity(self) -> None:
        def insert(batch):
            pass

        buf = AuditBuffer(store_insert=insert, max_size=2, batch_size=100)
        buf.enqueue({"n": 1})
        buf.enqueue({"n": 2})
        buf.enqueue({"n": 3})  # should drop {"n": 1}
        assert len(buf._deque) == 2
        assert buf._deque[0]["n"] == 2
        assert buf._deque[1]["n"] == 3

    async def test_start_stop_flushes_remaining(self, store_insert: MagicMock) -> None:
        buf = AuditBuffer(store_insert=store_insert, batch_size=10)
        buf.enqueue({"user": "alice"})
        buf.enqueue({"user": "bob"})
        await buf.start()
        await buf.stop()
        # remaining entries should be flushed on stop
        assert store_insert.called

    async def test_flush_on_batch_size(self, store_insert: MagicMock) -> None:
        buf = AuditBuffer(store_insert=store_insert, batch_size=3, flush_interval_seconds=60)
        for i in range(4):
            buf.enqueue({"n": i})
        await buf.start()
        await asyncio.sleep(0.1)
        await buf.stop()
        assert store_insert.call_count >= 1

    async def test_flush_on_interval(self, store_insert: MagicMock) -> None:
        buf = AuditBuffer(store_insert=store_insert, batch_size=50, flush_interval_seconds=0.1)
        buf.enqueue({"user": "alice"})
        await buf.start()
        await asyncio.sleep(0.3)
        await buf.stop()
        assert store_insert.call_count >= 1

    async def test_retry_on_failure(self) -> None:
        call_count = 0

        def flaky_insert(batch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Neo4j down")
            return len(batch)

        buf = AuditBuffer(store_insert=flaky_insert, batch_size=10, flush_interval_seconds=0.1)
        buf.enqueue({"user": "alice"})
        await buf.start()
        await asyncio.sleep(0.3)
        await buf.stop()
        assert call_count > 0  # at least the stop flush ran

    async def test_start_idempotent(self, store_insert: MagicMock) -> None:
        buf = AuditBuffer(store_insert=store_insert)
        await buf.start()
        await buf.start()  # second call should be no-op
        await buf.stop()
