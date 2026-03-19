"""Tests for channel types: MessageContent, ChannelMessage, ChannelInfo, Visibility."""

import pytest
from pydantic import ValidationError

from sssn.core.channel import (
    ChannelInfo,
    ChannelMessage,
    GenericContent,
    MessageContent,
    Visibility,
)


# ---------------------------------------------------------------------------
# MessageContent / GenericContent
# ---------------------------------------------------------------------------


def test_generic_content_default():
    c = GenericContent()
    assert c.data is None


def test_generic_content_with_data():
    c = GenericContent(data={"key": "value"})
    assert c.data == {"key": "value"}


def test_message_content_extra_allowed():
    """MessageContent uses extra='allow' so unknown fields are silently accepted."""
    c = MessageContent(foo="bar", baz=42)
    assert c.foo == "bar"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ChannelMessage
# ---------------------------------------------------------------------------


def test_channel_message_basic():
    content = GenericContent(data="hello")
    msg = ChannelMessage(
        id="msg-1",
        timestamp=1234567890.0,
        sender_id="sys-a",
        content=content,
    )
    assert msg.id == "msg-1"
    assert msg.sender_id == "sys-a"
    assert msg.correlation_id is None
    assert msg.reply_to is None
    assert msg.recipient_id is None


def test_channel_message_optional_fields():
    content = GenericContent(data=42)
    msg = ChannelMessage(
        id="msg-2",
        timestamp=0.0,
        sender_id="sys-b",
        content=content,
        correlation_id="corr-123",
        reply_to="response-channel",
        recipient_id="sys-c",
        metadata={"priority": 1},
    )
    assert msg.correlation_id == "corr-123"
    assert msg.reply_to == "response-channel"
    assert msg.recipient_id == "sys-c"
    assert msg.metadata["priority"] == 1


def test_channel_message_immutable():
    """ChannelMessage is frozen — mutation should raise."""
    msg = ChannelMessage(
        id="msg-3",
        timestamp=0.0,
        sender_id="sys-a",
        content=GenericContent(data=1),
    )
    with pytest.raises((TypeError, ValidationError)):
        msg.id = "new-id"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ChannelInfo
# ---------------------------------------------------------------------------


def test_channel_info_fields():
    info = ChannelInfo(
        id="ch-1",
        name="My Channel",
        description="A test channel",
        visibility=Visibility.PRIVATE,
        period=30.0,
    )
    assert info.id == "ch-1"
    assert info.visibility == Visibility.PRIVATE
    assert info.period == 30.0


def test_channel_info_public():
    info = ChannelInfo(
        id="ch-2",
        name="Public Channel",
        description="",
        visibility=Visibility.PUBLIC,
        period=60.0,
    )
    assert info.visibility == Visibility.PUBLIC


def test_channel_info_serialisable():
    info = ChannelInfo(
        id="ch-3",
        name="Serialisable",
        description="desc",
        visibility=Visibility.PRIVATE,
        period=10.0,
    )
    d = info.model_dump()
    assert d["id"] == "ch-3"
    assert d["visibility"] == "private"
