from __future__ import annotations

import time
import uuid
from typing import Any

from sssn.core.channel import (
    BaseChannel,
    ChannelMessage,
    GenericContent,
    MessageContent,
)


class PassthroughChannel(BaseChannel):
    """
    A channel variant where data arrives exclusively via write() calls
    rather than through an active pull loop.

    The background loop is intentionally disabled: start() only calls
    on_start() and sets the running/accepting-writes flags — no asyncio Task
    is created.  This makes PassthroughChannel suitable for synchronous
    request-response patterns, broadcast buses, work queues, and mailboxes
    where a producer drives the data flow.

    Conversion happens inline inside write() instead of being deferred to
    a background on_process() cycle.  The result is that every write()
    completes with the message already in the store and subscribers
    already notified before write() returns.

    Subclasses that need a pull loop (e.g., PeriodicSourceChannel) MUST
    override start() to call ``asyncio.create_task(self._run_loop())``
    explicitly — the default passthrough start() deliberately skips this.

    Abstract methods:

    pull_fn()
        No-op in this class.  Subclasses that override start() to enable
        the loop should implement real pull logic here.

    convert_fn(sender_id, raw_data)
        Default implementation:
          - If raw_data is already a ChannelMessage, return it unchanged.
          - If raw_data is a MessageContent subclass, wrap it in a new
            ChannelMessage.
          - Otherwise, wrap in GenericContent first.
    """

    # ------------------------------------------------------------------
    # Lifecycle — no background loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the channel without creating a background task.

        Calls on_start() (initialises DB and transport) then marks the
        channel as running and open for writes.  The _run_loop is NOT
        started — data enters only via write().
        """
        self._is_running = True
        self._accepting_writes = True
        await self.on_start()
        # Deliberately omit: self._loop_task = asyncio.create_task(self._run_loop())

    # ------------------------------------------------------------------
    # Inline write — bypasses the raw buffer
    # ------------------------------------------------------------------

    async def write(
        self,
        sender_id: str,
        data: Any,
        direct: bool = False,
    ) -> str:
        """
        Write to the channel with inline conversion.

        direct=True
            data must be a ChannelMessage.  Goes straight to on_message().

        direct=False
            data is passed through convert_fn() immediately (no buffering),
            then the resulting ChannelMessage is stored and subscribers are
            notified.  Returns the message's stable ID.

        Authorization is checked before any processing.  Backpressure
        (max_raw_buffer_size) is not enforced because there is no buffer.
        """
        if not self._accepting_writes:
            raise RuntimeError(
                f"Channel '{self.id}' is not accepting writes (shutting down)."
            )

        if not await self.security.authorize_write(sender_id, self.id):
            raise PermissionError(
                f"'{sender_id}' is not authorised to write to channel '{self.id}'."
            )

        if direct:
            if not isinstance(data, ChannelMessage):
                raise TypeError(
                    "direct=True requires data to be a ChannelMessage instance."
                )
            await self.on_message(data)
            return data.id

        # Inline conversion — no buffer involved.
        msg = await self.convert_fn(sender_id, data)
        if msg is not None:
            await self.on_message(msg)
            return msg.id
        return ""

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    async def pull_fn(self) -> None:
        """
        No-op for PassthroughChannel.

        Subclasses that add a pull loop by overriding start() should
        implement actual polling logic here.
        """
        pass

    async def convert_fn(self, sender_id: str, raw_data: Any) -> ChannelMessage | None:
        """
        Convert raw data to a ChannelMessage.

        Dispatch rules:
          1. raw_data is a ChannelMessage  → return as-is.
          2. raw_data is a MessageContent  → wrap in a new ChannelMessage.
          3. Anything else                 → wrap in GenericContent first.
        """
        if isinstance(raw_data, ChannelMessage):
            return raw_data

        if isinstance(raw_data, MessageContent):
            content: MessageContent = raw_data
        else:
            content = GenericContent(data=raw_data)

        return ChannelMessage(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            sender_id=sender_id,
            content=content,
        )
