# Event Envelope

Goal: append an event with enough semantic context for downstream consumers.

## Prerequisites

```bash
python -m pip install -e ".[dev]"
```

## Files Used

- `sssn/core/models.py` defines the `Event` envelope fields.
- `sssn/stores/local.py` persists events, cursors, metadata, and parent links.
- `tests/test_local_store.py` keeps envelope behavior covered.

## Append A Context-Rich Event

```python
from sssn import Channel, LocalStore

store = LocalStore(".lllm/network")
store.create_channel(Channel(name="events", schema="demo.schemas:Event"))

event = store.append_event(
    {
        "channel": "events",
        "kind": "policy.sample",
        "payload": {"step_id": 1, "action": [0.1, 0.2]},
        "schema": "demo.schemas:Event",
        "source": "argus",
        "correlation_id": "episode-1",
        "metadata": {"split": "dev"},
    }
)
```

The payload is the domain data. The envelope fields around it make the event
usable by downstream workers: `kind` routes the event, `source` says who wrote
it, `correlation_id` groups a run or episode, and `metadata` carries small
queryable hints. The store fills in `id` (unless you set your own),
`timestamp`, and `cursor`.

## Link A Derived Event

```python
derived = store.append_event(
    {
        "channel": "events",
        "kind": "policy.score",
        "payload": {"step_id": 1, "score": 0.9},
        "source": "scorer",
        "correlation_id": event.correlation_id,
        "parent_ids": [event.id],
    }
)
```

`parent_ids` must name events that exist, in any channel. Event ids are unique:
appending an event with an id that is taken raises `EventExistsError`.

## Verify

```python
same = store.get_event(event.id)
assert same.correlation_id == "episode-1"
assert same.payload["step_id"] == 1
assert store.get_event(derived.parent_ids[0]).id == event.id
```

```bash
python -m pytest tests/test_local_store.py -q
```

Expected output:

```text
... passed
```

Next, add a subscription that consumes only the event kinds a worker needs.
