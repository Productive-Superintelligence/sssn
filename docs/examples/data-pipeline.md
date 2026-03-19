# Example · Data Pipeline

A complete ETL pipeline: a `PeriodicChannel` polls an external API, feeds a `WorkQueueChannel`, and multiple worker systems drain the queue concurrently.

```
PeriodicChannel (pull every 10s)
    └── raw-records WorkQueueChannel
            ├── Worker 1 (claim → transform → push)
            ├── Worker 2 (claim → transform → push)
            └── Worker 3 (claim → transform → push)
                    └── processed-records BroadcastChannel
                                └── Dashboard (subscribe)
```

---

## Full program

```python
import asyncio
import time
import uuid
from sssn.channels.periodic import PeriodicChannel
from sssn.channels.work_queue import WorkQueueChannel
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.channel import ChannelMessage, GenericContent
from sssn.core.system import BaseSystem


# ---------------------------------------------------------------------------
# Data source: periodic poll → raw work queue
# ---------------------------------------------------------------------------

class DataIngestor(PeriodicChannel):
    """Polls a (simulated) API every 5 seconds, queues raw records."""

    def __init__(self, raw_queue: WorkQueueChannel, **kwargs):
        super().__init__(**kwargs)
        self._raw_queue = raw_queue

    async def pull_fn(self) -> None:
        # Simulate fetching a batch from an API
        batch = [
            {"id": str(uuid.uuid4()), "sensor": "s1", "value": 22.1 + i * 0.3}
            for i in range(5)
        ]
        for record in batch:
            await self._raw_queue.write("ingestor", record)
        print(f"[Ingestor] queued {len(batch)} records")

    async def convert_fn(self, sender_id: str, raw_data) -> ChannelMessage | None:
        # DataIngestor doesn't use its own store — it forwards to raw_queue
        return None


# ---------------------------------------------------------------------------
# Worker system: claims → transforms → publishes
# ---------------------------------------------------------------------------

class TransformWorker(BaseSystem):
    def __init__(
        self,
        raw_queue: WorkQueueChannel,
        output: BroadcastChannel,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._raw_queue = raw_queue
        self._output = output

    async def setup(self):
        # Wire direct references — no channel ownership here
        self.client.connect("raw-records", self._raw_queue)
        self.client.connect("processed", self._output)

    async def step(self):
        msgs = await self.claim_channel("raw-records", limit=3)
        for msg in msgs:
            try:
                transformed = await self._transform(msg.content.data)
                await self.write_channel("processed", data=transformed)
                await self.acknowledge_channel("raw-records", [msg.id])
            except Exception as e:
                print(f"[{self.id}] transform error: {e}")
                await self.nack_channel("raw-records", [msg.id])

    async def _transform(self, raw: dict) -> dict:
        await asyncio.sleep(0.02)  # Simulate CPU work
        return {
            "record_id": raw["id"],
            "sensor": raw["sensor"],
            "celsius": raw["value"],
            "fahrenheit": raw["value"] * 9 / 5 + 32,
            "processed_at": time.time(),
            "worker": self.id,
        }


# ---------------------------------------------------------------------------
# Monitor: subscribes to processed records, logs anomalies
# ---------------------------------------------------------------------------

class Dashboard(BaseSystem):
    def __init__(self, processed: BroadcastChannel, **kwargs):
        super().__init__(**kwargs)
        self._processed = processed
        self._received = 0

    async def setup(self):
        self.client.connect("processed", self._processed)
        await self.subscribe_channel("processed", self._on_record)

    async def _on_record(self, msg: ChannelMessage):
        self._received += 1
        data = msg.content.data
        temp = data["celsius"]
        status = "🔴 HIGH" if temp > 23 else "✅ OK "
        print(
            f"[Dashboard] {status} | {data['sensor']} | "
            f"{temp:.1f}°C | worker={data['worker']}"
        )

    async def step(self):
        pass  # All work done in _on_record callback


# ---------------------------------------------------------------------------
# Umbrella: wires everything together and runs
# ---------------------------------------------------------------------------

async def main():
    # Shared channels
    raw_queue  = WorkQueueChannel(id="raw-records",  name="Raw Records",  claim_timeout=30.0)
    processed  = BroadcastChannel(id="processed",    name="Processed Records")

    # Start channels
    await raw_queue.start()
    await processed.start()

    # Ingestor channel (runs its own loop)
    ingestor = DataIngestor(
        raw_queue=raw_queue,
        id="ingestor", name="Data Ingestor",
        period=5.0,
    )
    await ingestor.start()

    # Workers
    workers = [
        TransformWorker(
            raw_queue=raw_queue,
            output=processed,
            id=f"worker-{i}",
            name=f"Worker {i}",
        )
        for i in range(1, 4)
    ]

    # Dashboard
    dashboard = Dashboard(processed=processed, id="dashboard", name="Dashboard")

    # Setup all systems
    for w in workers:
        await w.setup()
    await dashboard.setup()

    # Run for 30 seconds
    async def run_limited(system, tick_rate, duration):
        try:
            await asyncio.wait_for(system.run(tick_rate=tick_rate), timeout=duration)
        except asyncio.TimeoutError:
            system.stop()

    print("Pipeline starting — runs for 30 seconds...")
    await asyncio.gather(
        run_limited(workers[0], tick_rate=5.0, duration=30),
        run_limited(workers[1], tick_rate=5.0, duration=30),
        run_limited(workers[2], tick_rate=5.0, duration=30),
        run_limited(dashboard,  tick_rate=1.0, duration=30),
    )

    print(f"\nDashboard received {dashboard._received} processed records.")


asyncio.run(main())
```

---

## Key design decisions

**Why a `WorkQueueChannel` between ingestion and processing?**
The ingestor may burst (large API batch) while workers have finite throughput. The queue acts as a buffer and automatically balances load across workers.

**Why `direct=False` for ingestion writes?**
Raw records go through the queue's `convert_fn()` for wrapping. Direct writes are appropriate when you've already constructed the `ChannelMessage` (e.g., request-response correlation).

**Why `BroadcastChannel` for output?**
Multiple downstream consumers (dashboard, archiver, alerting) each need to see every processed record independently. Broadcast gives each consumer its own cursor.
