# Welcome to SSSN

<p align="center">
  <img src="assets/SSSN-logo-txt-dark.png#only-light" alt="SSSN Logo" width="600"/>
  <img src="assets/SSSN-logo-txt-white.png#only-dark" alt="SSSN Logo" width="600"/>
</p>

**Simple System of Systems Network** — a minimal Python framework and protocols for distributed and continuous AI agent networks.


---

## The Mental Model

SSSN has exactly two abstractions.

```
┌─────────────────────────────────────────────────────────┐
│                       SYSTEM                            │
│   A node that does work: reads channels, runs logic,   │
│   writes results, and owns the channels it produces.   │
└────────────────┬──────────────┬───────────────┬─────────┘
                 │              │               │
           Channel          Channel         Channel
           (edge)           (edge)          (edge)
                 │              │               │
┌────────────────┴──────────────┴───────────────┴─────────┐
│                       SYSTEM                            │
│   Another node. Reads from one or more of the above    │
│   channels and writes to its own.                      │
└─────────────────────────────────────────────────────────┘
```

A **Channel** is an edge — a typed, secured, persistent message store. A **System** is a node — an autonomous agent that reads, computes, and writes. Wire Systems together with Channels to build arbitrarily complex networks.

That's the whole model.

---

## Design Principles

**Minimal surface area.**
Two classes, six consumption methods, one lifecycle. No framework magic.

**Composition over configuration.**
Systems wire themselves to channels explicitly. Nothing is auto-wired. Every dependency is visible in code.

**Security by interface.**
Every read and write goes through a pluggable security layer. Swapping from development (open) to production (JWT) is one constructor argument.

**Progressive complexity.**
A local in-process network launches with `launch()`. The exact same code exposes itself over HTTP with `publish()`. Scale is a deployment decision, not a code change.

---

## Quick Start

```python
import asyncio
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.system import BaseSystem

class Sensor(BaseSystem):
    async def setup(self):
        self.events = BroadcastChannel(id="events", name="Events")
        self.add_channel(self.events)

    async def step(self):
        await self.write_channel("events", data={"temp": 22.4})

class Monitor(BaseSystem):
    async def setup(self):
        pass  # reads from parent's channel via wiring

    async def step(self):
        msgs = await self.read_channel("events")
        for msg in msgs:
            print(msg.content)

async def main():
    sensor = Sensor(id="sensor", name="Temperature Sensor")
    monitor = Monitor(id="monitor", name="Monitor")

    await sensor.setup()
    sensor.add_subsystem(monitor, channels=["events"])

    await asyncio.gather(sensor.launch(), monitor.run())

asyncio.run(main())
```

---

## Channel Types at a Glance

| Channel | Pattern | Exclusive read? |
|---------|---------|----------------|
| `PassthroughChannel` | Base — no pull loop, inline write | Optional |
| `BroadcastChannel` | Fan-out; every subscriber sees every message | No (shared only) |
| `WorkQueueChannel` | Competing consumers; each item claimed once | Yes (required) |
| `MailboxChannel` | Per-recipient inbox; each reader sees only their messages | Shared |
| `PeriodicChannel` | Active poll loop — extend and implement `pull_fn` | Optional |
| `DiscoveryChannel` | Service registry with TTL-based expiry | No |

---

## Learning Path

| Step | What you'll learn |
|------|-------------------|
| [Concepts → Channel](concepts/channel.md) | The consumption interface, MessageStore, lifecycle |
| [Concepts → System](concepts/system.md) | setup/step/run, topology, launch vs publish |
| [Tutorial 1 — First Channel](tutorials/01-first-channel.md) | Write and read your first message |
| [Tutorial 2 — Broadcast Bus](tutorials/02-broadcast.md) | Push-based fan-out with subscribers |
| [Tutorial 3 — Work Queue](tutorials/03-work-queue.md) | Claim, process, acknowledge |
| [Tutorial 4 — Multi-System](tutorials/04-multi-system.md) | Composite topology with subsystems |
| [Tutorial 5 — Security](tutorials/05-securing-channels.md) | ACL and JWT access control |
| [Examples](examples/index.md) | Complete working programs |

---

## Installation

```bash
pip install sssn
```

Requires Python 3.10+.
