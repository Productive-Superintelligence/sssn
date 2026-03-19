from __future__ import annotations

from typing import Any

from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import ChannelMessage


class WorkQueueChannel(PassthroughChannel):
    """
    A competing-consumer work queue built on top of PassthroughChannel.

    Semantics
    ---------
    * Writes enqueue tasks; every write() call produces one claimable item.
    * Reads are always exclusive: a message is claimed by exactly one
      reader and hidden from all others until it is acknowledged or the
      claim expires.
    * Shared reads (exclusive=False) are rejected with TypeError to prevent
      accidental at-least-once fan-out in a queue context.
    * Expired claims are lazily reclaimed on every read() call so dead
      workers do not permanently starve the queue.

    Acknowledge / nack
    ------------------
    * acknowledge(): mark work as done; message is permanently removed.
    * nack(): release the claim immediately so another worker can pick it up.

    Claim timeout
    -------------
    claim_timeout controls how long a worker may hold a claim before it is
    automatically released.  Defaults to 300 seconds (5 minutes).

    Typical usage::

        queue = WorkQueueChannel(id="jobs", name="Job Queue")
        await queue.start()

        # Producer
        await queue.write("producer", {"task": "resize", "file": "img.png"})

        # Worker
        msgs = await queue.read("worker-1", limit=5, exclusive=True)
        for msg in msgs:
            await process(msg)
            await queue.acknowledge("worker-1", [msg.id])
    """

    def __init__(self, claim_timeout: float = 300.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.claim_timeout = claim_timeout

    # ------------------------------------------------------------------
    # Read — exclusive only
    # ------------------------------------------------------------------

    async def read(
        self,
        reader_id: str,
        limit: int = 10,
        exclusive: bool = False,
        after: str | None = None,
    ) -> list[ChannelMessage]:
        """
        Claim up to `limit` unclaimed messages for reader_id.

        exclusive must be True (or omitted — callers may pass exclusive=True
        explicitly).  Shared reads raise TypeError.

        Expired claims from previous workers are reclaimed before each read
        so stale locks do not permanently hold items.
        """
        if not exclusive:
            raise TypeError(
                "WorkQueueChannel only supports exclusive reads. "
                "Use read(exclusive=True) to claim work items."
            )

        # Lazy reclaim: release claims older than claim_timeout before
        # presenting new items to this reader.
        self._store.reclaim_expired(timeout=self.claim_timeout)

        # Delegate to the base class with exclusive=True; this handles auth
        # and then calls _store.read_exclusive().
        return await super().read(
            reader_id=reader_id,
            limit=limit,
            exclusive=True,
            after=after,
        )

    # ------------------------------------------------------------------
    # Nack override — explicit docstring; implementation via base class
    # ------------------------------------------------------------------

    async def nack(self, reader_id: str, message_ids: list[str]) -> None:
        """
        Release claimed messages back to the pool immediately.

        The released messages become available for the next exclusive read()
        from any worker (including the caller).
        """
        self._store.nack(reader_id, message_ids)

    # ------------------------------------------------------------------
    # Maintenance — periodic expired-claim cleanup
    # ------------------------------------------------------------------

    async def on_maintain(self) -> None:
        """
        Periodic housekeeping: evict old messages (via super) and reclaim
        any claims that have exceeded claim_timeout.
        """
        await super().on_maintain()
        self._store.reclaim_expired(self.claim_timeout)
