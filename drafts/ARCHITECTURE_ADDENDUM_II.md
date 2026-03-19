# SSSN Architecture — Addendum II: Channel Hierarchy, Concurrency, and Development Workflow

> Supplements ARCHITECTURE.md v0.3 and Addendum I. Merge into main spec.

---

## A. Channel Class Hierarchy

`BaseChannel` is the fully general base class. But most developers don't need the full generality. SSSN provides a hierarchy of **convenience channels** that pre-wire common patterns with reduced interface surface. Each level hides the complexity you don't need.

```
BaseChannel                         ← Full power. Implement pull_fn + convert_fn.
│
├── PassthroughChannel              ← No ingestion. Systems write, systems read. Simplest.
│   │
│   ├── BroadcastChannel            ← Shared read + subscribe. Push-first. No claim.
│   ├── WorkQueueChannel            ← Exclusive claim only. No shared read.
│   └── MailboxChannel              ← Shared read, filtered by recipient_id. 
│
├── PeriodicSourceChannel           ← Pulls from external source. Implement pull_fn + convert_fn.
│
├── DiscoveryChannel                ← Built-in registry channel.
│
└── (user subclasses)               ← Whatever you need.
```

### A.1 PassthroughChannel (the default)

No external data source. Systems write to it, systems read from it. Both `pull_fn` and `convert_fn` are pre-implemented (no-op and auto-wrap). This is the building block for most inter-system communication.

```python
class PassthroughChannel(BaseChannel):
    """
    The simplest channel. No external source. Systems write, systems read.
    Writes are processed inline (no background loop delay).

    Use this directly for most inter-system communication.
    """
    async def pull_fn(self):
        pass  # No external source

    async def convert_fn(self, sender_id: str, raw_data: Any) -> Optional[ChannelMessage]:
        # Auto-wrap raw data. If already a ChannelMessage, pass through.
        if isinstance(raw_data, ChannelMessage):
            return raw_data
        content = raw_data if isinstance(raw_data, MessageContent) else GenericContent(data=raw_data)
        return ChannelMessage(
            id=str(uuid.uuid4()), timestamp=time.time(),
            sender_id=sender_id,   # preserve actual sender identity
            content=content,
        )
```

Usage — this is the "5-line channel":

```python
ch = PassthroughChannel(id="commands", name="Design Commands")
await ch.start()
```

### A.2 BroadcastChannel

Pre-configured for broadcast/pub-sub. `claim()` is disabled. All reads are shared. Subscription is the primary interface. No persistence by default (ephemeral — good for real-time alerts, telemetry, notifications).

```python
class BroadcastChannel(PassthroughChannel):
    """
    Push-first channel. All readers see all messages. Subscription is primary.
    read(exclusive=True) raises. No persistence by default (in-memory only).

    Use for: alerts, telemetry, notifications, live status updates.
    """
    async def read(self, reader_id: str, limit: int = 10, exclusive: bool = False, **kw):
        if exclusive:
            raise TypeError("BroadcastChannel does not support exclusive reads. Use read() or subscribe().")
        return await super().read(reader_id, limit, exclusive=False, **kw)
```

Usage:

```python
alerts = BroadcastChannel(id="safety-alerts", name="Safety Alerts")
await alerts.subscribe(system_id="robot-1", callback=handle_alert)
# Every write triggers all subscriber callbacks immediately.
```

### A.3 WorkQueueChannel

Pre-configured for exclusive consumption. `read()` is disabled. Only `claim()` works. Persistence enabled by default (you don't want to lose jobs). Automatically manages unclaimed/failed items.

```python
class WorkQueueChannel(PassthroughChannel):
    """
    Task queue. Each message consumed by exactly one worker via read(exclusive=True).
    read(exclusive=False) raises. Persistence enabled by default.

    Use for: job assignment, task distribution, load balancing.
    """
    claim_timeout: float = 300.0  # 5 min default

    async def read(self, reader_id: str, limit: int = 10, exclusive: bool = False, **kw):
        if not exclusive:
            raise TypeError("WorkQueueChannel only supports exclusive reads. Use read(exclusive=True).")
        return await super().read(reader_id, limit, exclusive=True, **kw)

    async def nack(self, reader_id: str, message_ids: List[str]):
        """Release claims immediately — jobs return to the pool without waiting for claim_timeout."""
        self._store.nack(reader_id, message_ids)

    async def on_maintain(self):
        """Reclaim messages that were claimed but not acknowledged within timeout."""
        await super().on_maintain()
        self._store.reclaim_expired(timeout=self.claim_timeout)
```

Usage:

```python
tasks = WorkQueueChannel(
    id="eval-commands", name="Eval Commands",
    db_client=SqliteDBClient("./data/eval.db"),  # persist jobs
    claim_timeout=600,  # 10 min to complete before reclaim
)
# Workers — exclusive=True required:
jobs = await tasks.read(reader_id="verifier-1", limit=1, exclusive=True)
# On completion:
await tasks.acknowledge(reader_id="verifier-1", message_ids=[jobs[0].id])
# On failure (can't process this job):
await tasks.nack(reader_id="verifier-1", message_ids=[jobs[0].id])
```

### A.4 MailboxChannel

Shared mode with built-in filtering by `recipient_id`. The `read()` method automatically filters to only return messages addressed to the caller.

```python
class MailboxChannel(PassthroughChannel):
    """
    Targeted messages. read() auto-filters by recipient_id matching reader_id.
    Writers must set recipient_id on messages.
    
    Use for: direct commands, targeted notifications, point-to-point messaging.
    """
    async def read(self, reader_id: str, limit: int = 10, **kwargs) -> List[ChannelMessage]:
        all_msgs = await super().read(reader_id=reader_id, limit=limit * 5, **kwargs)
        return [m for m in all_msgs if m.recipient_id == reader_id or m.recipient_id is None][:limit]
```

Usage:

```python
mailbox = MailboxChannel(id="commands", name="Direct Commands")
# Master sends to a specific designer:
await mailbox.write_direct(ChannelMessage(
    ..., recipient_id="designer-3", content=DesignCommand(...)
))
# designer-3 only sees messages for itself:
msgs = await mailbox.read(reader_id="designer-3", limit=10)
```

### A.5 PeriodicSourceChannel

For channels that actively pull from external sources. The developer implements `pull_fn` and `convert_fn`. The lifecycle handles scheduling, error recovery, and persistence.

```python
class PeriodicSourceChannel(BaseChannel):
    """
    Channel that periodically ingests from an external source (API, DB, file system).
    Implement pull_fn() and convert_fn().
    
    Use for: news feeds, paper monitors, sensor data, API polling.
    """
    # pull_fn and convert_fn are still abstract — developer must implement.
    pass
```

### A.6 Choosing the Right Channel

```
Do you pull from an external source?
├── Yes → PeriodicSourceChannel (implement pull_fn + convert_fn)
└── No → Systems write to it
         │
         What consumption pattern?
         ├── Everyone sees everything → BroadcastChannel
         ├── One worker per message → WorkQueueChannel
         ├── Targeted to specific systems → MailboxChannel
         ├── Multiple patterns / general → PassthroughChannel
         └── Need full control → BaseChannel
```


---

## B. Concurrency Design and Extension Points

### B.1 Current Concurrency Model

The current design uses `asyncio` single-threaded concurrency with these mechanisms:

| Component | Mechanism | Bounded by |
|-----------|-----------|-----------|
| `convert_fn` workers | `asyncio.gather` + `asyncio.Semaphore` | `max_workers` |
| Background loop | `asyncio.create_task` | One task per channel |
| Subscriber notifications | `asyncio.gather` on callbacks | Number of subscribers |
| Multiple channels | Multiple `create_task` in one event loop | CPU (single core) |

This is sufficient for most agentic networks (hundreds of messages/sec, dozens of systems). The bottleneck is usually the LLM API call latency, not the channel throughput.

### B.2 Extension Points for High Concurrency

When throughput needs to scale beyond single-process asyncio, the architecture has clear extension points — each is a component you swap, not a redesign:

**Extension 1: MessageStore backend** — The default `MessageStore` is an in-memory list. For high-throughput channels where the store becomes a bottleneck, swap to a concurrent-safe implementation:

```python
class RedisMessageStore(MessageStore):
    """
    MessageStore backed by Redis Streams.
    read() uses XREAD with consumer groups.
    claim() uses XCLAIM.
    Scales to millions of messages/sec across processes.
    """
    ...

class KafkaMessageStore(MessageStore):
    """
    MessageStore backed by Kafka topics.
    Each consumption mode maps to a Kafka consumer group config.
    """
    ...
```

The channel interface stays identical. Systems still call `read()`, `claim()`, `subscribe()`. The store is internal to the channel.

**Extension 2: Transport for multi-process** — The `HttpTransport` already enables multi-process by nature (HTTP is process-agnostic). For higher throughput:

```python
class GrpcTransport(ChannelTransport):
    """Binary protocol, streaming, multiplexed connections."""
    ...

class NatsTransport(ChannelTransport):
    """NATS-backed transport for high-throughput pub/sub."""
    ...
```

**Extension 3: Worker pool for convert_fn** — The current `asyncio.Semaphore(max_workers)` bounds concurrent `convert_fn` calls within one event loop. For CPU-heavy conversions:

```python
class ProcessPoolChannel(BaseChannel):
    """
    Runs convert_fn in a ProcessPoolExecutor for CPU-bound work.
    Useful when conversion involves heavy parsing, ML inference, etc.
    """
    async def on_process(self):
        items = self._pop_raw_buffer()
        loop = asyncio.get_event_loop()
        with ProcessPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [loop.run_in_executor(pool, self._sync_convert, v) for v in items.values()]
            results = await asyncio.gather(*futures, return_exceptions=True)
            for result in results:
                if isinstance(result, ChannelMessage):
                    await self.on_message(result)
```

**Extension 4: Sharded channels** — For extreme throughput, a single channel can be partitioned:

```python
class ShardedChannel:
    """
    Distributes messages across N BaseChannel shards by hash(sender_id).
    read() merges results from all shards. claim() round-robins.
    """
    def __init__(self, base_id: str, n_shards: int, channel_factory: Callable):
        self.shards = [channel_factory(id=f"{base_id}-shard-{i}") for i in range(n_shards)]
    
    async def write(self, sender_id: str, data: Any) -> str:
        shard = self.shards[hash(sender_id) % len(self.shards)]
        return await shard.write(sender_id, data)
```

### B.3 Concurrency Summary

The design principle: **the default is simple (asyncio, in-memory), but every bottleneck component is swappable**. The extension path:

```
Throughput need          What you swap              Interface change
─────────────────────    ──────────────────────     ────────────────
~100 msg/s (default)     Nothing                    None
~10K msg/s               Redis/Kafka MessageStore   None
~100K msg/s              + GrpcTransport            None
CPU-bound convert_fn     ProcessPoolChannel         Override on_process
Millions msg/s           ShardedChannel wrapper      Thin wrapper
```


---

## C. Development Workflow: How to Build a System of Systems

Nobody starts by writing channels in isolation. Here is the actual workflow, inspired by how real distributed systems (and Genesys specifically) get built.

### C.1 The Five Phases

```
Phase 1: Think in Flows          "What information moves where?"
Phase 2: Prototype Locally       "Get it working in one process"
Phase 3: Harden                  "Add persistence, types, security, error handling"
Phase 4: Distribute              "Split across processes/machines"
Phase 5: Publish                 "Expose PUBLIC channels to the internet"
```

### Phase 1: Think in Flows (Whiteboard)

**Do not start with code.** Start with a diagram. Ask these questions:

1. **Who are the participants?** List every agent, service, human, and device.
2. **What information flows between them?** For each pair of participants that need to communicate, name the information: "design commands", "evaluation results", "telemetry", etc.
3. **What is the flow direction?** Who produces, who consumes?
4. **What are the consumption semantics?** Does everyone need to see every message (broadcast)? Or should each message go to exactly one consumer (task queue)?
5. **What is the criticality?** Which flows need persistence? Which need real-time delivery? Which can tolerate loss?

This produces a topology diagram:

```
                    ┌──────────────────────────────────────────────┐
Example: Genesys    │                                              │
                    │  DR(shared)   DC(exclusive)   DD(shared)     │
                    │  ER(shared)   EC(exclusive)   ED(shared)     │
                    │  ET(shared, persistent, Firebase-backed)     │
                    │                                              │
   Designers ──────▶│◀──────── Master ────────▶│◀──── Verifiers   │
                    │                          │                   │
                    └──────────────────────────────────────────────┘
                           KE (exposed service, no channel)
                           SC (exposed service, no channel)
```

**The output of Phase 1 is a table of channels and a table of systems.** Not code.

### Phase 2: Prototype Locally (One Process, In-Memory)

Translate the diagram directly to code. Use the simplest channel types. No persistence, no security, no HTTP. Everything in one `async def main()`.

```python
import asyncio
import sssn

async def main():
    # --- Channels (from the diagram) ---
    dr = sssn.PassthroughChannel(id="design-requests", name="Design Requests")
    dc = sssn.WorkQueueChannel(id="design-commands", name="Design Commands")
    dd = sssn.PassthroughChannel(id="design-delivery", name="Design Delivery")
    
    # --- Systems (minimal, just to test the flow) ---
    class Master(sssn.BaseSystem):
        async def step(self):
            reqs = await self.read_channel("design-requests", limit=5)
            for req in reqs:
                await self.write_channel("design-commands", data={"parent": req.content.data})
            
            deliveries = await self.read_channel("design-delivery", limit=5)
            for d in deliveries:
                print(f"Got delivery: {d.content.data}")
    
    class Designer(sssn.BaseSystem):
        async def step(self):
            jobs = await self.claim_channel("design-commands", limit=1)  # read(exclusive=True)
            if not jobs:
                return
            result = f"Design based on {jobs[0].content.data}"
            await self.write_channel("design-delivery", data={"result": result})
            await self.acknowledge_channel("design-commands", [jobs[0].id])
    
    # --- Wire and launch ---
    master = Master(id="master", name="Master")
    designer = Designer(id="designer-1", name="Designer 1")
    
    for sys in [master, designer]:
        sys.client.connect("design-requests", dr)
        sys.client.connect("design-commands", dc)
        sys.client.connect("design-delivery", dd)
    
    # Seed a request
    await dr.start(); await dc.start(); await dd.start()
    await master.client.write("design-requests", data={"seed": "GPT"})
    
    await asyncio.gather(
        master.run(tick_rate=1.0),
        designer.run(tick_rate=0.5),
    )

asyncio.run(main())
```

**The output of Phase 2 is a working prototype where you can see messages flow.** The logic is correct but nothing persists and there is no error handling.

### Phase 3: Harden

Add the production concerns, one at a time:

**Step 3a: Typed content** — Replace `GenericContent` with typed models.

```python
class DesignCommand(sssn.MessageContent):
    parent_ids: List[str]
    gp_operation: str
    target_units: Optional[List[str]] = None

# Now write() validates the schema:
await dc.write(sender_id="master", data=DesignCommand(parent_ids=["gpt"], gp_operation="mutate"))
```

**Step 3b: Persistence** — Add DB clients to channels that need durability.

```python
dc = sssn.WorkQueueChannel(
    id="design-commands", name="Design Commands",
    db_client=sssn.SqliteDBClient("./data/commands.db"),
    retention_max_count=1000,
)
```

**Step 3c: Security** — Add access control.

```python
sec = sssn.JWTChannelSecurity(secret=os.environ["SSSN_SECRET"])
dc = sssn.WorkQueueChannel(..., security=sec)
```

**Step 3d: Error handling** — Override `on_error` on channels, add retry logic to systems.

```python
class ResilientDesigner(sssn.BaseSystem):
    max_retries: int = 3
    
    async def step(self):
        jobs = await self.claim_channel("design-commands", limit=1)
        if not jobs:
            return
        for attempt in range(self.max_retries):
            try:
                result = await self.design(jobs[0])
                await self.write_channel("design-delivery", data=result)
                return
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed after {self.max_retries} attempts: {e}")
```

### Phase 4: Distribute

When you need to split across processes or machines:

**Step 4a: Switch transport** — Attach HTTP transport. One-line change per channel.

```python
server = sssn.ChannelServer(host="0.0.0.0", port=8000)
for ch in [dr, dc, dd, er, ec, ed, et]:
    ch.attach_transport(sssn.HttpTransport(server=server))
```

**Step 4b: Remote connection** — Systems in other processes connect via URL.

```python
# In the designer process (separate machine):
designer = Designer(id="designer-1", name="Designer 1")
designer.client.connect_remote("design-commands", "http://coordinator:8000/channels/design-commands", token=my_token)
designer.client.connect_remote("design-delivery", "http://coordinator:8000/channels/design-delivery", token=my_token)
await designer.run()
```

**Step 4c: Scale workers** — Launch N designer processes. Each claims from the same WorkQueueChannel. Exclusivity is guaranteed by the channel.

```bash
# Launch 4 designer workers
for i in $(seq 1 4); do
    python designer.py --id "designer-$i" &
done
```

### C.2 The Phase Map

| Phase | Effort | What you add | Risk if skipped |
|-------|--------|-------------|-----------------|
| **1. Think in Flows** | 1 hour | Diagram, channel/system tables (with visibility column) | You'll redesign everything |
| **2. Prototype** | 1 day | Working in-memory flow | Can't verify the architecture works |
| **3. Harden** | 1-3 days | Types, persistence, security, error handling | Data loss, schema bugs, unauthorized access |
| **4. Distribute** | 1 day | HTTP transport, remote connections | N/A — only if you need distribution |
| **5. Publish** | Hours | `publish()`, reverse proxy, public channel security | Unintended exposure if done without security |

### C.3 Common Development Questions

**"Should this be a channel or a direct function call?"**

Use a channel when: the communication should be *observable* (you want to inspect the flow), *persistent* (messages should survive restarts), *decoupled* (the producer doesn't need to know the consumer exists), or *access-controlled* (not everyone should see it). Use a direct call for everything else.

**"How many channels do I need?"**

One per distinct information flow. If the same data goes to the same consumers for the same purpose, it is one channel. If the consumption pattern differs (broadcast vs. exclusive), or the data type differs, or the access control differs, they are separate channels. For Genesys: 6 communication channels + 1 state channel. For a simple two-agent pipeline: 2 channels (input, output).

**"Should I use BaseSystem or a decorator?"**

If your system has a background loop (it needs to periodically check for new messages, do maintenance, etc.), use `BaseSystem`. If your system is purely reactive (it only acts when called), use `@sssn.system`. If your system is a tool with no network presence beyond reading/writing channels, use `sssn.register()`.

**"When do I need the discovery channel?"**

When systems join and leave dynamically, or when you don't know the full topology at startup. For static networks where everything is launched together (most cases), direct wiring in the umbrella launcher is simpler and more explicit.


---

## D. Updated File Structure

```
sssn/
├── core/
│   ├── __init__.py
│   ├── system.py           # BaseSystem, SystemState, @sssn.system, @sssn.expose, sssn.register()
│   ├── channel.py          # BaseChannel, ChannelInfo, ChannelMessage, MessageContent, MessageStore
│   ├── client.py           # ChannelClient
│   ├── db.py               # ChannelDBClient (abstract) + SqliteDBClient, FileDBClient
│   ├── transport.py        # ChannelTransport + InProcessTransport, HttpTransport, IpcTransport
│   └── security.py         # ChannelSecurity + JWTChannelSecurity, OpenSecurity, ACLSecurity
├── channels/
│   ├── __init__.py
│   ├── passthrough.py      # PassthroughChannel
│   ├── broadcast.py        # BroadcastChannel
│   ├── work_queue.py       # WorkQueueChannel (with claim timeout + reclaim)
│   ├── mailbox.py          # MailboxChannel
│   ├── periodic.py         # PeriodicSourceChannel
│   └── discovery.py        # DiscoveryChannel
├── infra/
│   ├── __init__.py
│   ├── server.py           # ChannelServer (shared HTTP host)
│   └── helpers.py          # request_via_channel, etc.
├── utils/
│   ├── __init__.py
│   └── general.py
├── __init__.py              # Public API surface
└── py.typed
```
