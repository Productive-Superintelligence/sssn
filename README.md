# SSSN

SSSN is the semantic data and communication plane for PSI services.

The center model is `Channel`: a named semantic data interface backed by a
store. The first backend is deliberately boring: SQLite for metadata and a
filesystem directory for artifacts.

## Local Store

```python
from sssn import Event, LocalStore

store = LocalStore(".sssn")
store.create_channel({"name": "events", "form": "log"})
event = store.append_event(
    Event(channel="events", source="demo", kind="raw", payload={"text": "hello"})
)

assert store.query_events("events")[0].id == event.id
```

Default layout:

```text
.sssn/
  sssn.sqlite
  artifacts/
```

## Resources

- `Channel`: named semantic data interface.
- `Event`: timestamped semantic record in a channel.
- `Subscription`: consumer cursor over one channel.
- `Artifact`: larger payload stored by reference.
- `Snapshot`: latest state or materialized view.

SSSN does not control services. It provides the data plane those services can
read from and write to.

## Serve The Store

```python
from sssn import LocalStore
from sssn.server import create_app

app = create_app(LocalStore(".sssn"))
```

Portable HTTP endpoints include:

- `POST /channels`, `GET /channels`, `GET /channels/{name}`
- `POST /events`, `GET /events?channel=...`
- `POST /subscriptions`, `POST /subscriptions/{id}/pull`
- `POST /artifacts`, `GET /artifacts/{id}`
- `PUT /snapshots/{name}`, `GET /snapshots/{name}`

## Call A Server

```python
from sssn import AsyncSSSNClient

client = AsyncSSSNClient("http://127.0.0.1:7700")
channel = await client.create_channel({"name": "events"})
event = await client.append_event({"channel": channel.name, "payload": {"ok": True}})
```

`SSSNClient` provides the same shape for synchronous code.

## Service-Style Processing

`examples/channel_processor` shows the intended service shape: a process pulls
events from one channel subscription and appends derived events to another
channel. The example is covered by the test suite so it stays executable.
