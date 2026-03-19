"""Tests for PassthroughChannel: inline write, no background loop, subscribe."""

import pytest

from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import ChannelMessage, GenericContent


@pytest.fixture()
async def channel():
    ch = PassthroughChannel(id="pt-ch", name="Passthrough", description="test")
    await ch.start()
    yield ch


# ---------------------------------------------------------------------------
# start() — no loop task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_no_loop_task():
    ch = PassthroughChannel(id="pt-ch", name="PT", description="")
    await ch.start()
    assert ch._is_running is True
    assert ch._accepting_writes is True
    assert ch._loop_task is None


# ---------------------------------------------------------------------------
# write() — inline conversion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_raw_data(channel: PassthroughChannel):
    msg_id = await channel.write("sender-a", {"hello": "world"})
    assert msg_id != ""
    msgs = await channel.read("reader-a", limit=10)
    assert len(msgs) == 1
    assert isinstance(msgs[0].content, GenericContent)
    assert msgs[0].content.data == {"hello": "world"}


@pytest.mark.asyncio
async def test_write_returns_stable_id(channel: PassthroughChannel):
    msg_id = await channel.write("sender-a", "payload")
    msgs = await channel.read("reader-a", limit=10)
    assert msgs[0].id == msg_id


@pytest.mark.asyncio
async def test_write_direct(channel: PassthroughChannel):
    content = GenericContent(data="direct")
    import time, uuid
    msg = ChannelMessage(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        sender_id="sender-a",
        content=content,
    )
    returned_id = await channel.write("sender-a", msg, direct=True)
    assert returned_id == msg.id
    msgs = await channel.read("reader-a", limit=10)
    assert msgs[0].id == msg.id


@pytest.mark.asyncio
async def test_write_direct_requires_channel_message(channel: PassthroughChannel):
    with pytest.raises(TypeError):
        await channel.write("sender-a", {"not": "a message"}, direct=True)


@pytest.mark.asyncio
async def test_write_rejected_when_not_accepting(channel: PassthroughChannel):
    channel._accepting_writes = False
    with pytest.raises(RuntimeError, match="not accepting writes"):
        await channel.write("sender-a", "data")


# ---------------------------------------------------------------------------
# read() — shared cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_shared_returns_messages(channel: PassthroughChannel):
    await channel.write("s", "a")
    await channel.write("s", "b")
    msgs = await channel.read("reader-a", limit=10)
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_read_shared_cursor_advances(channel: PassthroughChannel):
    await channel.write("s", "a")
    await channel.write("s", "b")
    await channel.read("reader-a", limit=1)
    msgs = await channel.read("reader-a", limit=10)
    assert len(msgs) == 1


@pytest.mark.asyncio
async def test_read_permission_denied():
    from sssn.core.security import ACLSecurity
    sec = ACLSecurity()
    ch = PassthroughChannel(id="secure-ch", name="Secure", description="", security=sec)
    await ch.start()
    with pytest.raises(PermissionError):
        await ch.read("unauthorized-sys", limit=10)


# ---------------------------------------------------------------------------
# subscribe() / unsubscribe()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_receives_messages(channel: PassthroughChannel):
    received = []

    async def cb(msg: ChannelMessage):
        received.append(msg.id)

    await channel.subscribe("listener", cb)
    msg_id = await channel.write("sender", "event")
    assert received == [msg_id]


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(channel: PassthroughChannel):
    received = []

    async def cb(msg: ChannelMessage):
        received.append(msg.id)

    await channel.subscribe("listener", cb)
    await channel.unsubscribe("listener")
    await channel.write("sender", "after-unsub")
    assert received == []


@pytest.mark.asyncio
async def test_subscribe_permission_denied():
    from sssn.core.security import ACLSecurity
    sec = ACLSecurity()
    ch = PassthroughChannel(id="sec-ch", name="Sec", description="", security=sec)
    await ch.start()
    with pytest.raises(PermissionError):
        await ch.subscribe("rogue", lambda msg: None)


# ---------------------------------------------------------------------------
# convert_fn dispatch rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_fn_passthrough_channel_message(channel: PassthroughChannel):
    import time, uuid
    msg = ChannelMessage(
        id="existing",
        timestamp=time.time(),
        sender_id="s",
        content=GenericContent(data="x"),
    )
    result = await channel.convert_fn("s", msg)
    assert result is msg


@pytest.mark.asyncio
async def test_convert_fn_wraps_message_content(channel: PassthroughChannel):
    content = GenericContent(data=99)
    result = await channel.convert_fn("s", content)
    assert result is not None
    assert result.content is content


@pytest.mark.asyncio
async def test_convert_fn_wraps_arbitrary_data(channel: PassthroughChannel):
    result = await channel.convert_fn("s", [1, 2, 3])
    assert result is not None
    assert isinstance(result.content, GenericContent)
    assert result.content.data == [1, 2, 3]
