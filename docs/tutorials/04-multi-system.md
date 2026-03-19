# Tutorial 4 · Multi-System

In this tutorial you will build a pipeline with three systems — a producer, a processor, and a monitor — wired together with explicit channel dependencies.

**What you'll learn:**

- `BaseSystem` subclassing with `setup()` and `step()`
- Explicit subsystem wiring with `add_subsystem(system, channels=[...])`
- The difference between `launch()` (in-process) and `publish()` (HTTP)
- The holonic pattern: systems that own other systems

---

## The topology

```
  ┌────────────────────────────────────┐
  │           Pipeline (umbrella)      │
  │                                    │
  │  ┌─────────┐    raw    ┌─────────┐ │
  │  │ Ingester│──────────►│ Refiner │ │
  │  └─────────┘           └────┬────┘ │
  │                             │      │
  │                          refined   │
  │                             │      │
  │                        ┌────▼────┐ │
  │                        │ Monitor │ │
  │                        └─────────┘ │
  └────────────────────────────────────┘
```

---

## Step 1 — Define the leaf systems

```python
import asyncio
from sssn.core.system import BaseSystem
from sssn.channels.work_queue import WorkQueueChannel
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.channel import ChannelMessage, GenericContent
import time, uuid

class Ingester(BaseSystem):
    """Produces raw records every tick."""

    async def setup(self):
        self.raw = WorkQueueChannel(
            id="raw-records",
            name="Raw Records",
            claim_timeout=30.0,
        )
        self.add_channel(self.raw)

    async def step(self):
        # Simulate receiving data from an external source
        record = {"sensor": "temp-01", "value": 22.4, "ts": time.time()}
        await self.write_channel("raw-records", data=record)


class Refiner(BaseSystem):
    """Claims raw records, enriches them, publishes to refined channel."""

    async def setup(self):
        # Refiner owns the refined channel
        self.refined = BroadcastChannel(
            id="refined-records",
            name="Refined Records",
        )
        self.add_channel(self.refined)
        # raw-records is wired in by the umbrella via add_subsystem

    async def step(self):
        msgs = await self.claim_channel("raw-records", limit=5)
        for msg in msgs:
            data = msg.content.data
            enriched = {**data, "unit": "celsius", "system_id": self.id}
            await self.write_channel("refined-records", data=enriched)
            await self.acknowledge_channel("raw-records", [msg.id])


class Monitor(BaseSystem):
    """Observes refined records and logs anomalies."""

    async def step(self):
        msgs = await self.read_channel("refined-records", limit=20)
        for msg in msgs:
            temp = msg.content.data.get("value", 0)
            if temp > 30:
                print(f"[ALERT] High temperature: {temp}°C")
```

---

## Step 2 — Compose with an umbrella system

```python
class Pipeline(BaseSystem):
    """Umbrella that wires Ingester → Refiner → Monitor."""

    async def setup(self):
        ingester = Ingester(id="ingester", name="Ingester")
        refiner  = Refiner(id="refiner",  name="Refiner")
        monitor  = Monitor(id="monitor",  name="Monitor")

        # Run setup() on each so they create their channels
        await ingester.setup()
        await refiner.setup()
        await monitor.setup()

        # Wire: Refiner reads from Ingester's raw channel
        self.add_subsystem(ingester)
        self.add_subsystem(refiner, channels=["raw-records"])
        self.add_subsystem(monitor, channels=["refined-records"])

        # Register channels so the pipeline's own client can see them
        self.add_channel(ingester.raw)
        self.add_channel(refiner.refined)
```

!!! warning "Explicit wiring required"
    `add_subsystem(refiner)` without `channels=[...]` gives `refiner` **no** channel access. Every dependency must be declared. This is intentional — it makes the topology visible and auditable.

---

## Step 3 — Launch

```python
async def main():
    pipeline = Pipeline(id="pipeline", name="Temperature Pipeline")
    await pipeline.launch()

asyncio.run(main())
```

`launch()` does the following, in order:

1. Calls `setup()` on the pipeline (which calls setup on each subsystem).
2. Starts every channel's background loop (or passthrough `start()`).
3. Gathers `run()` on all subsystems and the pipeline itself with `asyncio.gather`.

The whole thing is a single Python process with a shared event loop.

---

## Step 4 — Expose over HTTP

To make the refined feed accessible to external consumers, mark the channel as `PUBLIC` and call `publish()`:

```python
from sssn.core.channel import Visibility
from sssn.channels.broadcast import BroadcastChannel

class Refiner(BaseSystem):
    async def setup(self):
        self.refined = BroadcastChannel(
            id="refined-records",
            name="Refined Records",
            visibility=Visibility.PUBLIC,   # ← expose over HTTP
        )
        self.add_channel(self.refined)
        ...

async def main():
    pipeline = Pipeline(id="pipeline", name="Temperature Pipeline")
    await pipeline.publish(host="0.0.0.0", port=8000)
    # External clients can now GET http://localhost:8000/channels/refined-records
```

`PRIVATE` channels (the default) are never exposed regardless of `publish()`.

---

## Step 5 — The tick rate

Each system runs its `step()` at its own tick rate:

```python
class Ingester(BaseSystem):
    async def run(self, tick_rate=5.0):  # 5 ticks/second
        await super().run(tick_rate=5.0)

class Refiner(BaseSystem):
    async def run(self, tick_rate=10.0):  # 10 ticks/second (faster drain)
        await super().run(tick_rate=10.0)
```

Override `run()` in the umbrella to pass different tick rates to each subsystem:

```python
class Pipeline(BaseSystem):
    async def launch(self):
        await self.setup()
        for ch in self._channels:
            await ch.start()
        await asyncio.gather(
            self._subsystems[0].run(tick_rate=5.0),   # Ingester
            self._subsystems[1].run(tick_rate=10.0),  # Refiner
            self._subsystems[2].run(tick_rate=2.0),   # Monitor
        )
```

---

## What's next?

Continue to [Tutorial 5 → Securing Channels](05-securing-channels.md) to add access control to this pipeline.
