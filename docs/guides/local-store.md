# Local Store

The local store creates a deterministic directory:

```text
.sssn/
  sssn.sqlite
  artifacts/
```

```python
from sssn import LocalStore

store = LocalStore(".sssn")
```

The store owns channel metadata, event cursors, subscription cursor state,
artifact metadata, artifact payload files, and snapshots.

## Channels And Events

```python
from sssn import Channel, Event

store.create_channel(Channel(name="events", schema="demo.Event", form="log"))
event = store.append_event(
    Event(channel="events", source="demo", kind="raw", payload={"text": "hello"})
)
events = store.query_events("events", after_cursor=0, limit=10)
```

`after_cursor` starts at `0`, cursors must be non-negative integers, and limits
must be greater than `0`. Returned events include `cursor` when the backend can
provide one.

## Subscriptions

Subscriptions persist a consumer cursor over one channel:

```python
subscription = store.create_subscription(
    "events",
    subscription_id="worker",
    filters={"kind": "raw"},
)
batch = store.pull_subscription(subscription.id, limit=10)
```

Creating the same subscription id for the same channel returns the existing
subscription. Reusing an id for a different channel returns a stable conflict
error. Filters currently support event-kind-specific loops.

## Artifacts

```python
artifact = store.write_artifact(
    b"hello",
    media_type="text/plain",
    event_ids=[event.id],
    metadata={"source": "demo"},
)
metadata = store.get_artifact(artifact.id)
payload = store.read_artifact(artifact.id)
```

Artifact writes can link payloads back to events. Local stores reject links to
missing events so larger payloads remain explainable.

## Snapshots

```python
store.put_snapshot(
    "latest",
    {"status": "ok"},
    channel="events",
    source_event_id=event.id,
)
snapshot = store.get_snapshot("latest")
```

Snapshots are latest-state materializations. They can include channel, schema,
metadata, and `source_event_id` fields.

## Error Shape

Store methods raise stable `SSSNError` subclasses for missing resources and
invalid request values. HTTP clients copy those server errors into
`SSSNClientError` with status code, error type, message, and raw detail.
