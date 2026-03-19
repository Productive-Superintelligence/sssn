from __future__ import annotations

from typing import Any

from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import ChannelMessage


class BroadcastChannel(PassthroughChannel):
    """
    A push-first, fan-out channel where subscription is the primary
    consumption pattern.

    Every subscriber receives every message as it arrives.  Shared reads
    (cursor-based) are also supported so late-joining readers can catch up
    from their last cursor position.

    Exclusive reads are explicitly prohibited: BroadcastChannel is designed
    for one-to-many delivery, not work-queue claiming.  Attempting an
    exclusive read raises TypeError immediately.

    Typical usage::

        broadcast = BroadcastChannel(id="events", name="Event Bus")
        await broadcast.start()

        # Subscriber pattern (push, preferred)
        async def handler(msg: ChannelMessage):
            print(msg.content)

        await broadcast.subscribe("consumer-1", handler)

        # Producer
        await broadcast.write("producer", {"type": "click", "x": 42})

        # Late-joining poll reader (shared cursor, not exclusive)
        msgs = await broadcast.read("consumer-2", limit=20)
    """

    async def read(
        self,
        reader_id: str,
        limit: int = 10,
        exclusive: bool = False,
        after: str | None = None,
    ) -> list[ChannelMessage]:
        """
        Read messages from the broadcast channel.

        exclusive=True is not supported and raises TypeError.
        All other arguments behave identically to BaseChannel.read().
        """
        if exclusive:
            raise TypeError(
                "BroadcastChannel does not support exclusive reads. "
                "Use subscribe() for push delivery or read(exclusive=False) "
                "for cursor-based polling."
            )
        return await super().read(
            reader_id=reader_id,
            limit=limit,
            exclusive=False,
            after=after,
        )
