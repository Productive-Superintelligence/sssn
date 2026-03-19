# Channel

A channel is a **typed, secured, persistent message store** with a well-defined consumption interface. It is the only way data moves between systems in an SSSN network.

---

## The six consumption methods

Every channel exposes exactly six methods to consumers:

| Method | Description |
|--------|-------------|
| `read(reader_id, limit, exclusive, after)` | Pull messages — shared (cursor) or exclusive (claim) |
| `write(sender_id, data, direct)` | Push data into the channel |
| `subscribe(system_id, callback)` | Register a push callback for new messages |
| `unsubscribe(system_id)` | Remove a push callback |
| `acknowledge(reader_id, message_ids)` | Mark exclusively-claimed messages as done |
| `nack(reader_id, message_ids)` | Release claims immediately without consuming |

And three **host operations** (owner/admin only):

| Method | Description |
|--------|-------------|
| `clear(filter_fn)` | Remove messages matching a predicate (or all) |
| `evict(before, max_count)` | Enforce retention by age and/or count |
| `remove(message_ids)` | Remove specific messages by ID |

---

## Message model

Every unit of data in a channel is a `ChannelMessage` — a frozen (immutable) Pydantic model:

```python
class ChannelMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str                          # Stable unique identifier
    timestamp: float                 # Unix epoch seconds
    sender_id: str                   # Who wrote this
    content: MessageContent          # Always a Pydantic model — always serialisable

    # Optional fields for common patterns
    correlation_id: str | None       # Thread messages across channels
    reply_to: str | None             # Channel ID for response routing
    recipient_id: str | None         # Mailbox targeting
    metadata: dict[str, Any]         # Arbitrary key-value annotations
```

`content` is always a `MessageContent` subclass. The default wrapper is `GenericContent(data=...)`:

```python
class MessageContent(BaseModel):
    model_config = ConfigDict(extra="allow")  # Extra fields are silently accepted

class GenericContent(MessageContent):
    data: Any = None
```

To define a typed payload, subclass `MessageContent`:

```python
class SensorReading(MessageContent):
    sensor_id: str
    temperature: float
    unit: str = "celsius"
```

---

## Read modes

### Shared read (default)

```python
msgs = await channel.read("my-system", limit=10)
```

Every reader has an **independent cursor**. Reading does not consume messages — all readers see all messages (except those acknowledged or currently claimed by another reader). The cursor advances automatically; call with `after="<message-id>"` to seek to a specific position.

```
Store:  [m1] [m2] [m3] [m4] [m5]
Reader A cursor: ──────────────►  (has read all 5)
Reader B cursor: ──────►          (has read m1–m3, next call returns m4, m5)
```

### Exclusive read (claim)

```python
msgs = await channel.read("worker-1", limit=5, exclusive=True)
```

Claims messages for **exclusive processing**. Claimed messages are invisible to all other readers until:

- `acknowledge()` is called (permanent removal), or
- `nack()` is called (immediate release), or
- the claim expires after `claim_timeout` seconds (WorkQueueChannel).

The `after` parameter is **ignored** for exclusive reads — claims always pull from the full unclaimed pool.

---

## Write modes

### Buffered write (default)

```python
item_id = await channel.write("sender", {"key": "value"})
```

Data enters the ingestion pipeline: raw buffer → `convert_fn()` → store. Returns an `item_id` that is **not** a stable message ID — do not use it to query the store.

!!! note "Backpressure"
    If the raw buffer exceeds `max_raw_buffer_size` (default: 10,000 items), `write()` raises `RuntimeError` immediately. This prevents unbounded memory growth when producers outpace the ingestion pipeline.

### Direct write

```python
msg_id = await channel.write("sender", my_channel_message, direct=True)
```

`data` must be a `ChannelMessage`. It bypasses `convert_fn()` and goes straight to `on_message()`. Returns the message's stable `id`.

Use `direct=True` when you have already constructed the `ChannelMessage` (e.g., for request-response correlation).

---

## MessageStore

The `MessageStore` is the in-memory backing of every channel. It maintains:

- `messages: list[ChannelMessage]` — append-only log
- `cursors: dict[str, int]` — per-reader cursor positions
- `claims: dict[str, tuple[str, float]]` — msg_id → (claimer_id, claim_time)
- `acknowledged: set[str]` — permanently consumed message IDs
- `subscribers: dict[str, Callable]` — push callbacks

Messages are **never removed by reads**. They persist until a host operation (`clear`, `evict`, or `remove`) explicitly removes them. This means:

- Slow readers never miss messages (unless evicted by retention policy)
- Multiple readers with different paces are fully independent
- The store acts as a truth-log, not a transient queue

---

## Subscriber notifications

`subscribe()` registers an async callback that fires on every new message:

```python
async def handler(msg: ChannelMessage):
    print(f"Received: {msg.content}")

await channel.subscribe("my-listener", handler)
```

Under the hood, `notify_subscribers()` uses `asyncio.gather(..., return_exceptions=True)`. **A failing subscriber never silences others** — exceptions are logged and execution continues.

---

## Lifecycle

```
               ┌──────────┐
               │  start() │  sets _is_running=True, starts background loop
               └────┬─────┘
                    │
          ┌─────────▼──────────┐
          │   _run_loop()      │  on_pull → on_process → [on_maintain] → sleep(period)
          └─────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │   stop() / drain()  │
         └─────────────────────┘
```

- **`start()`** — calls `on_start()` (initialises DB, transport), then creates the background loop task.
- **`stop()`** — sets `_is_running = False`. The current loop iteration completes, then the task exits. Does **not** call `on_stop()`. Non-blocking.
- **`drain(timeout)`** — graceful shutdown. Stops accepting writes, waits for the raw buffer to empty (up to `timeout` seconds), then calls `on_stop()`.

### Loop hooks (overridable)

| Hook | Called | Default |
|------|--------|---------|
| `on_start()` | Once, before loop | Init DB + transport |
| `on_pull()` | Every cycle | Calls `pull_fn()` |
| `on_process()` | Every cycle | Drains raw buffer → `convert_fn()` → store |
| `on_message(msg)` | Per message | Append + DB save + notify subscribers |
| `on_maintain()` | Every `maintenance_interval_seconds` (wall-clock) | Evict by retention policy |
| `on_error(phase, error)` | On any exception | Log + continue |
| `on_stop()` | Once, on drain | Stop transport |

---

## Configuration reference

```python
BaseChannel(
    id="my-channel",
    name="My Channel",
    description="",
    visibility=Visibility.PRIVATE,     # PRIVATE or PUBLIC (exposed via HTTP)
    period=60.0,                        # Loop sleep interval in seconds
    max_workers=10,                     # Concurrent convert_fn() tasks
    max_raw_buffer_size=10_000,         # Backpressure threshold
    retention_max_age=None,             # Evict messages older than N seconds
    retention_max_count=None,           # Keep only the N newest messages
    maintenance_interval_seconds=60.0,  # Wall-clock interval for on_maintain()
    db_client=None,                     # Optional persistence backend
    transport=None,                     # Optional HTTP transport
    security=None,                      # Defaults to OpenSecurity
)
```

---

## Implementing a custom channel

Subclass `BaseChannel` and implement two abstract methods:

```python
from sssn.core.channel import BaseChannel, ChannelMessage
import httpx

class WeatherChannel(BaseChannel):
    async def pull_fn(self) -> None:
        """Fetch raw data from an external source every cycle."""
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.weather.example/current")
            data = resp.json()
        # Queue data for conversion
        await self.write("weather-api", data)

    async def convert_fn(self, sender_id: str, raw_data: dict) -> ChannelMessage | None:
        """Transform raw API response into a ChannelMessage."""
        if "temperature" not in raw_data:
            return None  # Discard malformed data
        return ChannelMessage(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            sender_id=sender_id,
            content=SensorReading(
                sensor_id="weather-api",
                temperature=raw_data["temperature"],
            ),
        )
```

For channels where data arrives via `write()` rather than a pull loop, use [`PassthroughChannel`](channel-types.md#passthroughchannel) as the base.
