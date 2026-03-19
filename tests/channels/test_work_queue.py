"""Tests for WorkQueueChannel: exclusive reads, lazy reclaim, acknowledge, nack."""

import time

import pytest

from sssn.channels.work_queue import WorkQueueChannel


@pytest.fixture()
async def queue():
    q = WorkQueueChannel(id="wq", name="Work Queue", description="", claim_timeout=300.0)
    await q.start()
    yield q


async def enqueue(q: WorkQueueChannel, n: int):
    ids = []
    for i in range(n):
        mid = await q.write("producer", {"task": i})
        ids.append(mid)
    return ids


# ---------------------------------------------------------------------------
# read() — exclusive only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exclusive_read_claims_messages(queue: WorkQueueChannel):
    await enqueue(queue, 3)
    msgs = await queue.read("worker-1", limit=2, exclusive=True)
    assert len(msgs) == 2
    for m in msgs:
        assert m.id in queue._store.claims


@pytest.mark.asyncio
async def test_shared_read_raises(queue: WorkQueueChannel):
    await enqueue(queue, 1)
    with pytest.raises(TypeError, match="exclusive"):
        await queue.read("worker-1", exclusive=False)


@pytest.mark.asyncio
async def test_default_exclusive_false_raises(queue: WorkQueueChannel):
    """exclusive defaults to False — WorkQueueChannel must reject this."""
    await enqueue(queue, 1)
    with pytest.raises(TypeError):
        await queue.read("worker-1")


@pytest.mark.asyncio
async def test_claimed_hidden_from_other_workers(queue: WorkQueueChannel):
    await enqueue(queue, 3)
    await queue.read("worker-1", limit=2, exclusive=True)
    msgs = await queue.read("worker-2", limit=10, exclusive=True)
    assert len(msgs) == 1


# ---------------------------------------------------------------------------
# Acknowledge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acknowledge_permanently_removes(queue: WorkQueueChannel):
    await enqueue(queue, 2)
    msgs = await queue.read("worker-1", limit=10, exclusive=True)
    await queue.acknowledge("worker-1", [msgs[0].id])
    # m0 should not reappear after reclaim
    queue._store.reclaim_expired(timeout=0)
    remaining = await queue.read("worker-2", limit=10, exclusive=True)
    ids = [m.id for m in remaining]
    assert msgs[0].id not in ids
    assert msgs[1].id in ids


# ---------------------------------------------------------------------------
# Nack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nack_releases_for_other_worker(queue: WorkQueueChannel):
    await enqueue(queue, 1)
    msgs = await queue.read("worker-1", limit=10, exclusive=True)
    await queue.nack("worker-1", [msgs[0].id])
    available = await queue.read("worker-2", limit=10, exclusive=True)
    assert len(available) == 1
    assert available[0].id == msgs[0].id


@pytest.mark.asyncio
async def test_nack_other_workers_claim_ignored(queue: WorkQueueChannel):
    await enqueue(queue, 1)
    msgs = await queue.read("worker-1", limit=10, exclusive=True)
    await queue.nack("worker-2", [msgs[0].id])  # nack from wrong worker
    # Claim should still be held by worker-1
    assert msgs[0].id in queue._store.claims


# ---------------------------------------------------------------------------
# Lazy reclaim on read()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lazy_reclaim_on_read(queue: WorkQueueChannel):
    await enqueue(queue, 1)
    msgs = await queue.read("worker-1", limit=10, exclusive=True)
    # Manually expire the claim
    queue._store.claims[msgs[0].id] = ("worker-1", time.time() - 99999)
    queue.claim_timeout = 1  # expire after 1 second

    # Next read should trigger reclaim and expose the item again
    available = await queue.read("worker-2", limit=10, exclusive=True)
    assert len(available) == 1
    assert available[0].id == msgs[0].id


# ---------------------------------------------------------------------------
# on_maintain — periodic reclaim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_maintain_reclaims_expired(queue: WorkQueueChannel):
    await enqueue(queue, 1)
    msgs = await queue.read("worker-1", limit=10, exclusive=True)
    # Expire the claim
    queue._store.claims[msgs[0].id] = ("worker-1", time.time() - 99999)
    queue.claim_timeout = 1
    await queue.on_maintain()
    assert msgs[0].id not in queue._store.claims
