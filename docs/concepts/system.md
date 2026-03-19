# System

A system is an **autonomous agent** — it owns channels, wires itself to the wider network, and runs a tick loop. Systems compose: a system can contain subsystems, forming a holonic hierarchy.

---

## Lifecycle overview

```
          ┌──────────┐
 object   │   INIT   │   __init__() creates ChannelClient
 created  └────┬─────┘
               │ setup()
          ┌────▼─────┐
          │  wired   │   channels created, subsystems added
          └────┬─────┘
               │ launch() or publish()
          ┌────▼──────┐
          │  RUNNING  │   step() called tick_rate times/sec
          └────┬──────┘
               │ stop()
          ┌────▼──────┐
          │  STOPPED  │
          └───────────┘
```

---

## Implementing a system

Subclass `BaseSystem` and override `setup()` and `step()`:

```python
from sssn.core.system import BaseSystem
from sssn.channels.broadcast import BroadcastChannel

class TemperatureSensor(BaseSystem):
    async def setup(self):
        # Create channels this system owns
        self.readings = BroadcastChannel(
            id="temperature-readings",
            name="Temperature Readings",
            description="Live sensor data",
        )
        self.add_channel(self.readings)

    async def step(self):
        temp = await self._read_hardware_sensor()
        await self.write_channel("temperature-readings", data={"celsius": temp})

    async def _read_hardware_sensor(self) -> float:
        # ... hardware integration
        return 22.4
```

### `setup()`

Called **once** before the run loop starts, by `launch()` or `publish()`. This is where you:

- Create channels (`BroadcastChannel`, `WorkQueueChannel`, etc.)
- Register channels with `add_channel()`
- Add subsystems with `add_subsystem()`

`setup()` is **idempotent** — calling `launch()` or `publish()` multiple times only runs `setup()` once.

### `step()`

Called once per tick. The default implementation is a no-op — umbrella systems that only coordinate subsystems do not need to override it.

Unhandled exceptions in `step()` are caught and passed to `on_step_error()`, which logs the error and continues. The loop never crashes on a single step failure.

```python
async def on_step_error(self, error: Exception) -> None:
    logger.error("[%s] step() failed: %s", self.id, error)
    # Override to add circuit-breaking, alerting, etc.
```

---

## Run loop

```python
async def run(self, tick_rate: float = 1.0) -> None:
    ...
```

`tick_rate` is in **ticks per second**. The loop compensates for the time consumed by `step()` so long-running steps do not accumulate drift:

```
actual sleep = (1 / tick_rate) - time_step_took
minimum sleep = 0  (loop always yields to the event loop)
```

| tick_rate | step interval |
|-----------|--------------|
| `1.0` | ~1 second |
| `10.0` | ~100 ms |
| `0.1` | ~10 seconds |

---

## Channel convenience methods

`BaseSystem` wraps `ChannelClient` with named helpers:

```python
# Read
msgs = await self.read_channel("channel-id", limit=20)

# Write
await self.write_channel("channel-id", data={"key": "value"})

# Exclusive read (claim)
msgs = await self.claim_channel("channel-id", limit=5)

# Acknowledge
await self.acknowledge_channel("channel-id", [msg.id for msg in msgs])

# Nack (release)
await self.nack_channel("channel-id", [msg.id])

# Subscribe
await self.subscribe_channel("channel-id", self._on_message)
```

---

## Topology: `add_channel` and `add_subsystem`

### `add_channel(channel)`

Registers a channel with this system and connects it to `self.client`:

```python
self.add_channel(self.readings)
# → self.client.connect("temperature-readings", self.readings)
```

### `add_subsystem(system, channels=[])`

Registers a subsystem and **explicitly wires** channel access:

```python
class Pipeline(BaseSystem):
    async def setup(self):
        self.queue = WorkQueueChannel(id="tasks", name="Tasks")
        self.add_channel(self.queue)

        worker = Worker(id="worker-1", name="Worker 1")
        self.add_subsystem(worker, channels=["tasks"])
        # Worker can now read/write "tasks" directly
```

!!! warning "No auto-wiring"
    `add_subsystem(system)` without `channels` gives the subsystem **no channel access**. Every dependency must be declared. This enforces least-privilege: subsystems only see what they are explicitly given.

---

## Launch vs publish

### `launch()` — in-process

```python
await system.launch()
```

Runs everything in the same Python process. Channels use in-memory stores. No network ports opened. Best for:

- Local development and testing
- Single-machine deployments
- Multi-agent simulations

### `publish(host, port)` — HTTP

```python
await system.publish(host="0.0.0.0", port=8000)
```

Same as `launch()` plus:

1. Every `PUBLIC` channel gets an `HttpTransport` attached.
2. A `ChannelServer` (FastAPI + uvicorn) is started.
3. If a `DiscoveryChannel` is present, all public channels are auto-registered.

Channels marked `Visibility.PRIVATE` are **never exposed** over HTTP, regardless of `publish()`.

```python
from sssn.core.channel import Visibility
from sssn.channels.broadcast import BroadcastChannel

class MyService(BaseSystem):
    async def setup(self):
        # This channel is reachable over HTTP
        self.public_feed = BroadcastChannel(
            id="feed",
            name="Public Feed",
            visibility=Visibility.PUBLIC,
        )
        self.add_channel(self.public_feed)

        # This channel is internal only — never exposed
        self.internal_log = BroadcastChannel(
            id="internal-log",
            name="Internal Log",
            visibility=Visibility.PRIVATE,  # default
        )
        self.add_channel(self.internal_log)

await MyService(id="svc", name="Service").publish(port=8080)
```

---

## The `@system` and `@expose` decorators

For lightweight agents that don't need the full `BaseSystem` lifecycle, use the class decorators:

```python
import sssn

@sssn.system(id="image-processor", name="Image Processor")
class ImageProcessor:
    @sssn.expose(description="Process and tag an image")
    async def process(self, image_url: str) -> dict:
        ...
        return {"tags": ["cat", "indoor"]}
```

The decorator injects `self.client` and builds a `ServiceDescriptor` from all `@expose`d methods. Use `self.client.read()` / `self.client.write()` as normal.

---

## State machine

| State | Meaning |
|-------|---------|
| `INIT` | Created, `setup()` not yet called |
| `RUNNING` | Run loop active, `step()` firing |
| `PAUSED` | Marked paused (loop still runs; true suspension not yet implemented) |
| `STOPPED` | Run loop exited via `stop()` |
| `ERROR` | Reserved for future use |

Access via `system.state` (a `SystemState` enum).
