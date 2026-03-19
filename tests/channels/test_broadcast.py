"""Tests for BroadcastChannel: fan-out, shared reads, exclusive raises TypeError."""

import pytest

from sssn.channels.broadcast import BroadcastChannel
from sssn.core.channel import ChannelMessage


@pytest.fixture()
async def channel():
    ch = BroadcastChannel(id="bc", name="Broadcast", description="test")
    await ch.start()
    yield ch


# ---------------------------------------------------------------------------
# Exclusive reads prohibited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exclusive_read_raises(channel: BroadcastChannel):
    with pytest.raises(TypeError, match="exclusive"):
        await channel.read("reader-a", exclusive=True)


# ---------------------------------------------------------------------------
# Shared reads work normally
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_read(channel: BroadcastChannel):
    await channel.write("producer", {"event": "click"})
    msgs = await channel.read("reader-a", limit=10)
    assert len(msgs) == 1
    assert msgs[0].sender_id == "producer"


@pytest.mark.asyncio
async def test_multiple_readers_each_see_all(channel: BroadcastChannel):
    await channel.write("producer", "msg-1")
    await channel.write("producer", "msg-2")
    msgs_a = await channel.read("reader-a", limit=10)
    msgs_b = await channel.read("reader-b", limit=10)
    assert len(msgs_a) == 2
    assert len(msgs_b) == 2


# ---------------------------------------------------------------------------
# Subscription (push) pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribers_receive_messages(channel: BroadcastChannel):
    received_a: list[str] = []
    received_b: list[str] = []

    async def cb_a(msg: ChannelMessage):
        received_a.append(msg.id)

    async def cb_b(msg: ChannelMessage):
        received_b.append(msg.id)

    await channel.subscribe("sys-a", cb_a)
    await channel.subscribe("sys-b", cb_b)
    msg_id = await channel.write("producer", "event")
    assert received_a == [msg_id]
    assert received_b == [msg_id]


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(channel: BroadcastChannel):
    received: list[str] = []

    async def cb(msg: ChannelMessage):
        received.append(msg.id)

    await channel.subscribe("sys-a", cb)
    await channel.unsubscribe("sys-a")
    await channel.write("producer", "after-unsub")
    assert received == []
