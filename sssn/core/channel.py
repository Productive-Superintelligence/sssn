from __future__ import annotations

import abc
import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


class Visibility(str, Enum):
    PRIVATE = "private"  # Internal only. Default. Not exposed when published.
    PUBLIC = "public"    # Exposed to the internet when umbrella calls publish().


# ---------------------------------------------------------------------------
# Message models
# ---------------------------------------------------------------------------


class MessageContent(BaseModel):
    """
    Base class for typed message payloads.
    Subclass and add fields for schema validation.
    extra="allow" means unrecognised fields are accepted without error.
    """

    model_config = ConfigDict(extra="allow")


class GenericContent(MessageContent):
    """Default content wrapper — accepts any JSON-serialisable data."""

    data: Any = None


class ChannelMessage(BaseModel):
    """
    Immutable unit of information in a channel.
    Frozen so instances can be used as dict keys or in sets.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    timestamp: float                                       # Unix epoch seconds
    sender_id: str                                         # Who wrote this
    content: MessageContent                                # Always serialisable
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Optional fields that enable common patterns
    correlation_id: str | None = None   # Request-response, threading
    reply_to: str | None = None         # Channel ID for responses
    recipient_id: str | None = None     # Mailbox targeting


# ---------------------------------------------------------------------------
# ChannelInfo
# ---------------------------------------------------------------------------


class ChannelInfo(BaseModel):
    """Serialisable snapshot of a channel's identity."""

    id: str
    name: str
    description: str
    visibility: Visibility
    period: float


# ---------------------------------------------------------------------------
# MessageStore
# ---------------------------------------------------------------------------


class MessageStore:
    """
    In-memory, non-destructive message log backing every channel.

    Messages are never removed by reads — they persist until evicted by
    a host operation.  Shared readers use per-reader cursors; exclusive
    readers claim messages which are then invisible to others until
    released or acknowledged.
    """

    def __init__(self) -> None:
        self.messages: list[ChannelMessage] = []
        self.cursors: dict[str, int] = {}               # reader_id → last-read index
        self.claims: dict[str, tuple[str, float]] = {}  # msg_id → (claimer_id, claim_time)
        self.acknowledged: set[str] = set()             # permanently consumed msg IDs
        self.subscribers: dict[str, Callable] = {}      # system_id → async callback

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append(self, msg: ChannelMessage) -> None:
        self.messages.append(msg)

    # ------------------------------------------------------------------
    # Shared read (cursor-based)
    # ------------------------------------------------------------------

    def read_shared(
        self,
        reader_id: str,
        limit: int,
        after: str | None,
    ) -> list[ChannelMessage]:
        """
        Return up to `limit` messages for reader_id.

        If `after` is provided it is treated as a message ID; the cursor is
        moved to the position just after that message.  If `after` is None,
        the stored cursor position is used.

        Acknowledged and exclusively-claimed messages are skipped so shared
        readers never see consumed work-queue items.
        """
        # Resolve starting index from `after` override or stored cursor.
        if after is not None:
            # Find the index of the message with id == after, start from next.
            start = 0
            for i, m in enumerate(self.messages):
                if m.id == after:
                    start = i + 1
                    break
        else:
            start = self.cursors.get(reader_id, 0)

        result: list[ChannelMessage] = []
        idx = start
        while idx < len(self.messages) and len(result) < limit:
            msg = self.messages[idx]
            if msg.id not in self.acknowledged and msg.id not in self.claims:
                result.append(msg)
            idx += 1

        # Advance the stored cursor to where we stopped, regardless of
        # whether we found claimed/acked messages (so we don't re-scan them).
        self.cursors[reader_id] = idx
        return result

    # ------------------------------------------------------------------
    # Exclusive read (claim-based)
    # ------------------------------------------------------------------

    def read_exclusive(self, reader_id: str, limit: int) -> list[ChannelMessage]:
        """
        Claim up to `limit` unclaimed, unacknowledged messages for reader_id.
        Claimed messages are locked to this reader until acknowledged, nacked,
        or reclaimed after timeout.
        """
        result: list[ChannelMessage] = []
        claim_time = time.time()
        for msg in self.messages:
            if len(result) >= limit:
                break
            if msg.id in self.acknowledged:
                continue
            if msg.id in self.claims:
                continue
            self.claims[msg.id] = (reader_id, claim_time)
            result.append(msg)
        return result

    # ------------------------------------------------------------------
    # Acknowledge / nack
    # ------------------------------------------------------------------

    def acknowledge(self, reader_id: str, message_ids: list[str]) -> None:
        """
        Mark messages as permanently consumed.
        Removes the claim and adds to the acknowledged set.
        """
        for mid in message_ids:
            self.claims.pop(mid, None)
            self.acknowledged.add(mid)

    def nack(self, reader_id: str, message_ids: list[str]) -> None:
        """
        Release claimed messages back to the pool immediately.
        Removes the claim; the message becomes available for other readers.
        """
        for mid in message_ids:
            existing = self.claims.get(mid)
            if existing is not None and existing[0] == reader_id:
                del self.claims[mid]

    # ------------------------------------------------------------------
    # Reclaim expired claims
    # ------------------------------------------------------------------

    def reclaim_expired(self, timeout: float) -> None:
        """Remove claims older than `timeout` seconds."""
        cutoff = time.time() - timeout
        expired = [
            mid for mid, (_, claim_time) in self.claims.items()
            if claim_time < cutoff
        ]
        for mid in expired:
            del self.claims[mid]

    # ------------------------------------------------------------------
    # Subscriber notifications
    # ------------------------------------------------------------------

    async def notify_subscribers(self, msg: ChannelMessage) -> None:
        """
        Fire all subscriber callbacks concurrently.
        Errors from individual callbacks are logged but never propagate —
        one broken subscriber cannot silence others.
        """
        if not self.subscribers:
            return
        callbacks = list(self.subscribers.values())
        results = await asyncio.gather(
            *[cb(msg) for cb in callbacks],
            return_exceptions=True,
        )
        for cb, result in zip(callbacks, results):
            if isinstance(result, Exception):
                logger.error(
                    "Subscriber callback %r raised an exception: %s",
                    getattr(cb, "__name__", repr(cb)),
                    result,
                )

    # ------------------------------------------------------------------
    # Host operations
    # ------------------------------------------------------------------

    def clear(self, filter_fn: Callable[[ChannelMessage], bool] | None = None) -> None:
        """Remove messages matching filter_fn, or all messages if None."""
        if filter_fn is None:
            self.messages.clear()
            self.claims.clear()
            self.acknowledged.clear()
            self.cursors.clear()
        else:
            to_remove = {m.id for m in self.messages if filter_fn(m)}
            self.messages = [m for m in self.messages if m.id not in to_remove]
            for mid in to_remove:
                self.claims.pop(mid, None)
                self.acknowledged.discard(mid)

    def evict(
        self,
        before: float | None = None,
        max_count: int | None = None,
    ) -> None:
        """
        Retention enforcement.

        before:    Remove messages with timestamp < before.
        max_count: Keep only the newest max_count messages.

        Both can be applied together; `before` is applied first.
        """
        if before is not None:
            removed = {m.id for m in self.messages if m.timestamp < before}
            self.messages = [m for m in self.messages if m.id not in removed]
            for mid in removed:
                self.claims.pop(mid, None)
                self.acknowledged.discard(mid)

        if max_count is not None and len(self.messages) > max_count:
            # Keep the newest max_count messages (messages are ordered by append time).
            excess = self.messages[: len(self.messages) - max_count]
            removed = {m.id for m in excess}
            self.messages = self.messages[len(self.messages) - max_count:]
            for mid in removed:
                self.claims.pop(mid, None)
                self.acknowledged.discard(mid)

    def remove(self, message_ids: list[str]) -> None:
        """Remove specific messages by ID."""
        id_set = set(message_ids)
        self.messages = [m for m in self.messages if m.id not in id_set]
        for mid in id_set:
            self.claims.pop(mid, None)
            self.acknowledged.discard(mid)


# ---------------------------------------------------------------------------
# BaseChannel
# ---------------------------------------------------------------------------


class BaseChannel(abc.ABC):
    """
    Abstract base class for all channels.

    Provides the full lifecycle (start/stop/drain), the 6-method consumption
    interface (read/write/subscribe/unsubscribe/acknowledge/nack), 3 host
    operations (clear/evict/remove), and a default loop with overridable hooks.

    Subclasses must implement pull_fn() and convert_fn().
    """

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        visibility: Visibility = Visibility.PRIVATE,
        period: float = 60.0,
        max_workers: int = 10,
        max_raw_buffer_size: int = 10_000,
        retention_max_age: float | None = None,
        retention_max_count: int | None = None,
        maintenance_interval_seconds: float = 60.0,
        db_client=None,          # ChannelDBClient | None
        transport=None,          # ChannelTransport | None
        security=None,           # ChannelSecurity | None
    ) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.visibility = visibility
        self.period = period
        self.max_workers = max_workers
        self.max_raw_buffer_size = max_raw_buffer_size
        self.retention_max_age = retention_max_age
        self.retention_max_count = retention_max_count
        self.maintenance_interval_seconds = maintenance_interval_seconds

        self.db_client = db_client
        self.transport = transport
        # Security is lazily defaulted to OpenSecurity on first use so that
        # the import stays lazy (no circular issues at module load time).
        self._security = security

        self._store = MessageStore()
        self._raw_buffer: dict[str, tuple[str, Any]] = {}  # item_id → (sender_id, data)
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_workers)
        self._is_running: bool = False
        self._accepting_writes: bool = False
        self._loop_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Security property — lazy default
    # ------------------------------------------------------------------

    @property
    def security(self):
        if self._security is None:
            from sssn.core.security import OpenSecurity  # noqa: PLC0415
            self._security = OpenSecurity()
        return self._security

    @security.setter
    def security(self, value) -> None:
        self._security = value

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            id=self.id,
            name=self.name,
            description=self.description,
            visibility=self.visibility,
            period=self.period,
        )

    # ------------------------------------------------------------------
    # Abstract methods — channel developer implements these
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def pull_fn(self) -> None:
        """
        Active data ingestion.  Called every cycle inside on_pull().
        Add raw data to self._raw_buffer via write(sender_id, data).
        No-op for PassthroughChannel variants (data arrives via write()).
        """
        ...

    @abc.abstractmethod
    async def convert_fn(self, sender_id: str, raw_data: Any) -> ChannelMessage | None:
        """
        Transform raw data into a ChannelMessage.
        Return None to discard the item.
        Receives the original sender_id so identity is preserved.
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle hooks (overridable)
    # ------------------------------------------------------------------

    async def on_start(self) -> None:
        """One-time setup. Default: initialise DB and start transport."""
        if self.db_client:
            await self.db_client.initialize(self.info.model_dump())
        if self.transport:
            await self.transport.start(self)

    async def on_pull(self) -> None:
        """Called every cycle. Default: pull_fn() with error handling."""
        try:
            await self.pull_fn()
        except Exception as exc:
            await self.on_error("pull", exc)

    async def on_process(self) -> None:
        """
        Pop raw buffer, run convert_fn() concurrently on each item
        (bounded by _semaphore), store successful results.
        """
        items = self._pop_raw_buffer()
        if not items:
            return
        tasks = [self._process_one(k, sid, v) for k, (sid, v) in items.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, ChannelMessage):
                await self.on_message(result)

    async def _process_one(
        self, item_id: str, sender_id: str, raw_data: Any
    ) -> ChannelMessage | None:
        """Run convert_fn() for a single raw buffer item, bounded by _semaphore."""
        async with self._semaphore:
            try:
                return await self.convert_fn(sender_id, raw_data)
            except Exception as exc:
                await self.on_error("process", exc)
                return None

    async def on_message(self, msg: ChannelMessage) -> None:
        """
        Per-message hook: append to store → persist to DB → notify subscribers.
        Override to add filtering, enrichment, or routing.
        """
        self._store.append(msg)
        if self.db_client:
            try:
                await self.db_client.save(msg)
            except Exception as exc:
                await self.on_error("db_save", exc)
        await self._store.notify_subscribers(msg)

    async def on_maintain(self) -> None:
        """
        Periodic housekeeping triggered by wall-clock schedule.
        Default: evict messages by retention policy.
        """
        if self.retention_max_age is not None:
            cutoff = time.time() - self.retention_max_age
            self._store.evict(before=cutoff)
        if self.retention_max_count is not None:
            self._store.evict(max_count=self.retention_max_count)

    async def on_error(self, phase: str, error: Exception) -> None:
        """Default: log and continue (non-fatal)."""
        logger.error("[%s] Error in phase '%s': %s", self.id, phase, error)

    async def on_stop(self) -> None:
        """Cleanup. Default: stop transport."""
        if self.transport:
            try:
                await self.transport.stop()
            except Exception as exc:
                logger.error("[%s] Error stopping transport: %s", self.id, exc)

    # ------------------------------------------------------------------
    # Main loop (not normally overridden)
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """
        Background loop.  on_maintain() is triggered by wall-clock time,
        not cycle count, so retention enforcement is predictable regardless
        of cycle duration.
        """
        next_maintain_at = time.time() + self.maintenance_interval_seconds
        while self._is_running:
            await self.on_pull()
            await self.on_process()

            if time.time() >= next_maintain_at:
                await self.on_maintain()
                next_maintain_at = time.time() + self.maintenance_interval_seconds

            await asyncio.sleep(self.period)

    # ------------------------------------------------------------------
    # Lifecycle control
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the channel: initialise, then begin the background loop."""
        self._is_running = True
        self._accepting_writes = True
        await self.on_start()
        self._loop_task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        """
        Immediate stop — sets the running flag to False.
        The current loop iteration may complete before the task exits.
        Does NOT call on_stop(). Use drain() for a graceful shutdown.
        """
        self._is_running = False

    async def drain(self, timeout: float | None = None) -> None:
        """
        Graceful shutdown:
          1. Stop accepting new writes.
          2. Wait for the raw buffer to empty (or timeout).
          3. Set _is_running = False.
          4. Call on_stop().

        timeout: max seconds to wait for the buffer to clear.
                 None → wait indefinitely.
                 If timeout expires the remaining buffer items are abandoned.
        """
        self._accepting_writes = False
        deadline = time.time() + timeout if timeout is not None else None
        while self._raw_buffer:
            if deadline is not None and time.time() > deadline:
                logger.warning(
                    "[%s] drain() timed out; %d raw buffer items abandoned.",
                    self.id,
                    len(self._raw_buffer),
                )
                break
            await asyncio.sleep(0.1)
        self._is_running = False
        await self.on_stop()

    # ------------------------------------------------------------------
    # Consumption interface
    # ------------------------------------------------------------------

    async def read(
        self,
        reader_id: str,
        limit: int = 10,
        exclusive: bool = False,
        after: str | None = None,
    ) -> list[ChannelMessage]:
        """
        Read messages from the channel.

        exclusive=False (default): Shared read.  Each reader has an independent
            cursor.  All readers see all non-claimed, non-acknowledged messages.
            after: optional message ID to override the cursor.

        exclusive=True: Claim messages for exclusive processing.
            after: IGNORED — exclusive claims are always from the full unclaimed pool.
        """
        if not await self.security.authorize_read(reader_id, self.id):
            raise PermissionError(
                f"'{reader_id}' is not authorised to read from channel '{self.id}'."
            )
        if exclusive:
            return self._store.read_exclusive(reader_id, limit)
        return self._store.read_shared(reader_id, limit, after)

    async def write(
        self, sender_id: str, data: Any, direct: bool = False
    ) -> str:
        """
        Write to the channel.  Returns a message ID (direct) or item_id (buffered).

        direct=False (default): data enters the ingestion pipeline
            (raw buffer → convert_fn → store).  The returned item_id is NOT
            a stable message ID — do not use it to query the store.

        direct=True: data must be a ChannelMessage.  Goes straight to
            on_message(), bypassing convert_fn.  Returns the message's id.
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

        # Buffered path
        if len(self._raw_buffer) >= self.max_raw_buffer_size:
            raise RuntimeError(
                f"Channel '{self.id}' raw buffer full ({self.max_raw_buffer_size} items). "
                "Producer is faster than the ingestion pipeline. Slow down writes or "
                "increase max_raw_buffer_size."
            )
        item_id = f"{time.time()}_{uuid.uuid4().hex[:8]}"
        self._raw_buffer[item_id] = (sender_id, data)
        return item_id

    async def subscribe(
        self, system_id: str, callback: Callable[[ChannelMessage], Any]
    ) -> None:
        """
        Register a push callback for new messages.  Local-only.
        Raises PermissionError if the system does not have read access.
        """
        if not await self.security.authorize_read(system_id, self.id):
            raise PermissionError(
                f"'{system_id}' is not authorised to subscribe to channel '{self.id}'."
            )
        self._store.subscribers[system_id] = callback

    async def unsubscribe(self, system_id: str) -> None:
        """Remove a previously registered push callback."""
        self._store.subscribers.pop(system_id, None)

    async def acknowledge(self, reader_id: str, message_ids: list[str]) -> None:
        """Mark exclusively-claimed messages as permanently consumed."""
        self._store.acknowledge(reader_id, message_ids)

    async def nack(self, reader_id: str, message_ids: list[str]) -> None:
        """
        Release claimed messages back to the pool immediately.
        No-op for non-exclusively-claimed messages.
        """
        self._store.nack(reader_id, message_ids)

    # ------------------------------------------------------------------
    # Host operations
    # ------------------------------------------------------------------

    async def clear(
        self, filter_fn: Callable[[ChannelMessage], bool] | None = None
    ) -> None:
        """Remove messages matching filter_fn, or all messages if None."""
        self._store.clear(filter_fn)

    async def evict(
        self, before: float | None = None, max_count: int | None = None
    ) -> None:
        """Retention enforcement by age and/or count."""
        self._store.evict(before=before, max_count=max_count)

    async def remove(self, message_ids: list[str]) -> None:
        """Remove specific messages by ID."""
        self._store.remove(message_ids)

    # ------------------------------------------------------------------
    # Transport attachment
    # ------------------------------------------------------------------

    def attach_transport(self, transport) -> None:
        """Attach (or replace) the transport.  Called before start()."""
        self.transport = transport

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pop_raw_buffer(self) -> dict[str, tuple[str, Any]]:
        """
        Atomically snapshot and clear the raw buffer.
        Returns a copy so callers are not racing with new writes.
        """
        snapshot = dict(self._raw_buffer)
        self._raw_buffer.clear()
        return snapshot
