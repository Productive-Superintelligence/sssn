# Tutorial 3 · Work Queue

In this tutorial you will build a distributed task queue where multiple workers compete for jobs and each job is processed **exactly once**.

**What you'll learn:**

- `WorkQueueChannel` exclusive read semantics
- Claim → process → acknowledge / nack lifecycle
- Automatic reclaim of expired claims from dead workers

---

## The pattern

```
producer ──write──► WorkQueueChannel ──claim──► worker 1
                                     ──claim──► worker 2
                                     ──claim──► worker 3

Each message is owned by exactly one worker.
```

---

## Step 1 — Create the queue

```python
import asyncio
from sssn.channels.work_queue import WorkQueueChannel

async def main():
    queue = WorkQueueChannel(
        id="resize-jobs",
        name="Image Resize Jobs",
        claim_timeout=60.0,   # Workers have 60 seconds to process a job
    )
    await queue.start()
```

`claim_timeout` is the maximum time a worker can hold a claim before it is automatically released and another worker can pick it up. Set it to a safe multiple of your worst-case processing time.

---

## Step 2 — Enqueue jobs

```python
    jobs = [
        {"file": "photo-1.jpg", "size": 1024},
        {"file": "photo-2.jpg", "size": 800},
        {"file": "photo-3.jpg", "size": 2048},
        {"file": "photo-4.jpg", "size": 512},
    ]
    for job in jobs:
        await queue.write("scheduler", job)

    print(f"Queued {len(jobs)} jobs")
```

---

## Step 3 — Workers claim and process

```python
    async def worker(worker_id: str):
        while True:
            # Claim up to 2 jobs exclusively
            msgs = await queue.read(worker_id, limit=2, exclusive=True)
            if not msgs:
                break  # No more work

            for msg in msgs:
                print(f"[{worker_id}] processing {msg.content.data['file']}")
                try:
                    await do_resize(msg.content.data)
                    # Mark as permanently done
                    await queue.acknowledge(worker_id, [msg.id])
                    print(f"[{worker_id}] done: {msg.content.data['file']}")
                except Exception as e:
                    print(f"[{worker_id}] failed: {e}")
                    # Release immediately — another worker can retry
                    await queue.nack(worker_id, [msg.id])

    async def do_resize(job: dict):
        await asyncio.sleep(0.01)  # Simulate work
        print(f"  resized {job['file']} to {job['size']}px")

    # Run two workers concurrently
    await asyncio.gather(
        worker("worker-1"),
        worker("worker-2"),
    )
```

---

## Step 4 — Understand claim lifecycle

### Acknowledge

```python
await queue.acknowledge("worker-1", [msg.id])
```

The message is **permanently removed** from the pool. No other worker will ever see it.

### Nack

```python
await queue.nack("worker-1", [msg.id])
```

The claim is **released immediately**. The message returns to the unclaimed pool and will be picked up by the next `read(exclusive=True)` call. Use this for:

- Recoverable errors (network timeout, temporary dependency unavailability)
- Requeuing for a specific downstream handler

### Timeout reclaim

If a worker crashes or hangs without calling `acknowledge()` or `nack()`, the claim is automatically released after `claim_timeout` seconds. The next `read()` call on any worker triggers the reclaim before presenting new items.

```python
# Simulate a stuck worker
msgs = await queue.read("stuck-worker", limit=1, exclusive=True)
# ... stuck-worker never acknowledges ...

# Force the timeout by manipulating claim time in tests:
queue._store.claims[msgs[0].id] = ("stuck-worker", time.time() - 9999)

# Next read from any worker reclaims the item
available = await queue.read("rescue-worker", limit=10, exclusive=True)
# → includes the previously stuck item
```

---

## Step 5 — Retry with exponential backoff

A common pattern: track retry count in message metadata:

```python
import time, uuid
from sssn.core.channel import ChannelMessage, GenericContent

async def process_with_retry(queue: WorkQueueChannel, worker_id: str, max_retries: int = 3):
    msgs = await queue.read(worker_id, limit=1, exclusive=True)
    if not msgs:
        return

    msg = msgs[0]
    retries = msg.metadata.get("retries", 0)

    try:
        await do_work(msg)
        await queue.acknowledge(worker_id, [msg.id])
    except Exception as e:
        await queue.nack(worker_id, [msg.id])   # Release original

        if retries < max_retries:
            # Re-enqueue with incremented retry count
            retry_msg = ChannelMessage(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                sender_id=worker_id,
                content=msg.content,
                metadata={"retries": retries + 1, "last_error": str(e)},
            )
            await queue.write(worker_id, retry_msg, direct=True)
        else:
            # Dead letter: move to a dead-letter channel
            await dead_letter_queue.write(worker_id, msg, direct=True)
```

---

## Complete program

```python
import asyncio
from sssn.channels.work_queue import WorkQueueChannel

async def main():
    queue = WorkQueueChannel(id="tasks", name="Task Queue", claim_timeout=30.0)
    await queue.start()

    # Enqueue 10 tasks
    for i in range(10):
        await queue.write("producer", {"task_id": i, "payload": f"data-{i}"})

    results: list[str] = []

    async def worker(wid: str):
        while True:
            msgs = await queue.read(wid, limit=3, exclusive=True)
            if not msgs:
                return
            for msg in msgs:
                # Simulate random failure
                import random
                if random.random() < 0.2:
                    await queue.nack(wid, [msg.id])
                    continue
                results.append(f"{wid}:{msg.content.data['task_id']}")
                await queue.acknowledge(wid, [msg.id])

    await asyncio.gather(
        worker("worker-a"),
        worker("worker-b"),
        worker("worker-c"),
    )

    print(f"Processed {len(results)} tasks")

asyncio.run(main())
```

---

## What's next?

Continue to [Tutorial 4 → Multi-System](04-multi-system.md) to learn how to compose multiple systems with explicit channel wiring.
