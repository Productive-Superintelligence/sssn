# First Channel

Goal: build the smallest local SSSN channel, append an event, and read it back.

The same flow is available as an executable example at
`examples/first_channel/workflow.py`.

## Prerequisites

```bash
python -m pip install -e ".[dev]"
```

## Files Used

- `examples/first_channel/workflow.py` contains the runnable version of this
  flow.
- `tests/test_examples.py` keeps the example executable.
- `sssn/stores/local.py` provides the local SQLite/filesystem store.

## Create A Store

```python
from sssn import Channel, LocalStore

store = LocalStore(".lllm/network")
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
from sssn import Channel, ChannelExistsError, LocalStore

store = LocalStore(".lllm/network")
try:
    store.create_channel(Channel(name="events", schema="demo.schemas:Event"))
except ChannelExistsError:
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

Next, serve the same store with `sssn serve` (or `lllm network serve`), or
mount it in your own app with `sssn.create_app`.
