import pytest
from typing import Any, Optional, List
from sssn.core.channel import BaseChannel, ChannelMessage

# Create a concrete implementation for testing
class DummyChannel(BaseChannel):
    async def pull_fn(self):
        pass # Do nothing for basic tests

    async def convert_fn(self, raw_item: Any) -> Optional[ChannelMessage]:
        # Simple passthrough for testing
        return ChannelMessage(
            id=raw_item.get("id", "test_id"),
            timestamp=0.0,
            sender_id="test_sender",
            content=raw_item.get("data"),
            metadata={},
            raw_data=raw_item
        )

@pytest.fixture
def dummy_channel():
    """Provides a fresh, isolated channel for every test."""
    return DummyChannel(
        channel_id="test_001",
        name="Test Channel",
        description="For unit testing",
        period=0.1, # Fast period for quick tests
        readable_by=["*"],
        writable_by=["*"]
    )

