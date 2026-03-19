# Transport & Client

SSSN separates the **consumption interface** (read/write/subscribe) from the **transport layer** (how messages cross process boundaries). A channel's logic never changes; only the transport is swapped.

---

## Transport

The `ChannelTransport` interface has two methods:

```python
class ChannelTransport(abc.ABC):
    async def start(self, channel: BaseChannel) -> None: ...
    async def stop(self) -> None: ...
```

### InProcessTransport

The default — a no-op. All calls stay in the same Python process. No ports, no serialisation, no network overhead.

```python
from sssn.core.transport import InProcessTransport
# This is the default; you never need to set it explicitly.
```

### HttpTransport

Registers five FastAPI routes on a `ChannelServer`, making the channel reachable over HTTP:

| Route | Method | Purpose |
|-------|--------|---------|
| `/channels/{id}` | `GET` | Read messages |
| `/channels/{id}` | `PUT` | Write to channel |
| `/channels/{id}/acknowledge` | `POST` | Acknowledge claimed messages |
| `/channels/{id}/nack` | `POST` | Nack (release) claimed messages |
| `/channels/{id}/info` | `GET` | Channel metadata |

Authorization uses the `Authorization: Bearer <token>` header. For `JWTChannelSecurity`, the transport calls `authorize_from_token()` before dispatching.

You normally do not attach `HttpTransport` manually — call `system.publish()` and it is attached automatically to every `PUBLIC` channel.

If you need manual control:

```python
from sssn.infra.server import ChannelServer
from sssn.core.transport import HttpTransport

server = ChannelServer(host="0.0.0.0", port=8000)
channel.attach_transport(HttpTransport(server=server))
await channel.start()
await server.start()
```

### ChannelServer

A thin wrapper around FastAPI + uvicorn:

```python
from sssn.infra.server import ChannelServer

server = ChannelServer(host="0.0.0.0", port=8000)
# server.app is the FastAPI instance — attach middleware, extra routes, etc.
await server.start()
```

---

## ChannelClient

`ChannelClient` is the consumer-side of the transport layer. Every `BaseSystem` has one at `self.client`. It abstracts over **local** (in-process) and **remote** (HTTP) channels with a single interface.

```python
from sssn.core.client import ChannelClient

client = ChannelClient(system_id="my-system")
```

### Connecting channels

**Local (in-process):**

```python
client.connect("channel-id", channel_object)
```

**Remote (HTTP):**

```python
client.connect_remote("channel-id", url="http://host:8000", token="Bearer ...")
```

**From config dict:**

```python
client.connect_from_config({
    "channel_id": "channel-id",
    "url": "http://host:8000",
    "token": "...",
})
```

### Calling channels

The API is identical regardless of whether the channel is local or remote:

```python
# Read
msgs = await client.read("channel-id", limit=20)
msgs = await client.read("channel-id", exclusive=True)

# Write
await client.write("channel-id", data={"key": "value"})
await client.write("channel-id", data=msg, direct=True)

# Acknowledge / nack
await client.acknowledge("channel-id", [msg.id])
await client.nack("channel-id", [msg.id])

# Subscribe (local only)
await client.subscribe("channel-id", callback)
await client.unsubscribe("channel-id")
```

!!! note "Remote subscribe"
    `subscribe()` is not supported for remote channels and raises `TypeError`. Use polling (`read()`) or set up a webhook on the remote end.

### HTTP internals

Remote calls use `httpx.AsyncClient` with the `Authorization: Bearer <token>` header. The `ChannelClient` serialises and deserialises `ChannelMessage` objects automatically.

---

## Request–response helper

`sssn.infra.helpers` provides a utility for the common request-response pattern over channels:

```python
from sssn.infra.helpers import request_via_channel

response = await request_via_channel(
    request_channel=request_ch,
    response_channel=response_ch,
    sender_id="requester",
    data={"query": "status"},
    timeout=30.0,
)
if response:
    print(response.content)
```

Internally this:

1. Generates a `correlation_id`.
2. Writes to `request_channel` with `direct=True` (pre-built `ChannelMessage`).
3. Polls `response_channel` for a message with matching `correlation_id`.
4. Returns the matched message or `None` on timeout.
