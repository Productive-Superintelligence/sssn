# Channel Types

SSSN ships six built-in channel variants. All inherit from `BaseChannel`; the hierarchy is shallow and easy to extend.

```
BaseChannel
├── PassthroughChannel       (no pull loop; inline write)
│   ├── BroadcastChannel     (shared reads only; fan-out)
│   ├── WorkQueueChannel     (exclusive reads only; competing consumers)
│   ├── MailboxChannel       (per-recipient filtering)
│   └── DiscoveryChannel     (service registry with TTL)
└── PeriodicChannel          (marker — full pull loop; implement pull_fn)
```

---

## PassthroughChannel

**Use when** data arrives via `write()` calls rather than an active pull loop.

`PassthroughChannel` disables the background loop by overriding `start()` to skip `asyncio.create_task(_run_loop())`. Conversion happens **inline inside `write()`** — every call completes with the message in the store and subscribers notified before returning.

```python
from sssn.channels.passthrough import PassthroughChannel

channel = PassthroughChannel(id="events", name="Events")
await channel.start()

msg_id = await channel.write("producer", {"value": 42})
# Message is in the store NOW — no background cycle needed.
msgs = await channel.read("consumer", limit=10)
```

**Key properties:**

- No loop task created — `_loop_task` is always `None`.
- `write()` returns a **stable message ID** (not a buffer item ID).
- `convert_fn()` is provided: wraps anything in `GenericContent`, passes through `ChannelMessage` unchanged.
- `pull_fn()` is a no-op. Override it if you also override `start()` to enable the loop.

**Extending `PassthroughChannel`** — override only what you need:

```python
class AuditChannel(PassthroughChannel):
    async def on_message(self, msg):
        print(f"[AUDIT] {msg.sender_id} → {msg.content}")
        await super().on_message(msg)
```

---

## BroadcastChannel

**Use when** every consumer should receive every message (fan-out / event bus).

```python
from sssn.channels.broadcast import BroadcastChannel

bus = BroadcastChannel(id="telemetry", name="Telemetry Bus")
await bus.start()

# Push pattern (preferred — zero latency)
async def on_event(msg):
    print(msg.content)

await bus.subscribe("dashboard", on_event)
await bus.write("sensor", {"temp": 22.4})
# → on_event fires immediately

# Poll pattern (late-joining consumers can catch up)
history = await bus.read("late-reader", limit=100)
```

**Constraint:** `exclusive=True` raises `TypeError`. Use `subscribe()` for push or `read()` (shared) for pull.

---

## WorkQueueChannel

**Use when** each message should be processed by **exactly one worker** (competing consumers, task distribution).

```python
from sssn.channels.work_queue import WorkQueueChannel

queue = WorkQueueChannel(id="jobs", name="Job Queue", claim_timeout=300.0)
await queue.start()

# Producer
await queue.write("scheduler", {"task": "resize", "file": "img.png"})

# Worker
msgs = await queue.read("worker-1", limit=5, exclusive=True)
for msg in msgs:
    try:
        await process(msg)
        await queue.acknowledge("worker-1", [msg.id])
    except Exception:
        await queue.nack("worker-1", [msg.id])  # Return to pool
```

**Semantics:**

- All reads **must** be exclusive (`exclusive=True`). Shared reads raise `TypeError`.
- Claimed messages are invisible to other workers until acknowledged, nacked, or expired.
- Expired claims are **lazily reclaimed** on every `read()` call — dead workers do not permanently starve the queue.
- `on_maintain()` also runs periodic reclaim at the maintenance interval.

**`claim_timeout`** (seconds, default: `300`): How long a worker may hold a claim before it is automatically released. Set it to slightly longer than your worst-case processing time.

---

## MailboxChannel

**Use when** each system should have a private inbox — messages addressed to one recipient are invisible to others.

```python
from sssn.channels.mailbox import MailboxChannel

inbox = MailboxChannel(id="messages", name="Messages")
await inbox.start()

# Send a targeted message
import time, uuid
from sssn.core.channel import ChannelMessage, GenericContent

msg = ChannelMessage(
    id=str(uuid.uuid4()),
    timestamp=time.time(),
    sender_id="sys-a",
    content=GenericContent(data="Hello, sys-b!"),
    recipient_id="sys-b",     # ← targeting
)
await inbox.write("sys-a", msg, direct=True)

# sys-b only sees messages addressed to it (or broadcast messages with recipient_id=None)
msgs = await inbox.read("sys-b", limit=10)
assert all(m.recipient_id in (None, "sys-b") for m in msgs)
```

**Filtering:** `read(reader_id)` returns messages where `recipient_id == reader_id` or `recipient_id is None` (broadcast to all).

---

## PeriodicChannel

**Use when** data must be actively fetched from an external source on a schedule.

`PeriodicChannel` is a **marker class** — it inherits the full `BaseChannel` pull loop without modification. Implement `pull_fn()` and `convert_fn()`:

```python
from sssn.channels.periodic import PeriodicChannel
from sssn.core.channel import ChannelMessage, GenericContent
import httpx, time, uuid

class StockPriceChannel(PeriodicChannel):
    async def pull_fn(self) -> None:
        async with httpx.AsyncClient() as client:
            data = (await client.get("https://api.example/prices")).json()
        await self.write("stock-api", data)

    async def convert_fn(self, sender_id, raw_data) -> ChannelMessage | None:
        return ChannelMessage(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            sender_id=sender_id,
            content=GenericContent(data=raw_data),
        )

channel = StockPriceChannel(
    id="stocks",
    name="Stock Prices",
    period=5.0,          # Poll every 5 seconds
)
```

The loop runs: `on_pull()` → `on_process()` → `sleep(period)`. `on_maintain()` fires every `maintenance_interval_seconds`.

---

## DiscoveryChannel

**Use when** systems need to find each other by capability at runtime.

```python
from sssn.channels.discovery import DiscoveryChannel

registry = DiscoveryChannel(
    id="registry",
    name="Service Registry",
    registration_ttl=3600.0,   # Registrations expire after 1 hour
)
await registry.start()

# Register a channel
await registry.register_channel(my_channel.info)

# Register a system
await registry.register_system(my_system._service_descriptor.model_dump())

# Look up
channels = await registry.find_channels(visibility="public")
systems = await registry.find_systems(capability="process_image")

# Point lookup
info = await registry.get_channel("my-channel-id")
```

Registrations carry an `expires_at` timestamp. `on_maintain()` automatically purges expired entries. Refresh registrations with another `register_channel()` call before they expire.

---

## Choosing a channel type

| Need | Use |
|------|-----|
| Data pushed by producers, all consumers see all | `BroadcastChannel` |
| Tasks distributed one-at-a-time to workers | `WorkQueueChannel` |
| Per-system inboxes with recipient targeting | `MailboxChannel` |
| Active polling of an external API or sensor | `PeriodicChannel` |
| Service registry, capability lookup | `DiscoveryChannel` |
| Custom logic with inline write, no loop | `PassthroughChannel` |
