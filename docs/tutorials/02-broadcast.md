# Tutorial 2 · Broadcast Bus

In this tutorial you will build an event bus where multiple consumers receive every event the moment it is published.

**What you'll learn:**

- `BroadcastChannel` and fan-out semantics
- Push-based delivery with `subscribe()`
- Why exclusive reads are prohibited on a broadcast channel

---

## The pattern

A broadcast channel is designed for **one producer, many consumers**. Every subscriber receives every message — there is no claiming, no acknowledgement, no "consumed" state.

```
producer ──write──► BroadcastChannel ──push──► subscriber A
                                     ──push──► subscriber B
                                     ──push──► subscriber C
```

---

## Step 1 — Create the bus

```python
import asyncio
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.channel import ChannelMessage

async def main():
    bus = BroadcastChannel(id="events", name="Event Bus")
    await bus.start()
```

---

## Step 2 — Register subscribers

```python
    received_by_a: list[str] = []
    received_by_b: list[str] = []

    async def handler_a(msg: ChannelMessage):
        received_by_a.append(msg.content.data["type"])
        print(f"[A] received: {msg.content.data}")

    async def handler_b(msg: ChannelMessage):
        received_by_b.append(msg.content.data["type"])
        print(f"[B] received: {msg.content.data}")

    await bus.subscribe("consumer-a", handler_a)
    await bus.subscribe("consumer-b", handler_b)
```

`subscribe()` registers an async callback. The callback fires **synchronously within the `write()` call** — by the time `write()` returns, all subscribers have been notified.

If a subscriber raises an exception it is logged and **does not affect other subscribers**.

---

## Step 3 — Publish events

```python
    await bus.write("service", {"type": "user.login",  "user": "alice"})
    await bus.write("service", {"type": "user.logout", "user": "bob"})

    print(f"A received: {received_by_a}")  # ['user.login', 'user.logout']
    print(f"B received: {received_by_b}")  # ['user.login', 'user.logout']
```

---

## Step 4 — Late-joining consumers (poll mode)

Subscribers that register after some messages have already been published miss those messages. Late-joining consumers can **catch up** using shared reads:

```python
    # Carol subscribes late and polls the history
    history = await bus.read("carol", limit=100)
    print(f"Carol sees {len(history)} events in history")  # 2
```

After catching up, Carol can optionally subscribe for future events:

```python
    async def handler_carol(msg: ChannelMessage):
        print(f"[Carol] live: {msg.content.data}")

    await bus.subscribe("carol", handler_carol)
    await bus.write("service", {"type": "user.purchase"})
    # → [Carol] live: {'type': 'user.purchase'}
```

---

## Step 5 — Unsubscribe

```python
    await bus.unsubscribe("consumer-a")
    await bus.write("service", {"type": "system.reboot"})
    # Consumer A no longer receives events
    # Consumer B still does
```

---

## Why exclusive reads are blocked

`BroadcastChannel` raises `TypeError` if you attempt `read(exclusive=True)`. This is intentional:

- Exclusive reads are for work-queue semantics: one consumer claims a message and others cannot see it.
- A broadcast channel is designed for **all consumers to see all messages**. Exclusive reads would break this invariant.

```python
    try:
        await bus.read("reader", exclusive=True)
    except TypeError as e:
        print(e)
        # BroadcastChannel does not support exclusive reads.
```

Use `WorkQueueChannel` when you want exclusive claiming.

---

## Complete program

```python
import asyncio
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.channel import ChannelMessage

async def main():
    bus = BroadcastChannel(id="telemetry", name="Telemetry")
    await bus.start()

    log: list[tuple[str, str]] = []

    async def make_handler(name: str):
        async def handler(msg: ChannelMessage):
            log.append((name, msg.content.data["metric"]))
        return handler

    await bus.subscribe("dashboard",  await make_handler("dashboard"))
    await bus.subscribe("alerting",   await make_handler("alerting"))
    await bus.subscribe("archiver",   await make_handler("archiver"))

    metrics = ["cpu", "memory", "disk", "network"]
    for m in metrics:
        await bus.write("monitor", {"metric": m, "value": 42})

    print(f"Total deliveries: {len(log)}")  # 12 (4 metrics × 3 subscribers)
    assert all(count == 4 for _, count in
               [(name, log.count((name, _m)) for _m in metrics)
                for name in ["dashboard", "alerting", "archiver"]])

asyncio.run(main())
```

---

## What's next?

Continue to [Tutorial 3 → Work Queue](03-work-queue.md) to learn about competing consumers with claim-based exclusive reads.
