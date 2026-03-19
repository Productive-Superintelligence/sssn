# SSSN Architecture Specification — Addendum

> Supplements ARCHITECTURE.md v0.3. These sections should be merged into the main spec.

---

## A. ChannelDBClient vs LLLM LogBackend: Code Sharing Decision

**Decision: Keep separate interfaces. Share implementations where natural.**

The two abstractions serve different access patterns:

| | LogBackend (LLLM) | ChannelDBClient (SSSN) |
|---|---|---|
| **Sync model** | Synchronous | Asynchronous (asyncio) |
| **Data type** | Raw bytes | Typed `ChannelMessage` (Pydantic) |
| **Key model** | String keys, prefix listing | Message IDs, time-range queries |
| **Query patterns** | `get(key)`, `list_keys(prefix)` | `get_range(t0, t1)`, `get_latest(n)` |
| **Primary use** | Append-heavy session logs | Read-heavy message retrieval |

LogBackend is a dumb key-value pipe — it doesn't know what it stores. ChannelDBClient is message-aware — it needs time-indexed queries because channels are inherently chronological. Making ChannelDBClient wrap LogBackend would force awkward key-encoding schemes for time ranges and lose the async model.

However, the *implementations* naturally share underlying libraries:

```python
# Both use aiosqlite, but with different schemas and query patterns.
# LLLM's SQLiteBackend: CREATE TABLE kv (key TEXT PRIMARY KEY, data BLOB)
# SSSN's SqliteDBClient: CREATE TABLE messages (id TEXT PRIMARY KEY, timestamp REAL, sender_id TEXT, content JSON, ...)
#                        CREATE INDEX idx_timestamp ON messages(timestamp)

# Both can use Firebase, Redis, etc. — different schemas, same SDK.
```

**Concrete rule**: SSSN should `import` from LLLM for nothing. If a developer happens to use both frameworks, they can write a bridge. But the codebases stay independent. Within SSSN, the `ChannelDBClient` implementations use the same libraries (aiosqlite, firebase-admin) that LLLM's LogBackend implementations use — that's code *similarity*, not code *sharing*.


---

## B. Channel Lifecycle: The Default Loop

Like PyTorch Lightning's `Trainer` or HuggingFace's `Trainer`, `BaseChannel` has a **default lifecycle with overridable hooks**. The developer can override any hook to customize behavior, but the default lifecycle works out of the box.

### B.1 Lifecycle Diagram

```
channel.start()
    │
    ├── on_start()                      # Hook: one-time setup
    │     └── db_client.initialize()    # If DB is attached
    │     └── transport.start()         # If transport is attached
    │
    ├── ┌─────────── MAIN LOOP ──────────────┐
    │   │                                     │
    │   │  1. on_pull()                       │  ← calls pull_fn(), catches errors
    │   │       └── pull_fn()  [ABSTRACT]     │
    │   │                                     │
    │   │  2. on_process()                    │  ← pops raw buffer, runs convert_fn()
    │   │       └── convert_fn() [ABSTRACT]   │     concurrently on each item
    │   │       └── on_message(msg)           │  ← called per successfully converted msg
    │   │             └── store.append(msg)   │
    │   │             └── db_client.save(msg) │
    │   │             └── store.notify(msg)   │  ← push to subscribers
    │   │                                     │
    │   │  3. on_maintain()                   │  ← periodic housekeeping
    │   │       └── default: evict by policy  │
    │   │                                     │
    │   │  await asyncio.sleep(period)        │
    │   └─────────────────────────────────────┘
    │
    └── channel.stop()
          └── on_stop()                 # Hook: cleanup
                └── transport.stop()
```

### B.2 Hook Definitions

```python
class BaseChannel(abc.ABC):
    """
    Default lifecycle with overridable hooks.
    Override any hook to customize. The defaults are sensible for most cases.
    """
    
    # --- Configuration ---
    retention_max_age: Optional[float] = None         # Seconds. None = keep forever.
    retention_max_count: Optional[int] = None          # Max messages. None = unlimited.
    maintenance_interval_seconds: float = 60.0         # Wall-clock seconds between on_maintain() calls.
    
    # === Overridable lifecycle hooks ===
    
    async def on_start(self):
        """Called once when channel starts. Override for custom setup."""
        if self.db_client:
            await self.db_client.initialize(self.info.model_dump())
        if self.transport:
            await self.transport.start(self)
    
    async def on_pull(self):
        """Called every cycle. Default: calls pull_fn() with error handling."""
        try:
            await self.pull_fn()
        except Exception as e:
            await self.on_error("pull", e)
    
    async def on_process(self):
        """
        Called every cycle after pull. Pops raw buffer, runs convert_fn()
        on each item concurrently, stores successful results.
        Raw buffer entries are (sender_id, data) pairs — sender_id is threaded
        through to convert_fn so the resulting ChannelMessage preserves the
        actual sender identity.
        """
        items = self._pop_raw_buffer()  # Dict[item_id, (sender_id, data)]
        if not items:
            return
        tasks = [self._process_one(k, sid, v) for k, (sid, v) in items.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, ChannelMessage):
                await self.on_message(result)
    
    async def on_message(self, msg: ChannelMessage):
        """
        Called for each successfully converted message.
        Default: append to store, persist to DB, notify subscribers.
        Override to add custom logic (filtering, enrichment, routing).
        """
        self._store.append(msg)
        if self.db_client:
            await self.db_client.save(msg)
        await self._store.notify_subscribers(msg)
    
    async def on_maintain(self):
        """
        Periodic housekeeping. Called on a wall-clock schedule (maintenance_interval_seconds).
        Default: evict messages by retention policy.
        Override to add custom cleanup, compaction, metrics, etc.
        """
        if self.retention_max_age is not None:
            cutoff = time.time() - self.retention_max_age
            self._store.evict(before=cutoff)
        if self.retention_max_count is not None:
            self._store.evict(max_count=self.retention_max_count)
        # Sync evictions to DB if needed
        if self.db_client:
            await self._sync_evictions_to_db()
    
    async def on_error(self, phase: str, error: Exception):
        """
        Called when an error occurs in any phase.
        Default: log and continue. Override for custom error handling.
        """
        logger.error(f"[{self.id}] Error in {phase}: {error}")
    
    async def on_stop(self):
        """Called once when channel stops. Override for custom cleanup."""
        if self.transport:
            await self.transport.stop()
    
    # === The main loop (usually NOT overridden) ===
    
    async def _run_loop(self):
        """
        The background loop. Calls hooks in sequence.
        on_maintain() is triggered by wall-clock time, not cycle count, so
        retention enforcement remains predictable regardless of cycle duration.
        """
        next_maintain_at = time.time() + self.maintenance_interval_seconds
        while self._is_running:
            await self.on_pull()
            await self.on_process()

            if time.time() >= next_maintain_at:
                await self.on_maintain()
                next_maintain_at = time.time() + self.maintenance_interval_seconds

            await asyncio.sleep(self.period)
    
    async def start(self):
        """Start the channel. Calls on_start() then begins the loop."""
        self._is_running = True
        await self.on_start()
        self._loop_task = asyncio.create_task(self._run_loop())
    
    def stop(self):
        """Stop the channel."""
        self._is_running = False
        asyncio.create_task(self.on_stop())
```

### B.3 Who Manages the Datastore?

**The channel manages its own datastore.** The `on_maintain()` hook is the channel's built-in janitor. It runs periodically and enforces retention policy. The channel developer configures retention via `retention_max_age` and `retention_max_count`, or overrides `on_maintain()` for custom logic.

```python
# Simple: set retention policy at construction
news_channel = TechNewsChannel(
    id="tech-news", name="Tech News",
    retention_max_age=7 * 86400,    # Keep 7 days
    retention_max_count=10000,       # Max 10K messages
    maintenance_interval_seconds=30, # Run on_maintain() every 30 seconds
)

# Custom: override on_maintain for complex logic
class SmartChannel(BaseChannel):
    async def on_maintain(self):
        await super().on_maintain()  # default retention
        # Custom: also remove messages flagged as invalid
        flagged = [m.id for m in self._store.messages if m.metadata.get("flagged")]
        if flagged:
            self._store.remove(flagged)
            logger.info(f"Removed {len(flagged)} flagged messages")
```

The `clear()`, `evict()`, and `remove()` methods on BaseChannel are *imperative* host operations for manual control. `on_maintain()` is the *automatic* periodic cleanup. Both are available; the developer chooses when to use which.


---

## C. Occam's Razor: Justifying the Channel Interface

The channel interface has exactly **6 consumption methods** and **3 host operations**. Each exists because it enables a distinct pattern that cannot be reduced to the others.

### C.1 The 6 Consumption Methods

| Method | Why it exists | Removing it breaks... |
|--------|---------------|----------------------|
| `read()` | Unified read: `exclusive=False` for shared (cursor-based), `exclusive=True` for exclusive (task claim). | All consumption — bulletin boards, task queues, mailboxes |
| `write()` | Unified write: `direct=False` routes through ingestion pipeline; `direct=True` bypasses convert_fn. | All production — external data ingestion and system-to-system messages |
| `subscribe()` | Push notification on new messages. Local-only. | Real-time reactions without polling |
| `unsubscribe()` | Remove a push callback. | Cleanup. Without it, subscriptions leak. |
| `acknowledge()` | Mark exclusively-claimed messages as permanently consumed. | Reliable task completion — without it, tasks are re-delivered after claim_timeout. |
| `nack()` | Explicitly release claimed messages back to the pool without consuming them. | Workers cannot immediately reject unsuitable jobs; must wait for claim_timeout. |

**Why `read(exclusive)` not separate `read()` + `claim()`**: The flag unifies the interface without losing semantics. Convenience subclasses (`WorkQueueChannel`, `BroadcastChannel`) raise on invalid flag values, giving the same guardrails as separate methods with a smaller base interface.

**Why `write(direct)` not separate `write()` + `write_direct()`**: Same reasoning. The base class has one method per operation; the flag selects the path. `direct=False` routes raw data through the ingestion pipeline (convert_fn). `direct=True` bypasses convert_fn for pre-formed `ChannelMessage` objects.

**Why `acknowledge()` and `nack()` are symmetric in the base interface**: They are the two outcomes of exclusive consumption — success and failure. `nack()` allows immediate task return without waiting for `claim_timeout` to expire. Both are no-ops for non-exclusive messages.

### C.2 The 3 Host Operations

| Method | Why it exists |
|--------|---------------|
| `clear(filter_fn)` | Remove messages matching a condition. For patterns like "clear my completed commands." |
| `evict(before, max_count)` | Retention enforcement. For automatic and manual aging. |
| `remove(message_ids)` | Remove specific messages. For removing buggy/problematic content. |

**Could these merge?** `evict` is policy-based (by age or count), `remove` is by specific ID, `clear` is by predicate. They address different use cases. One general `delete(filter)` could replace all three, but the distinct names make intent clear and avoid accidental data loss from overly broad filters.

### C.3 One Pattern, One Example

Below is a minimal example for each pattern showing exactly which methods are used. All use the same `PassthroughChannel` — no subclassing needed.

#### Pattern 1: Bulletin Board

```python
# Setup
board = PassthroughChannel(id="announcements", name="Announcements")

# Writer (e.g., admin system) — direct=True: pre-formed message, bypasses convert_fn
await board.write(sender_id="admin", data=ChannelMessage(
    id="ann-1", timestamp=time.time(), sender_id="admin",
    content=GenericContent(data={"text": "System maintenance at 2am"}),
), direct=True)

# Reader (any system) — each reader sees all messages
msgs = await board.read(reader_id="worker-1", limit=10)
msgs = await board.read(reader_id="worker-2", limit=10)  # same messages
```

#### Pattern 2: Task Queue

```python
# Setup — WorkQueueChannel enforces exclusive-only reads
queue = WorkQueueChannel(id="tasks", name="Task Queue")

# Producer — direct=True: pre-formed message
await queue.write(sender_id="coordinator", data=ChannelMessage(
    id="task-1", timestamp=time.time(), sender_id="coordinator",
    content=GenericContent(data={"action": "pick", "shelf": "A3", "item": "widget-42"}),
), direct=True)

# Consumer — exclusive=True: only ONE worker gets each task
tasks = await queue.read(reader_id="robot-1", limit=1, exclusive=True)  # gets task-1
tasks = await queue.read(reader_id="robot-2", limit=1, exclusive=True)  # empty — task-1 already claimed

# On success: acknowledge
await queue.acknowledge(reader_id="robot-1", message_ids=["task-1"])

# On failure (can't process): nack — returns task immediately without waiting for claim_timeout
await queue.nack(reader_id="robot-1", message_ids=["task-1"])
```

#### Pattern 3: Mailbox (Targeted Messages)

```python
# Sender targets a specific system — direct=True: pre-formed message
await channel.write(sender_id="master", data=ChannelMessage(
    id="cmd-1", timestamp=time.time(), sender_id="master",
    content=GenericContent(data={"command": "stop"}),
    recipient_id="robot-3",                      # ← targeting
), direct=True)

# Receiver filters by recipient_id
msgs = await channel.read(reader_id="robot-3", limit=10)
my_msgs = [m for m in msgs if m.recipient_id == "robot-3"]
```

#### Pattern 4: Pub/Sub (Push)

```python
# Subscriber registers callback
async def on_alert(msg: ChannelMessage):
    print(f"ALERT: {msg.content.data}")

await alerts_channel.subscribe(system_id="robot-1", callback=on_alert)

# Publisher writes — callback fires immediately for all subscribers
await alerts_channel.write(sender_id="safety-monitor", data=ChannelMessage(
    id="alert-1", timestamp=time.time(), sender_id="safety-monitor",
    content=GenericContent(data={"type": "obstacle", "zone": "B2"}),
), direct=True)
# on_alert fires for robot-1 automatically
```

#### Pattern 5: Request-Response

```python
# Uses correlation_id + reply_to on standard messages
from sssn.infra.helpers import request_via_channel

response = await request_via_channel(
    request_channel=request_ch,
    response_channel=response_ch,
    sender_id="designer-1",
    data={"query": "search papers on state space models"},
    timeout=30.0,
)
# Internally: writes a message with correlation_id, polls response_ch for match
```

#### Pattern 6: Forum / Threaded Discussion

```python
# Original post — direct=True: pre-formed message with correlation_id
await channel.write(sender_id="proposer", data=ChannelMessage(
    id="thread-1", timestamp=time.time(), sender_id="proposer",
    content=GenericContent(data={"proposal": "Add gated attention..."}),
    correlation_id="thread-1",          # thread root
), direct=True)

# Reply (same correlation_id, linking to the thread)
await channel.write(sender_id="reviewer", data=ChannelMessage(
    id="reply-1", timestamp=time.time(), sender_id="reviewer",
    content=GenericContent(data={"review": "Score: 4/5, but consider..."}),
    correlation_id="thread-1",          # same thread
    reply_to="thread-1",               # what it replies to
), direct=True)

# Read thread: filter by correlation_id
msgs = await channel.read(reader_id="observer", limit=100)
thread = [m for m in msgs if m.correlation_id == "thread-1"]
```


---

## D. System Registration Flow

### D.1 Who Saves Registration Info?

**Registration is local-first.** There is no mandatory global registry. What happens at each level:

| Level | What happens on registration | Where is info saved |
|-------|------------------------------|---------------------|
| `sssn.register()` | Creates a `ChannelClient` with the given ID. Nothing else. | In-memory only. The client object is your handle. |
| `@sssn.system` | Creates a `ChannelClient` + collects `@sssn.expose` metadata into a `ServiceDescriptor`. | In-memory. The decorated class carries its descriptor. |
| `BaseSystem.__init__` | Same as decorator, plus initializes lifecycle state and directories. | In-memory. |

**No implicit writes to any registry or discovery service.** Registration is purely local — it gives you the tools to participate. *Announcing* yourself to the network is a separate, explicit step.

### D.2 Connecting to Channels

After registration, the system connects to channels explicitly:

```python
client = sssn.register(id="my-tool", name="My Tool")

# Option A: Direct reference (same process)
client.connect("news-feed", news_channel_object)

# Option B: Remote URL
client.connect_remote("news-feed", "http://host:8000/channels/news-feed")

# Option C: From config file
client.connect_from_config({"news-feed": "http://host:8000/channels/news-feed"})
```

**Channel-level access check**: When a system first calls `read()` or `write()` on a channel, the channel's `ChannelSecurity` verifies the system's identity and permissions. This is the "handshake" — implicit, on first operation, not a separate step.

For channels with `JWTChannelSecurity`, the client must have been given a token:

```python
token = await security.generate_token(system_id="my-tool", role="read")
client.connect_remote("news-feed", "http://host:8000/channels/news-feed", token=token)
```

For channels with `OpenSecurity` or `ACLSecurity`, the system_id itself is the credential.

### D.3 Announcing to Discovery (Optional)

If a `DiscoveryChannel` is running, systems can announce themselves:

```python
# Publish your presence to the discovery channel
await client.write("discovery", data=my_system.service_descriptor.model_dump())

# Or use a convenience method on BaseSystem
await self.announce(discovery_channel_id="discovery")
```

This is opt-in. For local networks where all systems are launched by the same process, discovery is unnecessary — direct references suffice.

### D.4 The Umbrella Launcher Pattern

For systems launched together, an "umbrella" system (or just a script) creates all channels, connects all systems, and starts everything. The umbrella is the natural place for registration and wiring:

```python
async def main():
    # 1. Create channels
    news = TechNewsChannel(id="news", name="Tech News", period=300)
    tasks = WorkQueueChannel(id="tasks", name="Tasks")  # enforces exclusive reads
    results = PassthroughChannel(id="results", name="Results")
    
    # 2. Create systems (they auto-get ChannelClients)
    fetcher = NewsFetcher(id="fetcher", name="Fetcher")
    processor = Processor(id="processor", name="Processor")
    
    # 3. Wire: connect systems to channels
    fetcher.client.connect("news", news)
    processor.client.connect("tasks", tasks)
    processor.client.connect("results", results)
    
    # 4. Launch everything
    await asyncio.gather(
        news.start(),
        tasks.start(),
        results.start(),
        fetcher.run(tick_rate=60),
        processor.run(tick_rate=1),
    )
```

The umbrella doesn't need to be a BaseSystem — it can be a plain async function. But it *can* be a BaseSystem if you want lifecycle management for the whole ensemble.


---

## E. Minimal Examples: From 5 Lines to a Full Network

### E.1 Simplest Possible: One Channel, Two Systems (5 lines)

```python
import asyncio
import sssn

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

### E.2 Growing: Add Persistence and Security

```python
async def main():
    db = sssn.SqliteDBClient("./data/chat.db")
    sec = sssn.ACLSecurity(read=["alice", "bob"], write=["alice", "bob"])
    
    ch = sssn.PassthroughChannel(
        id="chat", name="Chat",
        db_client=db, security=sec,
        retention_max_age=7 * 86400,  # 7 days
    )
    await ch.start()
    # ... same as before, but now messages persist and only alice/bob can access
```

### E.3 Multi-Channel: A Simple Pipeline

```python
async def main():
    # Channel 1: raw data in
    raw = sssn.PassthroughChannel(id="raw", name="Raw Data")
    # Channel 2: processed data out
    processed = sssn.PassthroughChannel(id="processed", name="Processed")
    
    await raw.start()
    await processed.start()
    
    # Processor system
    class Processor(sssn.BaseSystem):
        async def step(self):
            msgs = await self.read_channel("raw", limit=5)
            for msg in msgs:
                result = do_something(msg.content.data)
                await self.write_channel("processed", data=result)
    
    proc = Processor(id="proc", name="Processor")
    proc.client.connect("raw", raw)
    proc.client.connect("processed", processed)
    
    await proc.run(tick_rate=1.0)
```

### E.4 Full Network: Umbrella Launcher

```python
"""
A complete network with multiple channels, systems, shared server,
persistence, and security. This is the pattern for production systems.
"""
import asyncio
import sssn

async def main():
    # --- Security ---
    sec = sssn.JWTChannelSecurity(secret="my-network-secret")
    
    # --- Channels ---
    news = TechNewsChannel(
        id="news", name="Tech News", period=300,
        db_client=sssn.SqliteDBClient("./data/news.db"),
        security=sec, retention_max_age=30 * 86400,
    )
    tasks = sssn.WorkQueueChannel(
        id="tasks", name="Tasks",
        security=sec,
    )
    results = sssn.PassthroughChannel(
        id="results", name="Results",
        db_client=sssn.SqliteDBClient("./data/results.db"),
        security=sec,
    )
    discovery = sssn.DiscoveryChannel(
        id="discovery", name="Network Discovery", security=sec,
    )
    
    # --- Shared HTTP server (one port for all channels) ---
    server = sssn.ChannelServer(host="0.0.0.0", port=8000)
    for ch in [news, tasks, results, discovery]:
        ch.attach_transport(sssn.HttpTransport(server=server))
    
    # --- Systems ---
    fetcher = NewsFetcher(id="fetcher", name="News Fetcher")
    processor = Processor(id="processor", name="Processor")
    dashboard = Dashboard(id="dashboard", name="Dashboard")
    
    # --- Wiring ---
    for system in [fetcher, processor, dashboard]:
        system.client.connect("news", news)
        system.client.connect("tasks", tasks)
        system.client.connect("results", results)
        system.client.connect("discovery", discovery)
    
    # --- Announce systems to discovery ---
    for system in [fetcher, processor, dashboard]:
        await system.announce("discovery")
    
    # --- Launch ---
    await asyncio.gather(
        server.start(),
        news.start(), tasks.start(), results.start(), discovery.start(),
        fetcher.run(tick_rate=60),
        processor.run(tick_rate=1),
    )

asyncio.run(main())
```


---

## F. Best Practices: Building with SSSN Step by Step

Like LLLM, SSSN is designed to grow with your project:

| Stage | What you add | What you get |
|-------|-------------|--------------|
| **Prototype** | `PassthroughChannel` + `sssn.register()` | In-memory message passing, 10 lines |
| **Structure** | `BaseSystem` subclasses, typed `MessageContent` | Run loops, schema validation, error handling |
| **Persistence** | `SqliteDBClient` + retention config | Messages survive restarts, queryable history |
| **Security** | `ACLSecurity` or `JWTChannelSecurity` | Access control, audit trail |
| **Scale** | `HttpTransport` + `ChannelServer`, multiple processes | Remote access, distributed deployment |
| **Discovery** | `DiscoveryChannel` | Dynamic system/channel registration |

### F.1 Design Guidelines

**Start with channels, not systems.** Ask: "What information flows between my components?" Draw the channels first. Systems fill in around them.

**One channel per concern.** Don't multiplex unrelated data through the same channel. A design command channel and a telemetry channel serve different purposes, even if the same system reads both.

**Use typed content for important channels.** `GenericContent` is fine for prototyping. For production channels, subclass `MessageContent` so schema errors are caught at write-time, not when a downstream system tries to parse a malformed message.

**Start with `InProcessTransport`, switch later.** Begin with everything in one process. When you need to distribute, swap to `HttpTransport` — the channel interface is identical.

**Use the umbrella pattern.** One launcher script that creates all channels, connects all systems, and starts everything. This makes the network topology visible in one place.

**Let `on_maintain()` do the cleanup.** Set `retention_max_age` and `retention_max_count` on channels. The default lifecycle handles the rest. Only override `on_maintain()` for complex cleanup logic.

### F.2 Common Mistakes

**Over-channeling**: Not every method call needs a channel. If System A calls a synchronous function on System B in the same process, use a direct function call. Channels are for *decoupled*, *observable*, *persistent* information flows.

**Skipping typed content**: Using `GenericContent` for everything works, but you lose schema validation. When a buggy system writes malformed data to a channel, every downstream system breaks. With typed `MessageContent`, the write is rejected at the source.

**Global mutable state outside channels**: If systems share a mutable dict or global variable, that state is invisible to the network. Put shared state in a channel so it's observable, persistent, and access-controlled.

**Monolithic channels**: A single channel carrying commands, results, status, and errors is hard to manage. Split by concern: one channel for commands, one for results, one for status.


---

## G. Channel Lifecycle Summary (Quick Reference)

```
                    ┌─────────┐
                    │  INIT   │
                    └────┬────┘
                         │ start()
                         ▼
                    ┌─────────┐
              ┌────▶│ RUNNING │◀────┐
              │     └────┬────┘     │
              │          │          │
              │    ┌─────┴──────┐   │
              │    │  per cycle │   │
              │    │            │   │
              │    │ on_pull()  │   │
              │    │    ↓       │   │
              │    │ on_process()   │
              │    │    ↓       │   │
              │    │ on_maintain()  │  (every N cycles)
              │    │    ↓       │   │
              │    │  sleep()   │   │
              │    └────────────┘   │
              │                     │
              │   on_error() ───────┘  (non-fatal: log and continue)
              │
              │ stop()
              ▼
         ┌─────────┐
         │ STOPPED  │
         └─────────┘
```

**Defaults that work out of the box:**
- `on_start()`: initializes DB and transport
- `on_pull()`: calls `pull_fn()` with error catching
- `on_process()`: concurrent `convert_fn()` on raw buffer items
- `on_message()`: store → persist → notify subscribers
- `on_maintain()`: evict by `retention_max_age` and `retention_max_count`
- `on_error()`: log and continue (non-fatal)
- `on_stop()`: stop transport

**Override points** (like PyTorch Lightning hooks):
- `on_message()`: add filtering, enrichment, routing logic
- `on_maintain()`: add custom cleanup, compaction, metrics emission
- `on_error()`: add alerting, retry logic, circuit breakers
- `on_start()` / `on_stop()`: add custom setup/teardown
