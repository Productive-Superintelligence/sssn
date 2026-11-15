# Local Store

Goal: create a local store, inspect its layout, and use cursors.

## Prerequisites

```bash
python -m pip install -e ".[dev]"
```

## Files Used

- `sssn/stores/local.py` owns the SQLite metadata database and artifact
  directory layout.
- `tests/test_local_store.py` covers channel creation, event cursors,
  subscriptions, artifacts, and snapshots.

## Create Events

```python
from sssn import Channel, LocalStore

store = LocalStore(".lllm/network")
store.create_channel(Channel(name="events"))
first = store.append_event({"channel": "events", "payload": {"n": 1}})
second = store.append_event({"channel": "events", "payload": {"n": 2}})

events = store.query_events("events", after_cursor=first.cursor)
assert events == (second,)
print(tuple(event.payload for event in events))
```

Expected output:

```text
({'n': 2},)
```

Cursors increase across the whole store, so resume from the last cursor you
read instead of computing `cursor + 1`.

## Inspect The Layout

```text
.lllm/network/
  network.sqlite
  artifacts/
```

`LocalStore()` with no argument, `sssn`, and `lllm network` all default to
this folder.

## Verify

```bash
python -m pytest tests/test_local_store.py -q
```

Expected output:

```text
... passed
```

Next, serve the same store with the CLI or the FastAPI app helper.
