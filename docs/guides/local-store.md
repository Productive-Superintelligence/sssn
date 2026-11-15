# Local Store

The local store creates a deterministic directory:

```text
.lllm/network/
  network.sqlite          # channels, events, subscriptions, artifact metadata, snapshots
  artifacts/
    cd98c5bce101ab55...   # artifact bytes, named by their SHA-256
```

```python
from sssn import LocalStore

store = LocalStore(".lllm/network")   # the folder is created if missing
```

`LocalStore()` with no argument uses `.lllm/network` relative to the working
directory, the same folder the `sssn` and `lllm network` commands use by
default. The store owns channel metadata, event cursors, subscription cursor
state, artifact metadata, artifact payload files, and snapshots. The examples
on this page run top to bottom as one session.

## Channels And Events

```python
from sssn import Channel, Event

store.create_channel(Channel(name="events", schema="demo.Event", form="log"))
first = store.append_event(
    Event(channel="events", source="demo", kind="raw", payload={"text": "hello"})
)
store.append_event({"channel": "events", "kind": "ping", "payload": {}})
store.append_event({"channel": "events", "kind": "raw", "payload": {"text": "again"}})

print([(event.cursor, event.kind) for event in store.query_events("events")])
print([event.cursor for event in store.query_events("events", kind="raw")])
print([event.cursor for event in store.query_events("events", after_cursor=first.cursor, limit=1)])
```

```text
[(1, 'raw'), (2, 'ping'), (3, 'raw')]
[1, 3]
[2]
```

`query_events(channel, *, after_cursor=0, limit=100, kind=None)` returns events
with a cursor greater than `after_cursor`, oldest first. Cursors must be
non-negative integers and limits greater than `0`; anything else raises
`InvalidPayloadError`. `get_event(event_id)` reads one event by id.

Cursors increase across the whole store, so inside one channel they are
ordered but can have gaps. Never compute `cursor + 1`; resume from the last
cursor you read:

```python
def read_all(store, channel, *, page=500):
    cursor = 0
    while batch := store.query_events(channel, after_cursor=cursor, limit=page):
        yield from batch
        cursor = batch[-1].cursor


print(sum(1 for _ in read_all(store, "events", page=2)))
```

```text
3
```

Event ids are unique in the store. Appending an event whose id is taken raises
`EventExistsError` (409 from the store server), so a producer that retries with
its own ids cannot write an event twice.

## Subscriptions

Subscriptions persist a consumer cursor over one channel:

```python
subscription = store.create_subscription(
    "events",
    subscription_id="worker",
    consumer="worker",
    batch_size=1,
    filters={"kind": "raw"},
)
print([event.payload["text"] for event in store.pull_subscription("worker")])
print(store.get_subscription("worker").cursor)
print([event.payload["text"] for event in store.pull_subscription("worker", limit=10)])
print(store.pull_subscription("worker"))
```

```text
['hello']
1
['again']
()
```

- `pull_subscription(id, *, limit=None)` returns up to `limit` (default: the
  subscription's `batch_size`) events after the stored cursor and moves the
  cursor past them in the same call. A pulled event is delivered once, whether
  or not the consumer finishes with it. `TacticProcessor` reads ahead with
  `query_events` instead and pulls an event only after writing its output; see
  [Use with LLLM](lllm.md#run-tactics-over-channels).
- `filters` supports one key, `kind`. Other keys raise `InvalidPayloadError`.
- Without `subscription_id`, the store generates a UUID. Name subscriptions you
  want to resume.
- `get_subscription(id)` reads the current state without moving the cursor.

Creating a subscription with an id that already exists on the same channel
returns the existing one unchanged, cursor and settings included, so
`create_subscription` is safe to call on every start:

```python
same = store.create_subscription("events", subscription_id="worker", batch_size=50)
print(same.cursor, same.batch_size)
```

```text
3 1
```

To change the filter or batch size, use a new id. Reusing an id on a different
channel raises `SubscriptionExistsError`.

## Artifacts

```python
artifact = store.write_artifact(
    b"hello",
    channel="events",
    media_type="text/plain",
    event_ids=[first.id],
    metadata={"source": "demo"},
)
metadata = store.get_artifact(artifact.id)
payload = store.read_artifact(artifact.id)
print(metadata.size, metadata.path == f"artifacts/{metadata.sha256}", payload)
```

```text
5 True b'hello'
```

Artifact writes can link payloads back to events. Local stores reject links to
missing events so larger payloads remain explainable. The same bytes written
twice produce two artifact records that share one file.

## Snapshots

```python
store.put_snapshot(
    "latest",
    {"status": "ok"},
    channel="events",
    source_event_id=first.id,
)
snapshot = store.get_snapshot("latest")
print(snapshot.value, snapshot.channel, snapshot.source_event_id == first.id)
```

```text
{'status': 'ok'} events True
```

Snapshots are latest-state materializations. They can include channel, schema,
metadata, and `source_event_id` fields. `put_snapshot` also takes a `Snapshot`
or a dict of snapshot fields, and every write replaces the whole snapshot:
fields you leave out are reset. See
[Events, Artifacts, Snapshots](../concepts/events-artifacts-snapshots.md#snapshots).

## Error Shape

Store methods raise stable `NetworkError` subclasses (a `NetworkError` is a
`RuntimeError`) for missing resources and invalid request values:

| Error | Raised when | Store server status |
| --- | --- | --- |
| `ChannelExistsError` | Creating a channel whose name is taken. | 409 |
| `EventExistsError` | Appending an event whose id is taken. | 409 |
| `SubscriptionExistsError` | Reusing a subscription id on a different channel. | 409 |
| `ChannelNotFoundError` | Using a channel that does not exist. | 404 |
| `EventNotFoundError` | Unknown event id, including dangling `parent_ids`, artifact `event_ids`, or snapshot `source_event_id`. | 404 |
| `SubscriptionNotFoundError` | Unknown subscription id. | 404 |
| `ArtifactNotFoundError` | Unknown artifact id, or its file is missing. | 404 |
| `SnapshotNotFoundError` | Unknown snapshot name. | 404 |
| `InvalidPayloadError` | Bad names, negative cursors, non-positive limits, unsupported filters, values that are not JSON serializable. | 400 |
| `ChannelRefError` | Malformed or unbound `lllm://` refs. Also a `ValueError`. | not served |

HTTP clients copy server errors into `RemoteStoreError` with status code, error
type, message, and raw detail; see [HTTP Client](http-client.md#errors).

## Notes

- An event's cursor is its SQLite `rowid`, which is why cursors are store-wide.
- JSON values are stored with sorted keys, so payload dicts read back with
  their keys in alphabetical order.
- Every call opens its own SQLite connection, so several processes can share a
  store folder, for example a store server and a local worker. SQLite
  serializes their writes.
- Delete the folder to start over.
