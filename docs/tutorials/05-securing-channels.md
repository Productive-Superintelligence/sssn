# Tutorial 5 · Securing Channels

In this tutorial you will add access control to a channel pipeline — starting with the simple ACL model for internal use, then upgrading to JWT tokens for production HTTP deployment.

**What you'll learn:**

- `ACLSecurity` role hierarchy: `read` → `write` → `admin`
- Generating and using `JWTChannelSecurity` tokens
- How `PermissionError` surfaces to callers
- The difference between local (always trusted) and HTTP (fully validated) JWT auth

---

## Starting point

A `WorkQueueChannel` that currently has no security (uses `OpenSecurity` by default):

```python
from sssn.channels.work_queue import WorkQueueChannel

queue = WorkQueueChannel(id="jobs", name="Job Queue")
await queue.start()
```

---

## Part 1 — ACL security

### Attach an ACL

```python
from sssn.core.security import ACLSecurity
from sssn.channels.work_queue import WorkQueueChannel

sec = ACLSecurity()
sec.grant("scheduler", "write")          # scheduler can enqueue
sec.grant("worker-1",  "write")          # workers need write for acknowledge/nack
sec.grant("worker-2",  "write")
sec.grant("ops-dashboard", "admin")      # admin can clear, evict, remove

queue = WorkQueueChannel(id="jobs", name="Job Queue", security=sec)
await queue.start()
```

### What each role grants

```python
# scheduler can write (enqueue)
await queue.write("scheduler", {"task": "compress", "file": "video.mp4"})  # ✓

# worker-1 can read (claim) — write role implies read
msgs = await queue.read("worker-1", limit=5, exclusive=True)                # ✓
await queue.acknowledge("worker-1", [msgs[0].id])                           # ✓

# rogue cannot read
try:
    await queue.read("rogue-process", exclusive=True)
except PermissionError as e:
    print(e)  # 'rogue-process' is not authorised to read from channel 'jobs'.
```

### Dynamic grant/revoke

ACL entries can be modified at runtime:

```python
# Onboard a new worker
sec.grant("worker-3", "write")

# Offboard a compromised worker
sec.revoke("worker-1")
```

Changes take effect on the **next** `read()` or `write()` call — no restart required.

---

## Part 2 — JWT security (local)

JWT tokens are appropriate when:

- Systems communicate over HTTP
- You want token expiry
- You want per-channel scoping

```python
from sssn.core.security import JWTChannelSecurity

sec = JWTChannelSecurity(secret="your-32-byte-production-secret-key")
queue = WorkQueueChannel(id="jobs", name="Job Queue", security=sec)
await queue.start()
```

### Generate tokens

```python
# Read+write token for workers, scoped to this channel, expires in 8 hours
worker_token = await sec.generate_token(
    system_id="worker-1",
    role="write",
    channel_ids=["jobs"],
    expires_in=8 * 3600,
)

# Admin token for ops (all channels, no scope restriction)
admin_token = await sec.generate_token(
    system_id="ops-tool",
    role="admin",
    channel_ids=None,    # None = all channels
    expires_in=3600,
)
```

### Local calls are always trusted

For **in-process** calls, `JWTChannelSecurity` behaves like `OpenSecurity` — `authorize_read/write/admin` always return `True`. This is by design: systems that share a process are trusted at the architectural level.

```python
# In-process call: always works regardless of the token
await queue.write("any-local-system", {"task": "..."})   # ✓
```

JWT validation only fires when calls arrive **over HTTP**, via `authorize_from_token()`.

---

## Part 3 — JWT over HTTP

Expose the channel over HTTP and require Bearer tokens:

```python
from sssn.core.channel import Visibility
from sssn.channels.work_queue import WorkQueueChannel
from sssn.core.security import JWTChannelSecurity
from sssn.infra.server import ChannelServer
from sssn.core.transport import HttpTransport

SECRET = "your-32-byte-production-secret-key"
sec = JWTChannelSecurity(secret=SECRET)

queue = WorkQueueChannel(
    id="jobs",
    name="Job Queue",
    visibility=Visibility.PUBLIC,
    security=sec,
)

server = ChannelServer(host="0.0.0.0", port=8000)
queue.attach_transport(HttpTransport(server=server))
await queue.start()
await server.start()
```

Remote workers authenticate with their token:

```python
import httpx

worker_token = "..."  # obtained from token endpoint

async with httpx.AsyncClient() as client:
    # Claim jobs
    resp = await client.get(
        "http://localhost:8000/channels/jobs",
        headers={"Authorization": f"Bearer {worker_token}"},
        params={"exclusive": True, "limit": 5},
    )
    msgs = resp.json()["messages"]

    # Acknowledge
    await client.post(
        "http://localhost:8000/channels/jobs/acknowledge",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={"message_ids": [m["id"] for m in msgs]},
    )
```

A token with insufficient role returns `403 Forbidden`. An expired or tampered token returns `401 Unauthorized`.

---

## Part 4 — Using `ChannelClient` with tokens

Systems that consume remote channels use `ChannelClient` with the token pre-configured:

```python
from sssn.core.client import ChannelClient

client = ChannelClient(system_id="worker-3")
client.connect_remote(
    "jobs",
    url="http://job-server:8000",
    token=worker_token,
)

# All subsequent calls include the Authorization header automatically
msgs = await client.read("jobs", exclusive=True, limit=5)
```

---

## Security decision guide

| Scenario | Use |
|----------|-----|
| Local dev, single machine | `OpenSecurity` (default) |
| Internal services, trusted network | `ACLSecurity` |
| Internet-facing, token-based | `JWTChannelSecurity` |
| Enterprise SSO, OAuth, custom | Subclass `ChannelSecurity` |

Start with `OpenSecurity`, promote to `ACLSecurity` when you need role separation, and graduate to `JWTChannelSecurity` when you publish channels over HTTP.

---

## What's next?

Explore the [Examples](../examples/index.md) section for complete, production-shaped programs.
