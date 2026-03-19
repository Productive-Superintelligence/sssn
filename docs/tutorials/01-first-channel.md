# Tutorial 1 · First Channel

In this tutorial you will create a `PassthroughChannel`, write a message, and read it back. This is the simplest possible SSSN program.

**What you'll learn:**

- How a `PassthroughChannel` works
- The difference between `write()` and `read()`
- Why messages persist after being read

---

## Step 1 — Create and start a channel

```python
import asyncio
from sssn.channels.passthrough import PassthroughChannel

async def main():
    channel = PassthroughChannel(
        id="notes",
        name="Notes",
        description="A simple note-taking channel",
    )
    await channel.start()

asyncio.run(main())
```

`start()` on a `PassthroughChannel` does two things:

1. Sets `_is_running = True` and `_accepting_writes = True`.
2. Calls `on_start()` (which initialises any configured DB or transport).

Crucially, it does **not** create a background loop. Data arrives only via `write()`.

---

## Step 2 — Write a message

```python
    msg_id = await channel.write("tutorial-user", {"note": "Hello, SSSN!"})
    print(f"Wrote message: {msg_id}")
```

`write()` performs inline conversion:

1. Wraps `{"note": "Hello, SSSN!"}` in `GenericContent(data={"note": "Hello, SSSN!"})`.
2. Creates a `ChannelMessage` with a new UUID and the current timestamp.
3. Appends it to the `MessageStore`.
4. Notifies any registered subscribers.
5. Returns the message's stable `id`.

---

## Step 3 — Read the message

```python
    msgs = await channel.read("tutorial-user", limit=10)
    print(f"Read {len(msgs)} message(s)")
    for msg in msgs:
        print(f"  {msg.sender_id}: {msg.content.data}")
```

Output:
```
Wrote message: 3f4a1b2c-...
Read 1 message(s)
  tutorial-user: {'note': 'Hello, SSSN!'}
```

### Cursors advance automatically

Every reader has an independent cursor. The first `read()` returns all available messages; subsequent calls return only **new** messages since the last read.

```python
    msgs2 = await channel.read("tutorial-user", limit=10)
    print(f"Second read: {len(msgs2)} message(s)")  # → 0
```

To reset the cursor, pass `after=None` ... actually the cursor is stored server-side. Write another message to see it:

```python
    await channel.write("tutorial-user", {"note": "Second note"})
    msgs3 = await channel.read("tutorial-user", limit=10)
    print(f"Third read: {len(msgs3)} message(s)")  # → 1
```

---

## Step 4 — Multiple independent readers

Multiple readers each maintain their own cursor:

```python
    await channel.write("system-a", "first")
    await channel.write("system-a", "second")
    await channel.write("system-a", "third")

    # Reader A reads all three
    msgs_a = await channel.read("reader-a", limit=10)

    # Reader B has not read yet — still sees all three
    msgs_b = await channel.read("reader-b", limit=10)

    print(len(msgs_a), len(msgs_b))  # → 3, 3
```

This is how SSSN supports fan-out without duplication: the store holds one copy of each message; each reader tracks where they are.

---

## Complete program

```python
import asyncio
from sssn.channels.passthrough import PassthroughChannel

async def main():
    channel = PassthroughChannel(id="notes", name="Notes")
    await channel.start()

    # Write three messages as different senders
    await channel.write("alice", {"text": "Meeting at 3pm"})
    await channel.write("bob",   {"text": "Confirmed"})
    await channel.write("alice", {"text": "See you then"})

    # Each reader has an independent cursor
    msgs_alice = await channel.read("alice", limit=10)
    msgs_bob   = await channel.read("bob",   limit=10)
    msgs_carol = await channel.read("carol", limit=10)

    print(f"Alice sees {len(msgs_alice)} messages")  # 3
    print(f"Bob sees   {len(msgs_bob)}   messages")  # 3
    print(f"Carol sees {len(msgs_carol)} messages")  # 3

asyncio.run(main())
```

---

## What's next?

Continue to [Tutorial 2 → Broadcast Bus](02-broadcast.md) to learn about push-based delivery with `subscribe()`.
