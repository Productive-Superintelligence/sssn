# SSSN Architecture — Addendum III: Security Authority, Publishing, and the Global Network

> Supplements ARCHITECTURE.md v0.3. These sections modify and extend the main spec.

---

## A. Security Authority: Who Grants Permissions?

### A.1 The Principle

**Permissions are granted externally, by the network operator, not by the network itself.**

This mirrors every real-world security model. An AWS account admin creates IAM roles and distributes credentials. A Kubernetes admin creates service accounts and RBAC rules. A company's IT department issues access badges. The system being accessed never decides who gets access — that decision is made by whoever owns and operates the system.

In SSSN, the **network operator** (the developer who creates and deploys channels) is the security authority. They:

1. Define the access policy for each channel (who can read, write, admin).
2. Generate credentials (tokens) for each system that needs access.
3. Distribute those credentials out-of-band (environment variables, config files, secrets managers).

The SSSN framework provides the *mechanisms* (token generation, verification, access checking). The operator provides the *policy* (who gets what access).

### A.2 Concrete Flow

```
                    EXTERNAL (operator)                    INTERNAL (network)
                    ───────────────────                    ──────────────────
                    
1. Operator creates channels with security policy:
   
   sec = JWTChannelSecurity(secret=os.environ["SSSN_SECRET"])
   dc = WorkQueueChannel(id="design-commands", security=sec)
   
2. Operator generates tokens for each system:
   
   designer_token = await sec.generate_token("designer-1", role="write")
   master_token = await sec.generate_token("master", role="admin")
   
3. Operator distributes tokens out-of-band:
   
   # Via environment variable, config file, secrets manager, etc.
   # This is NOT done through an SSSN channel.
   
4. Systems use tokens to connect:
   
   designer.client.connect_remote(
       "design-commands", 
       "http://coordinator:8000/channels/design-commands",
       token=os.environ["SSSN_DESIGNER_TOKEN"],
   )
   
5. Channel verifies on every operation:
   
   # Internal to BaseChannel — automatic, not user code
   system_id = await self.security.authenticate(token)
   if not await self.security.authorize_write(system_id, self.id):
       raise PermissionError(...)
```

### A.3 Why Not In-Network Permission Granting?

It might seem convenient to have a "permission channel" where systems request access and an admin system grants it. But this creates circular dependencies (you need access to request access) and security risks (the permission channel itself needs to be secured, and any compromise of it compromises everything). 

The external model is simpler and more secure: credentials are generated before the network starts, or by the operator through a separate admin tool, and distributed through secure out-of-band channels.

### A.4 Admin Tools (Not Framework Primitives)

SSSN should provide CLI/utility tools for operators, but these are *operational tools*, not framework abstractions:

```bash
# Generate a token for a system
sssn token generate --system-id designer-1 --role write --secret $SSSN_SECRET --expires 30d

# List access policy for a channel
sssn acl show --channel design-commands

# Grant a system access to a channel
sssn acl grant --channel design-commands --system-id designer-1 --role write
```

These tools modify configuration files or environment variables. They don't run inside the SSSN network.

### A.5 For Local Development

For local development (everything in one process, no real security needed), `OpenSecurity` is the default. No tokens, no ACLs, no configuration. Security only becomes a concern when you distribute or publish.

```python
# Local: no security argument → defaults to OpenSecurity
ch = PassthroughChannel(id="tasks", name="Tasks")

# Production: explicit security
ch = PassthroughChannel(id="tasks", name="Tasks", security=sec)
```


---

## B. Publishing: The SSSN Capstone

### B.1 The LLLM Parallel

LLLM's journey: prototype → structure → package → **publish** (`lllm pkg export/install`).

SSSN's journey: prototype → harden → distribute → **publish** (expose to the internet).

Just as LLLM's capstone is sharing a reusable agent package, SSSN's capstone is publishing your network as a service on the global internet — contributing channels to a worldwide information supply network.

### B.2 The Umbrella System IS the Deployment Unit

**Decision: No separate "Service" class. The umbrella system is the deployment unit.**

Occam's razor: the umbrella system already creates channels, connects systems, manages lifecycle, and controls what's internal. Adding a separate "Service" abstraction creates a new concept that duplicates what the umbrella already does. Instead, the umbrella gains one additional responsibility: declaring which channels are exposed to the outside world.

```python
class GenesysNetwork(sssn.BaseSystem):
    """
    The umbrella system for the Genesys discovery network.
    This IS the deployment unit. It creates channels, launches systems,
    and declares what's publicly accessible.
    """
    
    async def setup(self):
        # --- Internal channels (not exposed) ---
        self.dc = sssn.WorkQueueChannel(id="design-commands", name="Design Commands")
        self.dd = sssn.PassthroughChannel(id="design-delivery", name="Design Delivery")
        self.ec = sssn.WorkQueueChannel(id="eval-commands", name="Eval Commands")
        self.ed = sssn.PassthroughChannel(id="eval-delivery", name="Eval Delivery")
        
        # --- Public channels (exposed to the internet) ---
        self.et = EvolutionTreeChannel(
            id="evolution-tree", name="Evolution Tree",
            db_client=sssn.FirebaseDBClient(...),
            visibility=sssn.Visibility.PUBLIC,       # ← exposed
        )
        self.leaderboard = sssn.BroadcastChannel(
            id="leaderboard", name="Discovery Leaderboard",
            visibility=sssn.Visibility.PUBLIC,       # ← exposed
        )
        self.dr = sssn.PassthroughChannel(
            id="design-requests", name="Design Requests",
            visibility=sssn.Visibility.PUBLIC,        # ← external designers can submit
        )
        
        # --- Systems ---
        self.master = EvolutionaryMaster(id="master", name="Master")
        self.designers = [Designer(id=f"designer-{i}", ...) for i in range(4)]
        self.verifiers = [Verifier(id=f"verifier-{i}", ...) for i in range(8)]
        
        # --- Wire ---
        # ... connect systems to channels ...
    
    async def step(self):
        pass  # Umbrella doesn't have its own logic; it just orchestrates.
    
    # --- Publication ---
    def get_public_channels(self) -> List[BaseChannel]:
        """Returns channels marked as PUBLIC. Used by publish()."""
        return [ch for ch in self.all_channels if ch.visibility == sssn.Visibility.PUBLIC]
```

### B.3 Visibility: Two Levels

**Decision: Two visibility levels, controlled per-channel.**

| Level | Meaning | Who can access |
|-------|---------|---------------|
| `PRIVATE` (default) | Internal to the network. Not exposed via any external transport. | Only systems within the same umbrella / local network. |
| `PUBLIC` | Exposed to the internet. Accessible by external systems, humans, other SSSN networks. | Anyone with valid credentials (per the channel's security policy). |

There's no need for a third "internet" level distinct from "public." Public *means* internet-accessible once the umbrella publishes it. The umbrella system decides which channels are public. Private channels are invisible to the outside world — they don't get HTTP routes, they're not listed in discovery.

```python
class Visibility(Enum):
    PRIVATE = "private"   # Internal only. Default.
    PUBLIC = "public"     # Exposed to external world when published.
```

This is set per-channel at creation time:

```python
# Internal: only systems in this network can access
dc = WorkQueueChannel(id="design-commands", visibility=Visibility.PRIVATE)

# Public: exposed when the umbrella publishes
leaderboard = BroadcastChannel(id="leaderboard", visibility=Visibility.PUBLIC)
```

### B.4 The `publish()` Flow

Publishing is the act of making public channels accessible on the internet.

```python
async def main():
    network = GenesysNetwork(id="genesys", name="Genesys Discovery Network")
    await network.setup()
    
    # Option A: Publish with built-in HTTP server
    await network.publish(host="0.0.0.0", port=8000)
    # This:
    #   1. Creates a ChannelServer
    #   2. Mounts only PUBLIC channels as HTTP endpoints
    #   3. Applies each channel's security policy to the HTTP routes
    #   4. Registers public channels to the discovery endpoint
    #   5. Starts the server
    
    # Option B: Publish with explicit server (for nginx/reverse proxy setups)
    server = sssn.ChannelServer(host="0.0.0.0", port=8000)
    await network.publish(server=server)
    
    # Then in production, nginx/Cloudflare routes external traffic to port 8000.
```

What `publish()` does internally:

```python
class BaseSystem:
    async def publish(self, host="0.0.0.0", port=8000, server=None):
        """
        Expose all PUBLIC channels via HTTP and start the network.
        This is the capstone: your network becomes a service on the internet.
        """
        server = server or ChannelServer(host=host, port=port)
        
        public_channels = self.get_public_channels()
        for ch in public_channels:
            ch.attach_transport(HttpTransport(server=server))
        
        # Start all channels (public and private)
        for ch in self.all_channels:
            await ch.start()
        
        # Start all systems
        tasks = [sys.run() for sys in self.all_systems]
        
        # Start the HTTP server (blocks)
        tasks.append(server.start())
        
        # If discovery channel exists, register public channels
        disc = self._find_discovery_channel()
        if disc:
            for ch in public_channels:
                await disc.register_channel(ch.info)
        
        await asyncio.gather(*tasks)
```

### B.5 The External Consumer Experience

From the outside world, a published SSSN network looks like a REST API with channel endpoints:

```
https://genesys.example.com/channels/evolution-tree      GET  → read designs
https://genesys.example.com/channels/leaderboard         GET  → read rankings
https://genesys.example.com/channels/design-requests     PUT  → submit new design
https://genesys.example.com/discovery                    GET  → list all public channels
```

An external system connects:

```python
# External researcher connecting to the public Genesys network
client = sssn.register(id="external-researcher", name="My Lab")
client.connect_remote(
    "evolution-tree", 
    "https://genesys.example.com/channels/evolution-tree",
    token=my_api_token,
)

# Read the latest discovered designs
designs = await client.read("evolution-tree", limit=20)

# Subscribe to leaderboard updates
client.connect_remote("leaderboard", "https://genesys.example.com/channels/leaderboard", token=my_api_token)
await client.subscribe("leaderboard", callback=on_new_champion)

# Submit a design from my own lab
client.connect_remote("design-requests", "https://genesys.example.com/channels/design-requests", token=my_api_token)
await client.write("design-requests", data=MyDesignProposal(...))
```

An external SSSN network connecting to another SSSN network is just a system connecting to remote channels. There's no special "network-to-network" protocol — the channel interface is the protocol.

### B.6 The Global Information Supply Network

When multiple SSSN networks publish their channels, they form a global information supply network:

```
┌─────────────────────┐     ┌─────────────────────┐
│  Genesys Network    │     │  EvalBench Network   │
│  (Allen AI)         │     │  (Stanford)          │
│                     │     │                      │
│  📢 evolution-tree  │────▶│  reader system       │
│  📢 leaderboard    │     │                      │
│  📢 design-requests│◀────│  📢 benchmark-results│
│  🔒 design-commands│     │  🔒 eval-queue       │
│  🔒 eval-commands  │     │                      │
└─────────────────────┘     └─────────────────────┘
         │                           │
         │     ┌─────────────────┐   │
         └────▶│ Research Monitor │◀──┘
               │ (Independent)   │
               │                 │
               │ 📢 weekly-digest│──▶ subscribers worldwide
               └─────────────────┘

📢 = PUBLIC channel    🔒 = PRIVATE channel
```

Each network publishes what it wants to share. External systems connect to the public channels they need. The channel interface (read/write/subscribe with typed messages and security) is the universal protocol. No special federation mechanism required — it's just systems connecting to remote channels.


---

## C. How This Threads Through the Design

### C.1 Updated Channel Constructor

```python
class BaseChannel(abc.ABC):
    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        # ... existing params ...
        visibility: Visibility = Visibility.PRIVATE,    # ← new
        security: Optional[ChannelSecurity] = None,     # existing
    ):
        ...
```

### C.2 Updated BaseSystem

```python
class BaseSystem(abc.ABC):
    
    # === Existing ===
    # ... id, name, description, state, directories, client ...
    
    # === New: umbrella capabilities ===
    
    _channels: List[BaseChannel]        # Channels created by this system
    _subsystems: List[BaseSystem]       # Systems managed by this system
    
    def add_channel(self, channel: BaseChannel):
        """Register a channel as owned by this system."""
        self._channels.append(channel)
        self.register_channel(channel.id)
    
    def add_subsystem(self, system: BaseSystem, channels: Optional[List[str]] = None):
        """
        Register a sub-system managed by this system.
        channels: explicit list of channel IDs to wire. If None, NO auto-wiring.
        The developer specifies which channels each sub-system accesses (least privilege).
        """
        self._subsystems.append(system)
        self.register_peer(system.id)
        if channels:
            for ch_id in channels:
                ch = next((c for c in self._channels if c.id == ch_id), None)
                if ch:
                    system.client.connect(ch_id, ch)
    
    @property
    def all_channels(self) -> List[BaseChannel]:
        return list(self._channels)
    
    @property
    def all_systems(self) -> List[BaseSystem]:
        return list(self._subsystems)
    
    def get_public_channels(self) -> List[BaseChannel]:
        return [ch for ch in self._channels if ch.visibility == Visibility.PUBLIC]
    
    async def publish(self, host="0.0.0.0", port=8000, server=None):
        """Expose PUBLIC channels via HTTP and start the entire network."""
        ...
    
    async def launch(self):
        """Start all channels and systems without HTTP exposure. For local-only networks."""
        for ch in self._channels:
            await ch.start()
        await asyncio.gather(*[sys.run() for sys in self._subsystems], self.run())
```

### C.3 Updated Development Phases

The four phases from Addendum II now have a fifth:

| Phase | What you do | Output |
|-------|------------|--------|
| **1. Think in Flows** | Diagram topology. Mark which channels are public. | Channel/system tables with visibility column |
| **2. Prototype** | In-memory, one process. `launch()`. | Working local network |
| **3. Harden** | Types, persistence, security, error handling. | Production-ready local network |
| **4. Distribute** | HTTP transport, remote connections. | Multi-process/machine network |
| **5. Publish** | `publish()`. Public channels go live. | Service on the internet |

### C.4 Updated Genesys Case Study

The Genesys channel table gains a visibility column:

| Channel | Mode | Visibility | Description |
|---------|------|-----------|-------------|
| **Design Request (DR)** | Shared | **PUBLIC** | External designers can submit proposals |
| **Design Command (DC)** | Exclusive | PRIVATE | Internal job assignment |
| **Design Delivery (DD)** | Shared | PRIVATE | Internal artifact delivery |
| **Eval Request (ER)** | Shared | PRIVATE | Internal eval requests |
| **Eval Command (EC)** | Exclusive | PRIVATE | Internal eval assignment |
| **Eval Delivery (ED)** | Shared | PRIVATE | Internal eval results |
| **Evolution Tree (ET)** | Shared | **PUBLIC** | Anyone can browse discovered designs |
| **Leaderboard** | Broadcast | **PUBLIC** | Real-time design rankings |

The Genesys network publishes 3 channels. The other 4 are internal. External researchers can browse the evolution tree, watch the leaderboard, and submit new designs — but they can't see the internal job assignment and delivery channels.

### C.5 Updated Best Practices

Add to the development guidelines:

**Design visibility early.** When drawing your topology in Phase 1, mark each channel as public or private. Ask: "Would it be useful for external systems to read/write this channel?" The evolution tree is useful to external researchers → public. Design commands are internal coordination → private.

**Public channels need typed content.** If a channel is public, external systems need to know the schema. Always use typed `MessageContent` subclasses for public channels, never `GenericContent`.

**Public channels need security.** Every public channel should have a `ChannelSecurity` policy. `OpenSecurity` on a public channel means anyone on the internet can read/write it.

**Start private, publish later.** Everything is private by default. Only mark channels as public when you're ready. `publish()` only exposes what you've explicitly marked.


---

## D. Complete Journey: From 5 Lines to Global Network

```
Stage 1: Prototype (5 lines)
─────────────────────────────
ch = PassthroughChannel(id="chat", name="Chat")
alice = sssn.register(id="alice", name="Alice")
alice.connect("chat", ch)
await alice.write("chat", data="Hello!")

Stage 2: Structure (umbrella + typed content)
──────────────────────────────────────────────
class MyNetwork(BaseSystem):
    async def setup(self):
        self.add_channel(WorkQueueChannel(id="tasks", ...))
        self.add_subsystem(Worker(id="worker-1", ...), channels=["tasks"])
    # step() not needed for umbrella — default is no-op

await MyNetwork(...).launch()

Stage 3: Harden (persistence + security)
──────────────────────────────────────────
self.add_channel(WorkQueueChannel(
    id="tasks", db_client=SqliteDBClient(...),
    security=JWTChannelSecurity(secret=...),
    retention_max_age=7*86400,
))

Stage 4: Distribute (HTTP transport)
──────────────────────────────────────
await network.publish(host="0.0.0.0", port=8000)
# Or with nginx reverse proxy in front

Stage 5: Go Global (public channels)
──────────────────────────────────────
self.add_channel(BroadcastChannel(
    id="leaderboard", visibility=Visibility.PUBLIC, ...
))
# External systems worldwide can now subscribe to your leaderboard
```

The progression mirrors LLLM:

| LLLM | SSSN |
|------|------|
| `Tactic.quick("Hello")` | `PassthroughChannel` + `register()` |
| `lllm.toml` + prompt files | Umbrella system + typed content |
| Subclass Tactic, YAML config | `BaseSystem`, persistence, security |
| `lllm pkg export` | `network.publish()` |
| Others import your package | Others connect to your public channels |
