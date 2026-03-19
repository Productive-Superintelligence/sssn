# Example · Service Discovery

Systems register their channels and capabilities at startup. Other systems query the registry at runtime to find what's available — no hardcoded addresses.

---

## Setup

```python
import asyncio
from sssn.channels.discovery import DiscoveryChannel
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.channel import Visibility, ChannelInfo
from sssn.core.system import BaseSystem


# ---------------------------------------------------------------------------
# A service that publishes itself to the registry
# ---------------------------------------------------------------------------

class TemperatureService(BaseSystem):
    async def setup(self):
        self.feed = BroadcastChannel(
            id="temperature-feed",
            name="Temperature Feed",
            description="Live temperature readings from all sensors",
            visibility=Visibility.PUBLIC,
        )
        self.add_channel(self.feed)

    async def announce(self, registry: DiscoveryChannel):
        await registry.register_channel(self.feed.info)
        await registry.register_system(
            self._service_descriptor.model_dump()
        )
        print(f"[{self.id}] registered with discovery")

    async def step(self):
        import time
        await self.write_channel("temperature-feed", data={"celsius": 22.4, "ts": time.time()})


# ---------------------------------------------------------------------------
# A client that discovers the service at runtime
# ---------------------------------------------------------------------------

class DataConsumer(BaseSystem):
    def __init__(self, registry: DiscoveryChannel, **kwargs):
        super().__init__(**kwargs)
        self._registry = registry
        self._connected = False

    async def setup(self):
        pass  # Connected lazily on first step

    async def step(self):
        if not self._connected:
            await self._discover_and_connect()

        msgs = await self.read_channel("temperature-feed", limit=20)
        for msg in msgs:
            print(f"[Consumer] temp={msg.content.data.get('celsius')}°C")

    async def _discover_and_connect(self):
        # Find public channels
        channels = await self._registry.find_channels(visibility="public")
        temp_channels = [c for c in channels if "temperature" in c.name.lower()]

        if not temp_channels:
            print("[Consumer] no temperature channels found yet, retrying...")
            return

        for info in temp_channels:
            # In a real system this would use ChannelClient.connect_remote() with HTTP
            # For this in-process demo, we look up the channel directly
            ch = _channel_registry.get(info.id)
            if ch:
                self.client.connect(info.id, ch)
                print(f"[Consumer] connected to '{info.name}' ({info.id})")

        self._connected = True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Simple in-process channel lookup for demo purposes
_channel_registry: dict = {}

async def main():
    # Shared discovery channel (TTL = 5 minutes for demo)
    registry = DiscoveryChannel(
        id="registry",
        name="Service Registry",
        registration_ttl=300.0,
    )
    await registry.start()

    # Service
    svc = TemperatureService(id="temp-svc", name="Temperature Service")
    await svc.setup()
    _channel_registry["temperature-feed"] = svc.feed
    await svc.announce(registry)

    # Consumer
    consumer = DataConsumer(id="consumer", name="Data Consumer", registry=registry)
    await consumer.setup()

    # Run for 5 seconds
    async def run_limited(system, tick_rate, duration):
        try:
            await asyncio.wait_for(system.run(tick_rate=tick_rate), timeout=duration)
        except asyncio.TimeoutError:
            system.stop()

    await asyncio.gather(
        run_limited(svc,      tick_rate=2.0, duration=5),
        run_limited(consumer, tick_rate=2.0, duration=5),
    )

asyncio.run(main())
```

---

## Finding systems by capability

```python
# Find systems that expose a "process_image" service
systems = await registry.find_systems(capability="process_image")
for sys_info in systems:
    print(f"Found: {sys_info['system_name']} ({sys_info['system_id']})")
    print(f"  services: {[s['name'] for s in sys_info['services']]}")
```

`find_systems(capability=X)` filters by checking whether any of the system's declared service names match `X`. Systems are registered via `register_system(descriptor.model_dump())`.

---

## TTL-based expiry

Registrations carry an `expires_at` timestamp. `on_maintain()` purges expired entries:

```python
registry = DiscoveryChannel(
    id="registry",
    name="Registry",
    registration_ttl=60.0,       # Entries expire after 60 seconds
    maintenance_interval_seconds=30.0,  # Check every 30 seconds
)
```

To keep a long-running service registered, re-register before TTL expires:

```python
async def heartbeat(svc: TemperatureService, registry: DiscoveryChannel, interval: float):
    while True:
        await svc.announce(registry)
        await asyncio.sleep(interval)

# Refresh every 45 seconds when TTL is 60
asyncio.create_task(heartbeat(svc, registry, interval=45))
```

---

## Point lookups

```python
# Get a specific channel by ID
info: ChannelInfo | None = await registry.get_channel("temperature-feed")
if info:
    print(f"Channel: {info.name}, period={info.period}s, visibility={info.visibility}")

# Get a specific system
sys_desc = await registry.get_system("temp-svc")
if sys_desc:
    print(f"System: {sys_desc['system_name']}")
```
