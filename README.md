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

## Errors And Cursors

Store methods raise stable `SSSNError` subclasses for missing resources and
invalid request values. `after_cursor` starts at `0`, cursors must be
non-negative integers, and subscription/query limits must be greater than `0`.
Returned events include `cursor` when the backing store can provide one; pass
that value back as `after_cursor` to continue a query.
Subscription filters currently support `{"kind": "..."}` for event-kind
specific consumer loops. HTTP clients can call `get_subscription()` to inspect
persisted cursor state.

HTTP clients raise `SSSNClientError` with `status_code`, `error_type`,
`message`, and raw `detail` fields copied from the server error envelope.

## Package Metadata Helpers

SSSN does not own `psi.toml`, but it can export channel metadata for PsiHub:

```python
from sssn import Channel, channel_resource

resource = channel_resource(Channel(name="events", schema="demo.schemas:Event"))
```

Custom SSSN endpoint decorators can be included so generated package cards show
domain routes alongside the portable channel API. Use `scope="channel"` on
channel-specific routes so package cards can group them correctly.

`examples/psihub_manifest` shows how to turn channel resources into a
PsiHub-style manifest section:

```python
from sssn import Channel, channel_resource

raw = channel_resource(
    Channel(
        name="raw",
        schema="raw_event",
        form="log",
        description="Incoming events.",
    )
)

manifest = {
    "package": {"org": "demo", "name": "events", "kind": "channel"},
    "channels": {raw["name"]: {k: v for k, v in raw.items() if k != "name"}},
}
```

## Serve The Store

```python
from sssn import LocalStore
from sssn.server import create_app

app = create_app(LocalStore(".sssn"))
```

Portable HTTP endpoints include:

- `POST /channels`, `GET /channels`, `GET /channels/{name}`
- `POST /events`, `GET /events?channel=...`
- `POST /subscriptions`, `GET /subscriptions/{id}`, `POST /subscriptions/{id}/pull`
- `POST /artifacts`, `GET /artifacts/{id}`, `GET /artifacts/{id}/metadata`
- `PUT /snapshots/{name}`, `GET /snapshots/{name}`

Custom endpoints can be mounted alongside the portable API:

```python
from sssn.server import create_app, endpoint

@endpoint.get("/channels/{name}/count")
def count_events(store, name: str):
    return {"count": len(store.query_events(name))}

app = create_app(LocalStore(".sssn"), custom_endpoints=[count_events])
```

## Call A Server

```python
from sssn import AsyncSSSNClient

client = AsyncSSSNClient("http://127.0.0.1:7700")
channel = await client.create_channel({"name": "events"})
event = await client.append_event({"channel": channel.name, "payload": {"ok": True}})
```

`SSSNClient` provides the same shape for synchronous code.
Subscription creation accepts an optional `subscription_id`; if that id already
exists, the existing subscription is returned so processors can keep a stable
cursor across restarts. Reusing an id for a different channel returns a stable
conflict error.
When `write_artifact()` receives `bytes`, HTTP clients send base64 so binary
payloads round-trip through the portable API. Artifact writes also accept
`metadata` and `event_ids` so larger payloads can stay linked to the events
that introduced them. Artifact downloads use the stored `media_type`; use
`get_artifact()` to inspect artifact metadata without downloading the payload.
Snapshot writes accept a plain value plus optional
`channel`, `schema`, `source_event_id`, and `metadata` fields, or a `Snapshot`
model instance.

## CLI

```bash
sssn --store .sssn create-channel events
sssn --store .sssn append events '{"text":"hello"}'
sssn --store .sssn channels
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```

## Service-Style Processing

`examples/channel_processor` shows the intended service shape: a process pulls
events from one channel subscription and appends derived events to another
channel. The example is covered by the test suite so it stays executable.

## Artifact And Snapshot Example

`examples/artifact_snapshot` shows the local-store shape for larger payloads and
latest-state materialization: append an event, write an event-linked artifact,
then update a `latest` snapshot.
