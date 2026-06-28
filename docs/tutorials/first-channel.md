# First Channel

Build the smallest local SSSN channel, append an event, and read it back.

## Prerequisites

```bash
python -m pip install -e ".[dev]"
```

## Create A Store

```python
from sssn import Channel, LocalStore

store = LocalStore(".sssn")
store.create_channel(
    Channel(
        name="events",
        schema="demo.schemas:Event",
        form="log",
        description="Local event stream.",
    )
)
```

## Append An Event

```python
event = store.append_event(
    {
        "channel": "events",
        "kind": "message",
        "payload": {"text": "hello"},
        "schema": "demo.schemas:Event",
        "source": "tutorial",
    }
)
```

## Read Events

```python
events = store.query_events("events", after_cursor=0)
assert events[0].id == event.id
assert events[0].payload == {"text": "hello"}
```

## Verify

```bash
python - <<'PY'
from sssn import Channel, LocalStore

store = LocalStore(".sssn")
try:
    store.create_channel(Channel(name="events", schema="demo.schemas:Event"))
except Exception:
    pass
event = store.append_event(
    {"channel": "events", "kind": "message", "payload": {"text": "hello"}}
)
print(store.query_events("events")[-1].payload)
PY
```

Expected output:

```text
{'text': 'hello'}
```

Next, serve the same store with `sssn.server.create_app` or the `sssn` CLI.
