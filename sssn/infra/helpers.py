from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Optional

from sssn.core.channel import ChannelMessage, GenericContent

if TYPE_CHECKING:
    from sssn.core.channel import BaseChannel


async def request_via_channel(
    request_channel: BaseChannel,
    response_channel: BaseChannel,
    sender_id: str,
    data,
    timeout: float = 30.0,
) -> Optional[ChannelMessage]:
    """
    Send a request on ``request_channel`` and poll ``response_channel`` for a
    correlated reply.

    A correlation ID is generated and embedded in the outgoing message's
    ``correlation_id`` field.  The caller's reply address (``response_channel``
    ID) is set as ``reply_to`` so the responder knows where to send its answer.

    The function polls ``response_channel`` every 0.5 seconds until a message
    whose ``correlation_id`` matches the one sent is found, or until
    ``timeout`` seconds elapse.

    Parameters
    ----------
    request_channel:
        The channel to write the request to.  Must already be started and
        connected to the responder.
    response_channel:
        The channel to poll for the correlated reply.  The caller should own
        this channel (or at least have read access).
    sender_id:
        The system ID used for both the write and the read operations.
    data:
        The request payload.  Will be wrapped in a GenericContent if it is
        not already a MessageContent instance.
    timeout:
        Maximum seconds to wait for a matching reply.  Returns None on timeout.

    Returns
    -------
    ChannelMessage | None
        The first response message whose correlation_id matches, or None if
        the deadline expires before a match is found.

    Typical usage::

        reply = await request_via_channel(
            request_channel=cmd_channel,
            response_channel=reply_channel,
            sender_id="orchestrator",
            data={"action": "resize", "width": 640},
            timeout=10.0,
        )
        if reply is None:
            print("Request timed out.")
        else:
            print("Got reply:", reply.content)
    """
    corr_id = str(uuid.uuid4())

    # Resolve the response channel ID for reply_to.
    reply_to: str
    if hasattr(response_channel, "id"):
        reply_to = response_channel.id
    else:
        reply_to = str(response_channel)

    msg = ChannelMessage(
        id=corr_id,
        timestamp=time.time(),
        sender_id=sender_id,
        content=GenericContent(data=data),
        metadata={},
        correlation_id=corr_id,
        reply_to=reply_to,
    )

    await request_channel.write(sender_id=sender_id, data=msg, direct=True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await response_channel.read(reader_id=sender_id, limit=50)
        for r in msgs:
            if r.correlation_id == corr_id:
                return r
        await asyncio.sleep(0.5)

    return None
