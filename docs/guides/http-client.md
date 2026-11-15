# HTTP Client

Serve a local store:

```bash
sssn serve --host 127.0.0.1 --port 7700
```

`--store` defaults to `.lllm/network` and `--port` to `7700`. The FastAPI app
is also available in Python as `create_app(store)`; the server has no
authentication, so keep it on localhost or behind a gateway that handles access
control.

Call it from Python:

```python
from sssn import RemoteStore

client = RemoteStore("http://127.0.0.1:7700")
channel = client.create_channel({"name": "events", "form": "log"})
event = client.append_event({"channel": channel.name, "payload": {"ok": True}})
same_event = client.get_event(event.id)
```

`AsyncRemoteStore` provides the same shape for async code:

```python
from sssn import AsyncRemoteStore

client = AsyncRemoteStore("http://127.0.0.1:7700")
channel = await client.create_channel({"name": "events"})
event = await client.append_event({"channel": channel.name, "payload": {"ok": True}})
```

Both take `base_url`, `timeout=30.0`, and an optional httpx `transport`. Each
call opens its own short-lived HTTP connection.

## Portable Operations

The client mirrors the portable HTTP API:

- create/list/read channels,
- append/query/read events,
- create/read/pull subscriptions,
- write/read artifacts and artifact metadata,
- put/read snapshots.

The clients have the `LocalStore` methods, with these differences:

| Method | `LocalStore` | `RemoteStore` / `AsyncRemoteStore` |
| --- | --- | --- |
| `write_artifact` | `bytes`, `bytearray`, or `memoryview` | `bytes` (sent base64-encoded) or `str` (sent as UTF-8 text) |
| errors | `NetworkError` subclasses | `RemoteStoreError` for server errors. Names and ids are checked before sending and raise `InvalidPayloadError`. |

`put_snapshot` has the same signature on every store:
`put_snapshot(snapshot=None, value=None, *, name=None, channel=None, timestamp=None, schema=None, source_event_id=None, metadata=None)`.
Pass a `Snapshot` or a dict of snapshot fields, or a name and a value. The
value is stored exactly as given, so `put_snapshot("config", {"value": 3, "unit": "ms"})`
stores the whole dict.

## Errors

HTTP clients raise `RemoteStoreError` with:

- `status_code`,
- `error_type`,
- `message`,
- raw `detail`.

That lets worker loops distinguish missing resources, invalid input, and
conflicts without scraping server text. `RemoteStoreError` is a
`RuntimeError`, not a `NetworkError`; branch on `error_type` (for example
`"SubscriptionNotFoundError"`) or `status_code`:

| Status | When |
| --- | --- |
| 400 | `InvalidPayloadError`, other `NetworkError`s, and request bodies that fail validation (reported as `InvalidPayloadError`). |
| 404 | `ChannelNotFoundError`, `EventNotFoundError`, `SubscriptionNotFoundError`, `ArtifactNotFoundError`, `SnapshotNotFoundError`. |
| 409 | `ChannelExistsError`, `EventExistsError` (an event id that is taken), `SubscriptionExistsError`. |
| 500 | Anything else, with the exception's class name and message. |

## Subscriptions

```python
subscription = client.create_subscription(
    "events", subscription_id="worker", filters={"kind": "message"}
)
events = client.pull_subscription(subscription.id, limit=10)
```

If the subscription id already exists for the same channel, the server returns
the existing subscription so processors can keep stable cursors across
restarts. Reusing the id for another channel is a conflict (409
`SubscriptionExistsError`).

## Test Without A Server

Pass `httpx.ASGITransport` to call an app in-process, which is the easiest way
to test code that uses a remote store:

```python
import asyncio

import httpx

from sssn import AsyncRemoteStore, LocalStore, create_app


async def main():
    app = create_app(LocalStore("test-store"))
    store = AsyncRemoteStore("http://test", transport=httpx.ASGITransport(app=app))
    await store.create_channel({"name": "inbox"})
    await store.append_event({"channel": "inbox", "payload": {"text": "hi"}})
    return [event.payload for event in await store.query_events("inbox")]


print(asyncio.run(main()))
```

```text
[{'text': 'hi'}]
```
