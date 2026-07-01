# HTTP Client

Serve a local store:

```bash
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```

Call it from Python:

```python
from sssn import SSSNClient

client = SSSNClient("http://127.0.0.1:7700")
channel = client.create_channel({"name": "events", "form": "log"})
event = client.append_event({"channel": channel.name, "payload": {"ok": True}})
same_event = client.get_event(event.id)
```

`AsyncSSSNClient` provides the same shape for async code:

```python
from sssn import AsyncSSSNClient

client = AsyncSSSNClient("http://127.0.0.1:7700")
channel = await client.create_channel({"name": "events"})
event = await client.append_event({"channel": channel.name, "payload": {"ok": True}})
```

## Portable Operations

The client mirrors the portable HTTP API:

- create/list/read channels,
- append/query/read events,
- create/read/pull subscriptions,
- write/read artifacts and artifact metadata,
- put/read snapshots.

Artifact writes accept `bytes`; HTTP clients base64-encode binary payloads so
they round-trip through JSON. Snapshot writes accept either a plain value with
metadata fields or a `Snapshot` model instance.

## Errors

HTTP clients raise `SSSNClientError` with:

- `status_code`,
- `error_type`,
- `message`,
- raw `detail`.

That lets worker loops distinguish missing resources, invalid input, and
conflicts without scraping server text.

## Subscriptions

```python
subscription = client.create_subscription(
    {"channel": "events", "id": "worker", "filters": {"kind": "message"}}
)
events = client.pull_subscription(subscription.id, limit=10)
```

If the subscription id already exists for the same channel, the server returns
the existing subscription so processors can keep stable cursors across
restarts. Reusing the id for another channel is a conflict.
