"""Tests for MessageStore: shared reads, exclusive reads, acknowledge, nack, reclaim."""

import time

import pytest

from sssn.core.channel import ChannelMessage, GenericContent, MessageStore


def make_msg(id: str, sender: str = "sys-a") -> ChannelMessage:
    return ChannelMessage(
        id=id,
        timestamp=time.time(),
        sender_id=sender,
        content=GenericContent(data=id),
    )


@pytest.fixture()
def store() -> MessageStore:
    s = MessageStore()
    s.append(make_msg("m1"))
    s.append(make_msg("m2"))
    s.append(make_msg("m3"))
    return s


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------


def test_shared_read_returns_all(store: MessageStore):
    msgs = store.read_shared("reader-a", limit=10, after=None)
    assert [m.id for m in msgs] == ["m1", "m2", "m3"]


def test_shared_read_respects_limit(store: MessageStore):
    msgs = store.read_shared("reader-a", limit=2, after=None)
    assert len(msgs) == 2
    assert msgs[0].id == "m1"


def test_shared_read_advances_cursor(store: MessageStore):
    store.read_shared("reader-a", limit=2, after=None)
    msgs = store.read_shared("reader-a", limit=10, after=None)
    assert [m.id for m in msgs] == ["m3"]


def test_shared_read_after_override(store: MessageStore):
    msgs = store.read_shared("reader-a", limit=10, after="m1")
    assert [m.id for m in msgs] == ["m2", "m3"]


def test_shared_read_skips_claimed(store: MessageStore):
    store.read_exclusive("claimer", 1)  # claims m1
    msgs = store.read_shared("reader-a", limit=10, after=None)
    assert [m.id for m in msgs] == ["m2", "m3"]


def test_shared_read_skips_acknowledged(store: MessageStore):
    store.acknowledge("any", ["m2"])
    msgs = store.read_shared("reader-a", limit=10, after=None)
    assert [m.id for m in msgs] == ["m1", "m3"]


def test_shared_read_independent_cursors(store: MessageStore):
    store.read_shared("reader-a", limit=2, after=None)
    msgs_b = store.read_shared("reader-b", limit=10, after=None)
    assert [m.id for m in msgs_b] == ["m1", "m2", "m3"]


# ---------------------------------------------------------------------------
# Exclusive reads
# ---------------------------------------------------------------------------


def test_exclusive_read_claims_messages(store: MessageStore):
    msgs = store.read_exclusive("worker-1", 2)
    assert len(msgs) == 2
    assert "m1" in store.claims
    assert "m2" in store.claims
    assert store.claims["m1"][0] == "worker-1"


def test_exclusive_read_hides_claimed_from_others(store: MessageStore):
    store.read_exclusive("worker-1", 2)
    msgs = store.read_exclusive("worker-2", 10)
    assert len(msgs) == 1
    assert msgs[0].id == "m3"


def test_exclusive_read_skips_acknowledged(store: MessageStore):
    store.acknowledge("any", ["m1"])
    msgs = store.read_exclusive("worker-1", 10)
    assert len(msgs) == 2
    assert "m1" not in [m.id for m in msgs]


# ---------------------------------------------------------------------------
# Acknowledge
# ---------------------------------------------------------------------------


def test_acknowledge_removes_claim(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    store.acknowledge("worker-1", ["m1"])
    assert "m1" not in store.claims
    assert "m1" in store.acknowledged


def test_acknowledge_makes_invisible_to_exclusive(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    store.acknowledge("worker-1", ["m1"])
    msgs = store.read_exclusive("worker-2", 10)
    assert "m1" not in [m.id for m in msgs]


# ---------------------------------------------------------------------------
# Nack
# ---------------------------------------------------------------------------


def test_nack_releases_claim(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    assert "m1" in store.claims
    store.nack("worker-1", ["m1"])
    assert "m1" not in store.claims


def test_nack_makes_available_again(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    store.nack("worker-1", ["m1"])
    msgs = store.read_exclusive("worker-2", 10)
    assert "m1" in [m.id for m in msgs]


def test_nack_only_releases_own_claims(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    # worker-2 tries to nack worker-1's claim — should be a no-op
    store.nack("worker-2", ["m1"])
    assert "m1" in store.claims


# ---------------------------------------------------------------------------
# Reclaim expired
# ---------------------------------------------------------------------------


def test_reclaim_expired_removes_old_claims(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    # Force the claim time to be very old
    store.claims["m1"] = ("worker-1", time.time() - 1000)
    store.reclaim_expired(timeout=60)
    assert "m1" not in store.claims


def test_reclaim_expired_leaves_fresh_claims(store: MessageStore):
    store.read_exclusive("worker-1", 1)
    store.reclaim_expired(timeout=60)
    assert "m1" in store.claims


# ---------------------------------------------------------------------------
# Subscriber notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_subscribers_called():
    store = MessageStore()
    received = []

    async def cb(msg: ChannelMessage):
        received.append(msg.id)

    store.subscribers["sys-a"] = cb
    msg = make_msg("m-notify")
    store.append(msg)
    await store.notify_subscribers(msg)
    assert received == ["m-notify"]


@pytest.mark.asyncio
async def test_notify_subscribers_exception_isolation():
    """A failing subscriber should not prevent others from being called."""
    store = MessageStore()
    called = []

    async def bad_cb(msg):
        raise RuntimeError("boom")

    async def good_cb(msg):
        called.append(msg.id)

    store.subscribers["bad"] = bad_cb
    store.subscribers["good"] = good_cb
    msg = make_msg("m-iso")
    await store.notify_subscribers(msg)
    assert called == ["m-iso"]


# ---------------------------------------------------------------------------
# Host operations
# ---------------------------------------------------------------------------


def test_clear_all(store: MessageStore):
    store.clear()
    assert store.messages == []
    assert store.claims == {}
    assert store.acknowledged == set()


def test_clear_with_filter(store: MessageStore):
    store.clear(lambda m: m.id == "m2")
    assert [m.id for m in store.messages] == ["m1", "m3"]


def test_evict_by_age(store: MessageStore):
    # Give m1 an old timestamp
    old = ChannelMessage(
        id="old-msg",
        timestamp=1.0,
        sender_id="sys-a",
        content=GenericContent(data="old"),
    )
    store.append(old)
    store.evict(before=time.time() - 1)
    ids = [m.id for m in store.messages]
    assert "old-msg" not in ids


def test_evict_by_count(store: MessageStore):
    store.evict(max_count=2)
    assert len(store.messages) == 2
    assert store.messages[0].id == "m2"
    assert store.messages[1].id == "m3"


def test_remove_by_id(store: MessageStore):
    store.remove(["m1", "m3"])
    assert [m.id for m in store.messages] == ["m2"]
