# SSSN: Architecture Specification

> **Status**: Constitution — all code and design decisions should conform to this document.
> **Version**: 0.6

---

## 1. What Is SSSN

SSSN (Simple System of Systems Network) is a lightweight network layer for connecting AI agents, humans, and machines into collaborative distributed systems.

**The name**: "Simple" is the ethos. The framework does the minimum needed to make heterogeneous systems talk to each other. "System of Systems" means participants are themselves complex systems. "Network" means connections, flows, and communication.

**The analogy**: If LLLM is an OS kernel — managing a single agentic system's internals — then SSSN is the network protocol layer that connects many independent systems. The internal conceptual model is an *information supply network*: systems are companies, channels are the supply chains between them. But SSSN is not reconstructing the internet. It exists because autonomous agents need structured, managed, observable information flows with access control, persistence, typed messages, and multi-mode consumption that raw HTTP doesn't provide out of the box.

**The "simple" promise**: To learn SSSN, you learn one thing — the Channel. Systems exist to connect to channels. Security protects channels. Discovery finds channels.

**Independence**: SSSN and LLLM are fully independent. Neither imports the other. Composing them is trivial — a decorator or thin base class bridges them.


## 2. Core Abstractions

Exactly two: **System** (node) and **Channel** (edge).

```
┌──────────┐         ┌──────────────┐         ┌──────────┐
│ System A │──read──▶│   Channel    │◀──write──│ System B │
│          │◀─write──│              │──read──▶ │          │
└──────────┘         └──────────────┘         └──────────┘
```

**Channels are the center.** Design the flows first, then connect systems to them. Channels are the *material infrastructure* of the network — persistent, managed, observable — not transient sessions.


## 3. Developer Scenarios

Most developers are both channel developer and system developer. SSSN is designed for these situations:

**A. "I have systems, I want to connect them."** Design channels → register existing systems → connect via ChannelClient → done.

**B. "I'm building a distributed system from scratch."** Design topology (systems + channels) → implement as umbrella BaseSystem → launch together.

**C. "I want to expose my system to others."** Decorate with `@sssn.system` → expose methods with `@sssn.expose` → announce to discovery.

**D. "I want to build a content channel."** Subclass PeriodicSourceChannel → implement pull_fn + convert_fn → configure persistence → publish.

**E. "I want to join an existing network."** Connect to discovery → browse available channels → register → connect → participate.


## 4. Channel

### 4.1 Concept

A Channel is a hosted, managed information store. The key mental model: **a managed database with a simple read/write interface, optional active ingestion, and built-in access control.**

Channels are versatile. The same interface supports many patterns:

| Pattern | How | Key feature |
|---------|-----|-------------|
| **Bulletin board** | `read()` | All readers see all messages |
| **Task queue** | `read(exclusive=True)` | One reader per message |
| **Mailbox** | `read()` + filter by `recipient_id` | Targeted messages |
| **Pub/sub** | `subscribe()` | Push notifications |
| **Request-response** | `write(direct=True)` + `correlation_id` | Correlated pairs |
| **Forum** | `read()` + `correlation_id` | Threaded discussions |

**One class, many patterns.** The pattern emerges from which arguments and message fields are used.

### 4.2 ChannelInfo and ChannelMessage

`ChannelInfo` is the channel's identity record — a serializable snapshot returned by `channel.info` and used by discovery and DB initialization:

```python
class ChannelInfo(BaseModel):
    id: str
    name: str
    description: str
    visibility: Visibility
    period: float
```

`ChannelMessage` is the universal message format. Immutable, always serializable via Pydantic.

```python
class MessageContent(BaseModel):
    """Base class for typed payloads. Subclass for schema validation."""
    model_config = ConfigDict(extra="allow")

class GenericContent(MessageContent):
    """Default: accepts any JSON-serializable data."""
    data: Any

class ChannelMessage(BaseModel):
    """Immutable unit of information in a channel."""
    model_config = ConfigDict(frozen=True)
    
    id: str
    timestamp: float                            # Epoch seconds
    sender_id: str                              # Who wrote this
    content: MessageContent                     # Always serializable
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # --- Optional fields for common patterns ---
    correlation_id: Optional[str] = None        # Request-response, threading
    reply_to: Optional[str] = None              # Channel ID for responses
    recipient_id: Optional[str] = None          # Mailbox targeting
```

For typed channels, subclass `MessageContent`:

```python
class DesignCommand(MessageContent):
    parent_ids: List[str]
    gp_operation: str  # "mutate" | "crossover" | "scratch"
    target_units: Optional[List[str]] = None
```

### 4.3 Architecture: Core vs Transport

```
┌─────────────────────────────────────────────────┐
│                  BaseChannel                     │
│  identity, access, message store,                │
│  consumption, pull_fn, convert_fn,               │
│  lifecycle hooks, retention                      │
├─────────────────────────────────────────────────┤
│              ChannelTransport (pluggable)         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  HTTP    │  │  IPC     │  │  In-Process   │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────┘
```

### 4.4 Channel Interface

The base interface has **6 consumption methods** and **3 host operations**:

```python
class BaseChannel(abc.ABC):
    
    # --- Identity ---
    id: str
    name: str
    description: str
    visibility: Visibility = Visibility.PRIVATE   # PRIVATE or PUBLIC
    
    # --- Configuration ---
    period: float = 60.0                # Sleep time between loop cycles (NOT a target cycle time).
                                        # Actual cycle time = on_pull() + on_process() + period.
    max_workers: int = 10               # Concurrent convert_fn workers
    max_raw_buffer_size: int = 10_000   # Backpressure limit. write() raises when exceeded.
    retention_max_age: Optional[float] = None
    retention_max_count: Optional[int] = None
    maintenance_interval_seconds: float = 60.0  # Wall-clock seconds between on_maintain() calls.
    
    # --- Pluggable ---
    db_client: Optional[ChannelDBClient] = None
    transport: Optional[ChannelTransport] = None
    security: Optional[ChannelSecurity] = None   # Default: OpenSecurity
    
    # === Abstract (channel developer implements) ===
    
    async def pull_fn(self):
        """Active data ingestion. Called every cycle. No-op if no external source."""
        ...
    
    async def convert_fn(self, sender_id: str, raw_data: Any) -> Optional[ChannelMessage]:
        """Transform raw data into a ChannelMessage. Return None to discard."""
        ...
    
    # === Consumption interface ===
    
    async def read(self, reader_id: str, limit: int = 10,
                   exclusive: bool = False, after: Optional[str] = None
    ) -> List[ChannelMessage]:
        """
        Read messages from the channel.

        exclusive=False (default): Shared read. Each reader has an independent
            cursor. All readers see all messages. Non-destructive.
            after: optional message ID to override the cursor (read from that
            point onwards). Ignored if None (use stored cursor position).

        exclusive=True: Exclusive claim. Messages are locked to this reader.
            Other readers cannot see claimed messages. For task assignment.
            after: IGNORED for exclusive reads. Claims are always against the
            full pool of unclaimed messages — there is no cursor for exclusive
            consumption. Use acknowledge() to complete, nack() to release.
        """
        ...
    
    async def write(self, sender_id: str, data: Any, 
                    direct: bool = False) -> str:
        """
        Write to the channel. Returns message ID.
        
        direct=False (default): Raw data enters the ingestion pipeline
            (raw buffer → convert_fn → store). Use for external data 
            or data that needs processing.
        direct=True: `data` must be a ChannelMessage. Goes straight to 
            the store, bypassing convert_fn. Use for pre-formed 
            system-to-system messages.
        """
        ...
    
    async def subscribe(self, system_id: str, callback: Callable[[ChannelMessage], Any]):
        """
        Register push callback for new messages. Local-only (see §4.9).
        Security: checks authorize_read before registering. Raises PermissionError if denied.
        """
        ...
    
    async def unsubscribe(self, system_id: str):
        """Remove push callback."""
        ...
    
    async def acknowledge(self, reader_id: str, message_ids: List[str]):
        """
        Acknowledge processing of exclusively-claimed messages.
        Acknowledged messages are permanently consumed.
        Unacknowledged claims are reclaimed after timeout (see WorkQueueChannel).
        No-op for shared reads (non-exclusive messages don't need acknowledgment).
        """
        ...

    async def nack(self, reader_id: str, message_ids: List[str]):
        """
        Explicitly release claimed messages back to the pool without consuming them.
        They become available for other readers immediately, without waiting for
        claim_timeout to expire.
        Use when a worker determines it cannot process a job (wrong capabilities,
        transient resource unavailability, etc.).
        No-op for shared (non-exclusive) messages.
        """
        ...

    # === Host operations ===
    
    async def clear(self, filter_fn: Optional[Callable[[ChannelMessage], bool]] = None):
        """Remove messages matching filter, or all."""
        ...
    
    async def evict(self, before: Optional[float] = None, max_count: Optional[int] = None):
        """Retention enforcement."""
        ...
    
    async def remove(self, message_ids: List[str]):
        """Remove specific messages by ID."""
        ...
    
    # === Lifecycle (see §4.7) ===
    async def start(self): ...
    def stop(self): ...
    async def drain(self, timeout: Optional[float] = None): ...
```

Note: `convert_fn` receives `sender_id` as its first argument. The raw buffer stores `(sender_id, data)` pairs so the sender's identity is preserved through the ingestion pipeline.

### 4.5 Message Store

The in-memory log backing every channel. Not a destructive queue — messages persist until evicted.

```python
class MessageStore:
    messages: List[ChannelMessage]              # Ordered by timestamp
    cursors: Dict[str, int]                     # reader_id → last-read index (shared mode)
    claims: Dict[str, Tuple[str, float]]        # message_id → (claimer_id, claim_time)
    acknowledged: Set[str]                      # Permanently consumed message IDs
    subscribers: Dict[str, Callable]            # system_id → callback

    def append(self, msg: ChannelMessage): ...
    def read_shared(self, reader_id: str, limit: int, after: Optional[str]) -> List[ChannelMessage]: ...
    def read_exclusive(self, reader_id: str, limit: int) -> List[ChannelMessage]: ...
    def acknowledge(self, reader_id: str, message_ids: List[str]): ...
    def nack(self, reader_id: str, message_ids: List[str]): ...   # Release claims immediately
    def reclaim_expired(self, timeout: float): ...
    async def notify_subscribers(self, msg: ChannelMessage):
        """
        Fire all subscriber callbacks concurrently via asyncio.gather(..., return_exceptions=True).
        Exceptions in individual callbacks are logged but do NOT propagate — all subscribers
        are notified regardless of individual failures. One broken callback cannot silence others.
        """
        ...
    def clear(self, filter_fn=None): ...
    def evict(self, before=None, max_count=None): ...
    def remove(self, message_ids: List[str]): ...
```

**Ordering guarantee**: Messages are stored in the order `on_message()` is called. Within a single asyncio event loop, this is deterministic — `on_message()` is never called concurrently. For `PassthroughChannel` (inline writes), order equals the call order from the event loop, which is FIFO for a single producer. For multi-producer channels, order reflects asyncio scheduling — deterministic within a run, but dependent on interleaving. WorkQueueChannel delivers tasks in FIFO order.

**Cursor persistence**: `cursors` is in-memory and resets on channel restart. Readers re-read from the start of the in-memory store (or from DB if the channel reloads messages on startup). For long-lived shared-read channels where cursor durability matters, override `on_start()` to restore cursors from the DB and `on_message()` to persist cursor updates. This is a known trade-off: the default is simple; persistence is opt-in via override.

### 4.6 Persistence: ChannelDBClient

Abstract persistence backend. Async, message-aware, time-indexed. Separate from LLLM's LogBackend (different sync model, data types, and query patterns — see §13.1). Implementations use the same underlying libraries (aiosqlite, firebase-admin, etc.).

```python
class ChannelDBClient(abc.ABC):
    async def initialize(self, channel_metadata: Dict[str, Any]) -> bool: ...
    async def save(self, message: ChannelMessage) -> bool: ...
    async def save_batch(self, messages: List[ChannelMessage]) -> bool: ...
    async def get(self, message_id: str) -> Optional[ChannelMessage]: ...
    async def get_range(self, start_time: float, end_time: float) -> List[ChannelMessage]: ...
    async def get_latest(self, limit: int) -> List[ChannelMessage]: ...
    async def delete(self, message_ids: List[str]) -> bool: ...

# Built-in
class SqliteDBClient(ChannelDBClient): ...     # via aiosqlite
class FileDBClient(ChannelDBClient): ...       # JSON files
class FirebaseDBClient(ChannelDBClient): ...   # via firebase-admin
```

### 4.7 Lifecycle: Default Loop with Overridable Hooks

Like PyTorch Lightning: a default lifecycle that works out of the box, with hooks you can override.

```
start()
  ├── on_start()            # setup DB, transport
  ├── MAIN LOOP:
  │     on_pull()           # → pull_fn()
  │     on_process()        # → pop buffer → convert_fn() → on_message()
  │     on_maintain()       # every N cycles: retention enforcement
  │     sleep(period)
  └── drain() / stop()
        on_stop()           # cleanup
```

```python
class BaseChannel(abc.ABC):
    
    # === Overridable hooks ===
    
    async def on_start(self):
        """One-time setup. Default: init DB + start transport."""
        if self.db_client: await self.db_client.initialize(self.info.model_dump())
        if self.transport: await self.transport.start(self)
    
    async def on_pull(self):
        """Called every cycle. Default: pull_fn() with error handling."""
        try: await self.pull_fn()
        except Exception as e: await self.on_error("pull", e)
    
    async def on_process(self):
        """Pop raw buffer, run convert_fn concurrently, store results."""
        items = self._pop_raw_buffer()  # Returns Dict[str, Tuple[str, Any]] — {item_id: (sender_id, data)}
        if not items:
            return
        tasks = [self._process_one(k, sid, v) for k, (sid, v) in items.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, ChannelMessage):
                await self.on_message(result)
    
    async def on_message(self, msg: ChannelMessage):
        """Per-message hook. Default: store → persist → notify subscribers."""
        self._store.append(msg)
        if self.db_client: await self.db_client.save(msg)
        await self._store.notify_subscribers(msg)
    
    async def on_maintain(self):
        """
        Periodic housekeeping. Called by wall-clock schedule (maintenance_interval_seconds),
        not by cycle count, so retention enforcement is predictable regardless of cycle duration.
        Default: evict by retention policy.
        """
        if self.retention_max_age is not None:
            self._store.evict(before=time.time() - self.retention_max_age)
        if self.retention_max_count is not None:
            self._store.evict(max_count=self.retention_max_count)
    
    async def on_error(self, phase: str, error: Exception):
        """Default: log and continue."""
        logger.error(f"[{self.id}] Error in {phase}: {error}")
    
    async def on_stop(self):
        """Cleanup. Default: stop transport."""
        if self.transport: await self.transport.stop()
    
    # === Lifecycle control ===
    
    async def start(self):
        self._is_running = True
        await self.on_start()
        self._loop_task = asyncio.create_task(self._run_loop())
    
    def stop(self):
        """Immediate stop. In-flight operations may be interrupted."""
        self._is_running = False
    
    async def drain(self, timeout: Optional[float] = None):
        """
        Graceful shutdown: stop accepting new writes, wait for in-flight
        processing to complete, then stop. Use before redeployment.

        timeout: max seconds to wait for the raw buffer to clear.
                 None = wait forever. If the timeout expires before the
                 buffer empties, remaining items are discarded and shutdown
                 proceeds. Prevents indefinite hang if a convert_fn stalls.
        """
        self._accepting_writes = False
        deadline = time.time() + timeout if timeout is not None else None
        while self._raw_buffer:
            if deadline is not None and time.time() > deadline:
                break
            await asyncio.sleep(0.1)
        self._is_running = False
        await self.on_stop()
```

### 4.8 Write Path: Immediate vs Background

The `direct` flag controls the write path:

```python
async def write(self, sender_id: str, data: Any, direct: bool = False) -> str:
    """
    Returns:
        direct=True  → the message's permanent ID (data.id). Usable immediately.
        direct=False → a temporary item_id from the raw buffer. NOT a message ID.
                       The item is converted asynchronously; the final message ID
                       is only available after convert_fn runs. Do not use the
                       returned item_id to query the store. Use direct=True for
                       all cases where you need a stable, referenceable message ID.
    """
    if not self._accepting_writes:
        raise RuntimeError(f"Channel '{self.id}' is not accepting writes (shutting down).")

    # Security check
    if self.security:
        if not await self.security.authorize_write(sender_id, self.id):
            raise PermissionError(...)

    if direct:
        # Direct: data must be ChannelMessage, goes straight to store
        assert isinstance(data, ChannelMessage)
        await self.on_message(data)
        return data.id
    else:
        # Ingestion pipeline: buffer → background loop → convert_fn → store
        if len(self._raw_buffer) >= self.max_raw_buffer_size:
            raise RuntimeError(
                f"Channel '{self.id}' raw buffer full ({self.max_raw_buffer_size} items). "
                "Producer is faster than the ingestion pipeline. Slow down writes or "
                "increase max_raw_buffer_size."
            )
        item_id = f"{time.time()}_{uuid.uuid4().hex[:8]}"
        self._raw_buffer[item_id] = (sender_id, data)  # Preserves sender_id
        return item_id
```

**Backpressure**: `max_raw_buffer_size` (default: 10 000) caps the in-memory buffer. When full, `write()` raises immediately rather than silently growing without bound. Tune this based on the expected burst size and processing speed of your `convert_fn`. For `PassthroughChannel`, writes are processed inline so the buffer never fills.

**Important for PassthroughChannel**: Since PassthroughChannel has no external source and a trivial convert_fn, non-direct writes are processed inline (not waiting for the background loop):

```python
class PassthroughChannel(BaseChannel):
    """
    No external source. Writes are processed inline — no background loop is started.
    This eliminates idle asyncio tasks for every channel that doesn't need periodic pulling.

    If you subclass PassthroughChannel and add a meaningful pull_fn, override
    start() to call super().start() with loop=True.
    """

    async def pull_fn(self): pass

    async def convert_fn(self, sender_id: str, raw_data: Any) -> Optional[ChannelMessage]:
        if isinstance(raw_data, ChannelMessage):
            return raw_data
        content = raw_data if isinstance(raw_data, MessageContent) else GenericContent(data=raw_data)
        return ChannelMessage(
            id=str(uuid.uuid4()), timestamp=time.time(),
            sender_id=sender_id, content=content,
        )

    async def start(self):
        """Override: skip background loop. DB and transport are still initialized."""
        self._is_running = True
        await self.on_start()
        # No self._loop_task — no pull_fn, no buffered ingestion, no periodic work.

    async def write(self, sender_id: str, data: Any, direct: bool = False) -> str:
        """Override: process writes inline. Always returns a stable message ID."""
        if not self._accepting_writes:
            raise RuntimeError(f"Channel '{self.id}' is not accepting writes.")
        if self.security:
            if not await self.security.authorize_write(sender_id, self.id):
                raise PermissionError(...)
        if direct:
            assert isinstance(data, ChannelMessage)
            msg = data
        else:
            msg = await self.convert_fn(sender_id, data)
            if msg is None: return ""
        await self.on_message(msg)
        return msg.id
```

This means PassthroughChannel writes are always immediate — no latency from the background loop. PeriodicSourceChannel still uses the background loop for its pull_fn cycle.

### 4.9 Subscription: Local-Only by Default

`subscribe(callback)` registers a Python callable. This works for `InProcessTransport` — callbacks fire immediately when a message is stored.

**For remote channels, subscription is not available over HTTP.** HTTP is request-response; it cannot push. Remote consumers must poll via `read()`. The cursor-based design makes polling efficient — each `read()` returns only new messages since the last read.

Future `WebSocketTransport` can enable remote push subscriptions. This is an extension, not a base requirement. The design accommodates it: `subscribe()` is already defined on the channel interface, and a WebSocket transport would relay `notify_subscribers` events to connected clients.

### 4.10 Transport

```python
class ChannelTransport(abc.ABC):
    async def start(self, channel: BaseChannel): ...
    async def stop(self): ...

class InProcessTransport(ChannelTransport):
    """Direct Python method calls. Zero overhead. Default."""
    ...

class HttpTransport(ChannelTransport):
    """
    REST endpoints on FastAPI. Standalone or mounted on shared ChannelServer.
    
    Endpoints:
      GET  /channels/{id}?limit=10&after={msg_id}&exclusive={bool}  → read()
      PUT  /channels/{id}?direct={bool}                              → write()
      POST /channels/{id}/acknowledge                                → acknowledge()
      POST /channels/{id}/nack                                       → nack()
      GET  /channels/{id}/info                                       → channel metadata
    
    Cursor state: Managed server-side. The reader_id from the auth token
    identifies the cursor. Each authenticated reader has a persistent cursor
    in the MessageStore. The `after` parameter allows explicit cursor override.
    
    Auth: Uses channel.security on every request. Token from Authorization header.
    """
    ...

class IpcTransport(ChannelTransport):
    """Shared-memory or Unix socket. Sub-millisecond latency."""
    ...
```

### 4.11 Visibility

```python
class Visibility(Enum):
    PRIVATE = "private"   # Internal only. Default. Not exposed when published.
    PUBLIC = "public"     # Exposed to the internet when umbrella calls publish().
```

Set per-channel at creation. `publish()` only mounts PUBLIC channels onto the HTTP server.

### 4.12 Scope

The channel design intentionally does NOT reconstruct the internet, replace Kafka/RabbitMQ, or provide distributed transactions. It DOES provide a unified, typed, access-controlled abstraction for agent-centric information flows. For use cases already served by existing tools, write a thin adapter channel.


## 5. Channel Class Hierarchy

`BaseChannel` is the fully general base class. Convenience subclasses pre-wire common patterns with reduced interface surface:

```
BaseChannel                         ← Full power. Implement pull_fn + convert_fn.
│
├── PassthroughChannel              ← No ingestion. Inline writes. Simplest.
│   │
│   ├── BroadcastChannel            ← Shared + subscribe. exclusive=True raises.
│   ├── WorkQueueChannel            ← Exclusive + acknowledge. exclusive=False raises.
│   └── MailboxChannel              ← Shared, auto-filters by recipient_id.
│
├── PeriodicSourceChannel           ← Pulls from external source. Background loop.
│
└── DiscoveryChannel                ← Built-in network registry.
```

### 5.1 PassthroughChannel

No external source. Writes processed inline (zero latency). The building block for inter-system communication.

### 5.2 BroadcastChannel

Shared + subscribe. `read(exclusive=True)` raises. No persistence by default. For alerts, telemetry, notifications.

```python
class BroadcastChannel(PassthroughChannel):
    async def read(self, reader_id, limit=10, exclusive=False, **kw):
        if exclusive:
            raise TypeError("BroadcastChannel does not support exclusive reads.")
        return await super().read(reader_id, limit, exclusive=False, **kw)
```

### 5.3 WorkQueueChannel

Exclusive + acknowledge. `read(exclusive=False)` raises. Persistence by default. Unclaimed messages are reclaimed after `claim_timeout`. Workers must `acknowledge()` completion — unacknowledged claims are returned to the pool.

```python
class WorkQueueChannel(PassthroughChannel):
    claim_timeout: float = 300.0  # 5 min default

    async def read(self, reader_id, limit=10, exclusive=False, **kw):
        if not exclusive:
            raise TypeError("WorkQueueChannel only supports exclusive reads. Use read(exclusive=True).")
        # Lazy reclaim: run before every exclusive read so workers see jobs
        # as soon as claim_timeout expires — not delayed by maintenance schedule.
        self._store.reclaim_expired(timeout=self.claim_timeout)
        return await super().read(reader_id, limit, exclusive=True, **kw)

    async def nack(self, reader_id: str, message_ids: List[str]):
        """Release claims immediately — jobs return to the pool without waiting for claim_timeout."""
        self._store.nack(reader_id, message_ids)

    async def on_maintain(self):
        """Maintenance also reclaims, as a belt-and-suspenders fallback."""
        await super().on_maintain()
        self._store.reclaim_expired(timeout=self.claim_timeout)
```

**Reclaim timing**: Stale claims are reclaimed eagerly on every `read(exclusive=True)` call, not just at maintenance intervals. This means a crashed worker's job is visible again within one polling cycle after `claim_timeout` expires — no multi-minute lag from coarse maintenance scheduling.

### 5.4 MailboxChannel

Shared mode, auto-filters by `recipient_id` matching `reader_id`.

**Performance note**: Filtering is O(N) over fetched messages. For most agentic networks (tens of systems, thousands of messages), this is fine. For high-volume channels with many recipients, consider per-recipient channels (`commands-robot-1`, `commands-robot-2`) or a custom indexed `MessageStore`.

### 5.5 PeriodicSourceChannel

Pulls from external source via background loop. Developer implements `pull_fn` and `convert_fn`.

### 5.6 DiscoveryChannel

Built-in channel that stores `ChannelInfo` and `ServiceDescriptor` records. Opt-in infrastructure for dynamic networks. Standard `write()` / `read()` work normally; convenience methods layer on top.

```python
class DiscoveryChannel(PassthroughChannel):
    registration_ttl: float = 3600.0   # Default: 1 hour. Registrations expire if not refreshed.

    # === Convenience write helpers ===

    async def register_channel(self, info: ChannelInfo, ttl: Optional[float] = None):
        """
        Write a channel registration. Expires after ttl seconds (default: registration_ttl).
        To keep alive, call again before expiry. Stale registrations are purged by on_maintain().
        """
        ...

    async def register_system(self, descriptor: ServiceDescriptor, ttl: Optional[float] = None):
        """
        Write a system service descriptor. Same TTL semantics as register_channel().
        Systems should re-register on a heartbeat interval shorter than registration_ttl.
        """
        ...

    # === Convenience query helpers ===

    async def find_channels(
        self,
        tag: Optional[str] = None,
        visibility: Optional[Visibility] = None,
    ) -> List[ChannelInfo]:
        """Return non-expired registered channels matching optional filters."""
        ...

    async def find_systems(
        self, capability: Optional[str] = None
    ) -> List[ServiceDescriptor]:
        """Return non-expired registered systems, optionally filtered by exposed method name."""
        ...

    async def get_channel(self, channel_id: str) -> Optional[ChannelInfo]:
        """Look up a non-expired channel by ID. Returns None if not found or expired."""
        ...

    async def get_system(self, system_id: str) -> Optional[ServiceDescriptor]:
        """Look up a non-expired system by ID. Returns None if not found or expired."""
        ...

    async def on_maintain(self):
        """Purge expired registrations. Runs on the wall-clock maintenance schedule."""
        await super().on_maintain()
        # Remove messages whose content has exceeded its TTL
        ...
```

**Stale registration**: Systems that crash or shut down without deregistering leave stale records. The TTL mechanism handles this automatically — registrations expire unless refreshed. Systems should re-register on a heartbeat interval (e.g., every `registration_ttl / 2` seconds). Query methods only return non-expired records.

All query methods read from the in-memory store — they do not issue network requests. For remote discovery channels, connect via `ChannelClient` and use `read()` directly.


## 6. System

### 6.1 Three Registration Levels

**Level 1 — Register**: Get a ChannelClient. No metadata, no lifecycle.

```python
client = sssn.register(id="my-tool", name="My Tool")
msgs = await client.read("news", limit=10)
```

**Level 2 — Decorate**: Adds metadata and service exposure. Existing code untouched.

```python
@sssn.system(id="knowledge-engine", name="Knowledge Engine")
class KE:
    @sssn.expose(description="Search papers")
    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        return self.db.search(query, top_k)
```

**Level 3 — Inherit**: Full lifecycle, directories, umbrella capabilities.

```python
class Master(sssn.BaseSystem):
    async def step(self):
        msgs = await self.read_channel("requests", limit=5)
        ...
```

### 6.2 Service Exposure

`@sssn.expose` collects method metadata into a `ServiceDescriptor` for discovery. **It does not create RPC stubs or callable proxies.** Calling exposed methods is done through standard mechanisms — direct Python references for in-process, standard HTTP for remote. SSSN provides discovery (finding *what* a system offers) but not invocation (calling it). This keeps the framework focused on channels.

```python
class ServiceDescriptor(BaseModel):
    system_id: str
    system_name: str
    description: str
    services: List[ServiceMethod]
    channels_read: List[str]
    channels_write: List[str]
```

### 6.3 BaseSystem

```python
class BaseSystem(abc.ABC):
    id: str
    name: str
    description: str
    state: SystemState
    client: ChannelClient
    
    # Descriptive directories
    channel_directory: List[str]
    system_directory: List[str]
    
    # Umbrella capabilities
    _channels: List[BaseChannel]
    _subsystems: List[BaseSystem]
    
    # === Step (override in subclasses; default is no-op for umbrella systems) ===
    async def step(self): pass
    
    # === Lifecycle ===
    async def setup(self):
        """
        One-time setup hook. Called by launch() and publish() before starting.
        Override to create channels and sub-systems.
        IDEMPOTENT: guarded by _setup_done flag — safe if called multiple times.
        """
        pass

    async def run(self, tick_rate: float = 1.0):
        """
        Run the system's main loop. Calls step() repeatedly at tick_rate ticks/sec.

        tick_rate: calls to step() per second. tick_rate=1.0 → step() every ~1s.
                   Actual interval = max(1/tick_rate, time(step())).
                   If step() takes longer than 1/tick_rate, the next call starts
                   immediately after (no sleep). There is no drift accumulation.

        Error contract: exceptions raised in step() are caught and forwarded to
        on_step_error(). The loop continues. To shut down on error, call self.stop()
        from on_step_error().

        Termination: returns cleanly when stop() is called. Finishes the current
        step() before exiting. Does NOT propagate step() exceptions to the caller.
        """
        ...

    async def on_step_error(self, error: Exception):
        """
        Called when step() raises an exception. Default: log and continue.
        Override to add alerting, circuit-breaking, or self.stop().
        """
        logger.error(f"[{self.id}] Error in step(): {error}")

    def stop(self): ...
    def pause(self): ...
    def resume(self): ...
    
    # === Umbrella ===
    def add_channel(self, channel: BaseChannel):
        self._channels.append(channel)
        self.register_channel(channel.id)
    
    def add_subsystem(self, system: BaseSystem, channels: Optional[List[str]] = None):
        """
        Register a sub-system. 
        `channels`: explicit list of channel IDs to wire. If None, NO auto-wiring.
        The developer must specify which channels each sub-system accesses.
        """
        self._subsystems.append(system)
        self.register_peer(system.id)
        if channels:
            for ch_id in channels:
                ch = next((c for c in self._channels if c.id == ch_id), None)
                if ch: system.client.connect(ch_id, ch)
    
    async def launch(self):
        """Start all channels and systems locally. No HTTP exposure."""
        if not self._setup_done:
            await self.setup()
            self._setup_done = True
        for ch in self._channels: await ch.start()
        await asyncio.gather(*[s.run() for s in self._subsystems], self.run())

    async def publish(self, host="0.0.0.0", port=8000, server=None):
        """Expose PUBLIC channels via HTTP and start the entire network."""
        if not self._setup_done:
            await self.setup()
            self._setup_done = True
        server = server or ChannelServer(host=host, port=port)
        for ch in self._channels:
            if ch.visibility == Visibility.PUBLIC:
                ch.attach_transport(HttpTransport(server=server))
            await ch.start()
        tasks = [s.run() for s in self._subsystems]
        tasks.append(self.run())
        tasks.append(server.start())
        await asyncio.gather(*tasks)
    
    # === Channel convenience ===
    async def read_channel(self, ch_id, **kw): return await self.client.read(ch_id, **kw)
    async def write_channel(self, ch_id, **kw): return await self.client.write(ch_id, **kw)
    async def claim_channel(self, ch_id, **kw): return await self.client.read(ch_id, exclusive=True, **kw)
    async def acknowledge_channel(self, ch_id, message_ids): return await self.client.acknowledge(ch_id, message_ids)
    async def nack_channel(self, ch_id, message_ids): return await self.client.nack(ch_id, message_ids)
    async def subscribe_channel(self, ch_id, cb): return await self.client.subscribe(ch_id, cb)
    async def announce(self, discovery_channel_id):
        await self.client.write(discovery_channel_id, data=self.service_descriptor.model_dump())
```

### 6.4 ChannelClient

```python
class ChannelClient:
    """
    Handle for channel operations. Resolves channel IDs to local references
    or remote HTTP endpoints and dispatches accordingly.
    
    For local channels: direct method calls (zero overhead).
    For remote channels: HTTP requests via the transport's REST API.
    Cursor state for remote shared reads is managed server-side,
    keyed by the authenticated system_id.
    """
    system_id: str
    _local: Dict[str, BaseChannel]      # channel_id → local reference
    _remote: Dict[str, Tuple[str, str]] # channel_id → (url, token)
    
    async def read(self, channel_id, **kw) -> List[ChannelMessage]:
        if channel_id in self._local:
            return await self._local[channel_id].read(reader_id=self.system_id, **kw)
        elif channel_id in self._remote:
            return await self._http_read(channel_id, **kw)
        raise KeyError(f"Channel '{channel_id}' not connected.")

    async def write(self, channel_id, **kw) -> str:
        if channel_id in self._local:
            return await self._local[channel_id].write(sender_id=self.system_id, **kw)
        elif channel_id in self._remote:
            return await self._http_write(channel_id, **kw)
        raise KeyError(f"Channel '{channel_id}' not connected.")

    async def acknowledge(self, channel_id: str, message_ids: List[str]):
        if channel_id in self._local:
            return await self._local[channel_id].acknowledge(reader_id=self.system_id, message_ids=message_ids)
        elif channel_id in self._remote:
            return await self._http_acknowledge(channel_id, message_ids)
        raise KeyError(f"Channel '{channel_id}' not connected.")

    async def nack(self, channel_id: str, message_ids: List[str]):
        if channel_id in self._local:
            return await self._local[channel_id].nack(reader_id=self.system_id, message_ids=message_ids)
        elif channel_id in self._remote:
            return await self._http_nack(channel_id, message_ids)
        raise KeyError(f"Channel '{channel_id}' not connected.")

    async def subscribe(self, channel_id: str, callback: Callable[[ChannelMessage], Any]):
        """Local channels only. Remote channels do not support push (see §4.9)."""
        if channel_id in self._local:
            return await self._local[channel_id].subscribe(system_id=self.system_id, callback=callback)
        raise TypeError(f"subscribe() is not supported for remote channels ('{channel_id}'). Use read() polling.")

    async def unsubscribe(self, channel_id: str):
        if channel_id in self._local:
            return await self._local[channel_id].unsubscribe(system_id=self.system_id)

    def connect(self, channel_id: str, channel: BaseChannel):
        self._local[channel_id] = channel

    def connect_remote(self, channel_id: str, url: str, token: Optional[str] = None):
        self._remote[channel_id] = (url, token or "")

    def connect_from_config(self, config: Dict[str, str]):
        for ch_id, url in config.items():
            self.connect_remote(ch_id, url)
```


## 7. Security

### 7.1 Principle

**Permissions are granted externally, by the network operator, not by the network itself.** The operator defines access policies, generates credentials, and distributes them out-of-band (env vars, config files, secrets managers). SSSN provides mechanisms; the operator provides policy.

### 7.2 ChannelSecurity

```python
class ChannelSecurity(abc.ABC):
    async def authenticate(self, token: str) -> Optional[str]:
        """Verify token, return system_id or None.""" ...
    async def authorize_read(self, system_id: str, channel_id: str) -> bool: ...
    async def authorize_write(self, system_id: str, channel_id: str) -> bool: ...
    async def authorize_admin(self, system_id: str, channel_id: str) -> bool: ...
    async def generate_token(self, system_id: str, role: str,
                             channel_ids: Optional[List[str]] = None,
                             expires_in: float = 86400) -> str: ...
```

Note: `generate_token` accepts an optional `channel_ids` list. When present, the token is scoped to those specific channels only. When absent, the token grants access to all channels using the same security instance. This prevents a write token for the task queue from granting write access to unrelated channels.

**`subscribe()` is a read operation for security purposes.** Registering a push callback is authorized via `authorize_read`. A system without read access cannot subscribe.

**Token expiry**: `ChannelClient` embeds tokens in HTTP headers on every request. The client does NOT auto-refresh tokens. When a JWT token expires, remote operations raise `PermissionError`. Token lifecycle strategy:
- For short-lived deployments: use a token expiry longer than the deployment duration.
- For long-lived processes: implement token refresh by overriding `ChannelClient._http_read/write` to catch `PermissionError`, refresh the token via `security.generate_token()`, and retry. The framework deliberately leaves this to the operator — it does not store secrets.

### 7.3 Built-in Implementations

```python
class JWTChannelSecurity(ChannelSecurity):
    """
    JWT tokens with optional per-channel scoping.
    Token payload: {sub: system_id, role: "read"|"write"|"admin", 
                    channels: ["ch1", "ch2"] | null, exp: timestamp}
    """
    ...

class ACLSecurity(ChannelSecurity):
    """Simple access-control lists. Uses system_id directly. For local networks."""
    ...

class OpenSecurity(ChannelSecurity):
    """No auth. Default for local development."""
    ...
```

### 7.4 Admin Tools

CLI utilities for operators (not framework primitives):

```bash
sssn token generate --system-id designer-1 --role write --channels design-commands,design-delivery
sssn acl show --channel design-commands
sssn acl grant --channel design-commands --system-id designer-1 --role write
```


## 8. Network Topology

### 8.1 Local vs Public

**Local**: Same machine/cluster. In-process or local HTTP/IPC. Default.

**Public**: Selected channels exposed to the internet via `publish()` + reverse proxy.

### 8.2 Discovery

**Direct connection** (most common): Connect by reference or URL.

**Discovery channel** (opt-in): Built-in `DiscoveryChannel` stores channel registrations and service descriptors. Systems announce themselves and query for available resources.

**Config-driven**: Load channel URLs from a YAML file or environment variables.

### 8.3 Shared Server

```python
server = ChannelServer(host="0.0.0.0", port=8000)
# publish() mounts PUBLIC channels here automatically.
```


## 9. Request-Response Helper

A utility function, not a new abstraction:

```python
async def request_via_channel(
    request_channel, response_channel, sender_id, data, timeout=30.0
) -> Optional[ChannelMessage]:
    corr_id = str(uuid.uuid4())
    msg = ChannelMessage(
        id=corr_id, timestamp=time.time(), sender_id=sender_id,
        content=GenericContent(data=data), metadata={},
        correlation_id=corr_id, reply_to=response_channel.id,
    )
    await request_channel.write(sender_id, msg, direct=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await response_channel.read(reader_id=sender_id, limit=50)
        for r in msgs:
            if r.correlation_id == corr_id: return r
        await asyncio.sleep(0.5)
    return None
```


## 10. Case Study: Genesys

### 10.1 Systems

| System | Level | Why |
|--------|-------|-----|
| **Evolutionary Master** | `BaseSystem` | Needs run loop, budget management |
| **Proposer-Reviewer** | `BaseSystem` (wraps LLLM) | Run loop, polls for commands |
| **Implementer** | `BaseSystem` (wraps LLLM) | Run loop, claims commands |
| **Verifier** (×N) | `BaseSystem` | GPU worker, claims eval jobs |
| **Knowledge Engine** | `@sssn.system` + `@sssn.expose` | Reactive service, no run loop |
| **Symbolic Checker** | `@sssn.system` + `@sssn.expose` | Stateless utility |

### 10.2 Channels

| Channel | Class | Visibility | Description |
|---------|-------|-----------|-------------|
| **Design Request (DR)** | `PassthroughChannel` | PUBLIC | External designers can submit |
| **Design Command (DC)** | `WorkQueueChannel` | PRIVATE | Master → one designer |
| **Design Delivery (DD)** | `PassthroughChannel` | PRIVATE | Designers → Master |
| **Eval Request (ER)** | `PassthroughChannel` | PRIVATE | Master posts eval needs |
| **Eval Command (EC)** | `WorkQueueChannel` | PRIVATE | Master → one verifier |
| **Eval Delivery (ED)** | `PassthroughChannel` | PRIVATE | Verifiers → Master |
| **Evolution Tree (ET)** | Custom (Firebase) | PUBLIC | All designs, metrics, lineage |
| **Leaderboard** | `BroadcastChannel` | PUBLIC | Real-time rankings |

### 10.3 LLLM Bridge

```python
class ImplementerSystem(BaseSystem):
    def __init__(self, tactic, **kwargs):
        super().__init__(**kwargs)
        self.tactic = tactic  # LLLM Tactic
    
    async def step(self):
        jobs = await self.read_channel("design-commands", exclusive=True, limit=1)
        if not jobs: return
        cmd = jobs[0]
        result = self.tactic(task={"parents": cmd.content.parent_gau_trees, ...})
        delivery = DesignDelivery(design_name=result.name, code=result.code, ...)
        await self.write_channel("design-delivery", data=delivery)
        await self.client.acknowledge("design-commands", [cmd.id])
```

### 10.4 Umbrella

```python
class GenesysNetwork(sssn.BaseSystem):
    async def setup(self):
        sec = sssn.JWTChannelSecurity(secret=os.environ["SSSN_SECRET"])
        
        self.add_channel(sssn.PassthroughChannel(id="design-requests", visibility=Visibility.PUBLIC, security=sec))
        self.add_channel(sssn.WorkQueueChannel(id="design-commands", security=sec, claim_timeout=600))
        self.add_channel(sssn.PassthroughChannel(id="design-delivery", security=sec))
        self.add_channel(sssn.WorkQueueChannel(id="eval-commands", security=sec))
        self.add_channel(sssn.PassthroughChannel(id="eval-delivery", security=sec))
        self.add_channel(EvolutionTreeChannel(id="evolution-tree", visibility=Visibility.PUBLIC, ...))
        self.add_channel(sssn.BroadcastChannel(id="leaderboard", visibility=Visibility.PUBLIC, security=sec))
        
        master = EvolutionaryMaster(id="master", name="Master")
        self.add_subsystem(master, channels=["design-requests", "design-commands", "design-delivery",
                                              "eval-commands", "eval-delivery", "evolution-tree", "leaderboard"])
        for i in range(4):
            d = ImplementerSystem(id=f"designer-{i}", tactic=make_designer_tactic(), name=f"Designer {i}")
            self.add_subsystem(d, channels=["design-commands", "design-delivery", "evolution-tree"])
        for i in range(8):
            v = Verifier(id=f"verifier-{i}", name=f"Verifier {i}")
            self.add_subsystem(v, channels=["eval-commands", "eval-delivery", "evolution-tree"])
    
    async def step(self): pass

# Local: asyncio.run(GenesysNetwork(id="genesys", name="Genesys").launch())
# Public: asyncio.run(GenesysNetwork(id="genesys", name="Genesys").publish(port=8000))
```


## 11. Case Study: Warehouse Robot Fleet

| Channel | Class | Transport | Purpose |
|---------|-------|-----------|---------|
| **Task Queue** | `WorkQueueChannel` | In-Process | Coordinator → robots |
| **Robot Telemetry** | `BroadcastChannel` | IPC | 100Hz position/battery |
| **Safety Alerts** | `BroadcastChannel` | In-Process | Emergency stops |
| **Fleet Status** | `PassthroughChannel` | HTTP | Dashboard view |
| **Override Commands** | `MailboxChannel` | HTTP | Human → specific robot |


## 12. Development Workflow

### 12.1 Five Phases

| Phase | What you do | Output |
|-------|------------|--------|
| **1. Think in Flows** | Diagram topology. List channels (name, mode, visibility). List systems. | Tables + diagram |
| **2. Prototype** | PassthroughChannel + register() in one process. `launch()`. | Working local flow |
| **3. Harden** | Typed content, persistence, security, error handling. | Production-ready |
| **4. Distribute** | HTTP transport, remote connections. | Multi-process |
| **5. Publish** | `publish()`. Public channels go live. | Service on the internet |

### 12.2 Minimal Example

```python
import asyncio, sssn

async def main():
    ch = sssn.PassthroughChannel(id="chat", name="Chat")
    await ch.start()
    alice = sssn.register(id="alice", name="Alice")
    alice.connect("chat", ch)
    await alice.write("chat", data={"text": "Hello!"})
    bob = sssn.register(id="bob", name="Bob")
    bob.connect("chat", ch)
    msgs = await bob.read("chat", limit=10)
    print(msgs[0].content.data)  # {"text": "Hello!"}

asyncio.run(main())
```

### 12.3 Best Practices

**Start with channels, not systems.** Draw the information flows first.

**One channel per concern.** Don't multiplex unrelated data.

**Use typed content for production channels.** Schema errors caught at write-time.

**Explicit wiring.** Use `add_subsystem(sys, channels=[...])` with explicit channel lists. Least privilege.

**Let on_maintain() handle cleanup.** Set retention params; override only for custom logic.

**Public channels need typed content and security.** No `GenericContent` or `OpenSecurity` on public channels.


## 13. Concurrency Extension Points

The default (asyncio, in-memory) handles typical agentic networks. Every bottleneck component is swappable:

| Throughput need | What you swap | Interface change |
|----------------|---------------|-----------------|
| ~100 msg/s (default) | Nothing | None |
| ~10K msg/s | Redis/Kafka MessageStore | None |
| ~100K msg/s | + GrpcTransport | None |
| CPU-bound convert_fn | Override on_process() with ProcessPool | None |
| Millions msg/s | ShardedChannel wrapper | Thin wrapper |


## 14. Design Decisions

### 14.1 ChannelDBClient vs LLLM LogBackend

Separate interfaces. LogBackend is sync, key→bytes, prefix-listing. ChannelDBClient is async, message-typed, time-range-indexed. Different access patterns. Implementations share underlying libraries (aiosqlite, firebase-admin) — code *similarity*, not code *sharing*.

### 14.2 Unified read/write Interface

`read(exclusive=False|True)` instead of separate `read()` and `claim()`. `write(direct=False|True)` instead of separate `write()` and `write_direct()`. The base class has one method per operation; convenience subclasses restrict modes by raising on invalid flag values. This keeps the base interface minimal (6 consumption methods: read, write, subscribe, unsubscribe, acknowledge, nack) while derived classes provide guardrails.

**Why `nack()` is in the base interface**: `acknowledge()` and `nack()` are symmetric. Just as `acknowledge()` is a no-op for non-exclusive messages, `nack()` is a no-op for non-exclusive messages. Including both in the base interface keeps the contract complete: claim → process → acknowledge (success) or nack (failure).


## 15. File Structure

```
sssn/
├── core/
│   ├── __init__.py
│   ├── system.py           # BaseSystem, SystemState, @sssn.system, @sssn.expose, sssn.register()
│   ├── channel.py          # BaseChannel, ChannelMessage, MessageContent, MessageStore
│   ├── client.py           # ChannelClient
│   ├── db.py               # ChannelDBClient + SqliteDBClient, FileDBClient, FirebaseDBClient
│   ├── transport.py        # ChannelTransport + InProcessTransport, HttpTransport, IpcTransport
│   └── security.py         # ChannelSecurity + JWTChannelSecurity, OpenSecurity, ACLSecurity
├── channels/
│   ├── __init__.py
│   ├── passthrough.py      # PassthroughChannel
│   ├── broadcast.py        # BroadcastChannel
│   ├── work_queue.py       # WorkQueueChannel
│   ├── mailbox.py          # MailboxChannel
│   ├── periodic.py         # PeriodicSourceChannel
│   └── discovery.py        # DiscoveryChannel
├── infra/
│   ├── __init__.py
│   ├── server.py           # ChannelServer
│   └── helpers.py          # request_via_channel, etc.
├── utils/
│   └── general.py
├── __init__.py
└── py.typed
```


## 16. Design Principles

1. **Learn one thing**: The Channel.
2. **Channels are material**: Persistent, managed, observable infrastructure.
3. **Minimal base interface**: 6 consumption methods + 3 host operations. Patterns emerge from flags and message fields.
4. **Non-intrusive systems**: Three registration levels.
5. **Transparent systems**: `@sssn.expose` and `ServiceDescriptor` for discovery.
6. **Transport-agnostic**: Board logic separate from transport.
7. **Always serializable**: Pydantic BaseModel throughout.
8. **Security from the start**: Abstract ChannelSecurity with built-in JWT + per-channel token scoping.
9. **External security authority**: Operator grants permissions out-of-band.
10. **Host authority**: Channel operators control content lifecycle.
11. **Log-first store**: Non-destructive reads with cursors. Exclusive claims require acknowledgment.
12. **Graceful shutdown**: `drain()` for zero-message-loss redeployment.
13. **Independence from LLLM**: No imports. Composability via adapters.
14. **Private by default, publish explicitly**: Visibility.PRIVATE default. `publish()` exposes only PUBLIC.
15. **Flat network, private nesting**: Network sees peers. Internal composition is private.
