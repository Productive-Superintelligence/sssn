# Artifacts and snapshots

Events should stay small, because readers scan them and they cross HTTP as
JSON. Two other records hold what does not fit in an event. An **artifact**
holds bytes, such as a log, an image, or a report, stored beside the events
and linked to them by id. A **snapshot** holds the latest value of a name,
so a reader can get the current state in one call instead of replaying a
channel.

```python title="nightly.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "test-runs"})

run = store.append_event(  # (1)!
    {
        "channel": "test-runs",
        "kind": "finished",
        "correlation_id": "nightly-42",
        "payload": {"passed": 118, "failed": 2},
    }
)
log = store.write_artifact(  # (2)!
    b"FAILED test_export.py::test_csv\nFAILED test_auth.py::test_expiry\n",
    channel="test-runs",
    media_type="text/plain",
    metadata={"run": "nightly-42"},
    event_ids=[run.id],
)
store.put_snapshot(  # (3)!
    "nightly-status",
    {"run": "nightly-42", "failed": 2, "log": log.id},
    channel="test-runs",
    source_event_id=run.id,
)

status = store.get_snapshot("nightly-status")  # (4)!
info = store.get_artifact(status.value["log"])
print(info.media_type, info.size, info.event_ids == (run.id,))
#> text/plain 65 True
print(store.read_artifact(info.id).decode().splitlines()[0])
#> FAILED test_export.py::test_csv
```

1. The event is the fact: the run finished, with its counts.
2. The full log is bytes, so it goes in an artifact, linked to the event
   that produced it.
3. The snapshot is the current state that a dashboard reads. It points at
   the event behind its value and holds the artifact's id.
4. A reader starts from the snapshot. `get_artifact()` returns the record
   without the bytes, and `read_artifact()` returns the bytes.

## Writing artifacts

`write_artifact(data, *, channel=None, media_type=..., metadata=None,
event_ids=())` stores the bytes and returns an `Artifact`:

| Argument | Default | Meaning |
| --- | --- | --- |
| `data` | required | The content: `bytes`, `bytearray`, `memoryview`, or `str` |
| `channel` | `None` | The channel the artifact belongs to; it must exist |
| `media_type` | `"application/octet-stream"` | The content type, sent back when the artifact is downloaded over HTTP |
| `metadata` | `{}` | A JSON object that readers can see without the bytes |
| `event_ids` | `()` | The events it belongs to; they must exist |

The returned `Artifact` has these fields plus a random `id`, the `size` in
bytes, the `sha256` of the content, and the `path` of the file inside the
store folder. Artifacts never change: to replace one, write a new one and
point readers at it.

Text is stored as its UTF-8 bytes, so
`store.write_artifact(report, media_type="text/markdown")` stores a
Markdown report as it is. `read_artifact()` always returns bytes; decode
text with `.decode()`. Every store takes the same data: `RemoteStore` sends
bytes base64-encoded, so binary data arrives intact, and text as text
([Over HTTP](http.md)).

The store names each file by the SHA-256 of its content. The same bytes
written twice make two artifact records, each with its own id and metadata,
that share one file.

## Reading artifacts

| Method | Returns |
| --- | --- |
| `get_artifact(artifact_id)` | The `Artifact` record: size, media type, metadata, links |
| `read_artifact(artifact_id)` | The bytes |

Both raise `ArtifactNotFoundError` for an unknown id. Reading the record
first lets a reader check the size or the media type before downloading. A
served store answers `GET /artifacts/{id}` with the bytes and the stored
media type, so a browser can show an image directly, and
`GET /artifacts/{id}/metadata` with the record.

## Linking artifacts and events

A link can point either way. The example at the top writes the event first
and links the artifact to it with `event_ids`: the bytes point at the event
that produced them. To let readers of a channel find the bytes while they
read events, write the artifact first and put its id in the event:

```python title="frames.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "frames", "form": "artifact-index"})

for n, image in enumerate([b"\x89PNG frame-0", b"\x89PNG frame-1"]):
    frame = store.write_artifact(image, media_type="image/png")
    store.append_event(
        {
            "channel": "frames",
            "kind": "frame",
            "payload": {"n": n, "artifact": frame.id},
        }
    )

for event in store.query_events("frames"):
    data = store.read_artifact(event.payload["artifact"])
    print(event.payload["n"], data)
    #> 0 b'\x89PNG frame-0'
    #> 1 b'\x89PNG frame-1'
```

The `artifact-index` form tells readers that the channel's events describe
artifacts. The store does not look artifacts up by event or by channel, so
keep an artifact's id where its readers will look for it: in an event
payload or in a snapshot.

## Snapshots

`put_snapshot()` writes the value of a name, and `get_snapshot(name)` reads
it back. `put_snapshot()` accepts a snapshot in several forms:

```python title="plan.py"
from sssn import LocalStore, Snapshot

store = LocalStore(".lllm/network")
store.create_channel({"name": "plans"})
event = store.append_event({"channel": "plans", "payload": {"step": 3}})

store.put_snapshot(Snapshot(name="plan", value={"step": 1}))  # (1)!
store.put_snapshot({"name": "plan", "value": {"step": 2}})  # (2)!
store.put_snapshot(  # (3)!
    "plan", {"step": 3}, channel="plans", source_event_id=event.id
)

plan = store.get_snapshot("plan")
print(plan.value, plan.channel, plan.source_event_id == event.id)
#> {'step': 3} plans True

plan = store.put_snapshot("plan", {"step": 4})  # (4)!
print(plan.value, plan.channel, plan.source_event_id)
#> {'step': 4} None None
```

1. A `Snapshot` model.
2. A dict of the same fields.
3. A name and a value, with the other fields as keywords. `name=`,
   `value=`, and `snapshot=` (for a model or a dict) work as keywords too.
4. Each write replaces the whole snapshot. Fields you leave out are reset,
   as `channel` and `source_event_id` are here.

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | required | Unique in the store; see [Names](channels.md#names) |
| `value` | `None` | Any JSON value |
| `channel` | `None` | The channel the value summarizes; it must exist |
| `source_event_id` | `None` | The event the value came from; it must exist |
| `schema` | `None` | A ref to the value's schema |
| `metadata` | `{}` | A JSON object for small hints |
| `timestamp` | now | When the value was written |

The value is stored exactly as given, so
`put_snapshot("config", {"value": 3, "unit": "ms"})` stores the whole dict,
even though it has a `value` key. The one exception is a `Snapshot` passed
as the value: its fields are stored under the given name. Fields set to
`None` count as unset. `get_snapshot()` raises `SnapshotNotFoundError` for
a name that has never been written. `LocalStore`, `RemoteStore`, and
`AsyncRemoteStore` all take the same arguments.

Snapshots keep no history. When the history matters, append it to a channel
and point the snapshot at the latest event with `source_event_id`. Snapshot
names are unique in the whole store, not per channel, so name them for what
they describe, such as `orders-latest` or `robot-7-pose`.

## When to use which

| | Event | Artifact | Snapshot |
| --- | --- | --- | --- |
| Holds | a fact: something that happened | bytes | the current value of a name |
| Changes | never | never | replaced by every write |
| Readers find it | by reading the channel | by id | by name |
| History | the channel is the history | none | none; it points at an event |

Most systems use all three, as the example at the top of this page does:
append the event, write its bulk data as an artifact, and update a
snapshot that points at both. A worker that does this for every event is a
processor ([Processing with tactics](processing.md)).
