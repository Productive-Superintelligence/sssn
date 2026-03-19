from __future__ import annotations

from typing import Any

from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import ChannelMessage


class MailboxChannel(PassthroughChannel):
    """
    A single shared channel that routes messages to individual recipients.

    Each ChannelMessage optionally carries a ``recipient_id`` field.  When
    a reader calls read(), the channel returns only messages addressed to
    that reader (recipient_id == reader_id) plus any broadcast messages
    (recipient_id is None).

    Implementation note
    -------------------
    This channel uses a shared (non-exclusive) read under the hood to fetch
    a larger candidate window, then filters in Python.  As a result, the
    complexity is O(N) in the number of stored messages.  For high-volume
    deployments, prefer a dedicated per-recipient channel or a work queue.

    Authorization is fully enforced: the base class read() is called first,
    so the security layer always runs before any messages are returned.

    Typical usage::

        mailbox = MailboxChannel(id="notifications", name="Notification Mailbox")
        await mailbox.start()

        # Addressed write
        msg = ChannelMessage(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            sender_id="server",
            content=GenericContent(data={"text": "Hello Alice"}),
            recipient_id="alice",
        )
        await mailbox.write("server", msg, direct=True)

        # Alice reads only her messages
        alice_msgs = await mailbox.read("alice", limit=10)
    """

    async def read(
        self,
        reader_id: str,
        limit: int = 10,
        exclusive: bool = False,
        after: str | None = None,
    ) -> list[ChannelMessage]:
        """
        Return up to `limit` messages addressed to reader_id.

        Fetches a wider window (limit * 5) via a shared read, then filters to
        messages where recipient_id matches reader_id or is None (broadcast).
        Authorization is performed by the parent class before any messages
        are examined.
        """
        # Fetch a wider pool so filtering doesn't starve the caller.
        candidates: list[ChannelMessage] = await super().read(
            reader_id=reader_id,
            limit=limit * 5,
            exclusive=exclusive,
            after=after,
        )

        filtered = [
            m for m in candidates
            if m.recipient_id == reader_id or m.recipient_id is None
        ]
        return filtered[:limit]
