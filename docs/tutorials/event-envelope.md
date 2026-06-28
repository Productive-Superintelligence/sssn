# Event Envelope

Goal: append an event with enough semantic context for downstream consumers.

```python
from sssn import Channel, LocalStore

store = LocalStore(".sssn")
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

Verify:

```python
same = store.get_event(event.id)
assert same.correlation_id == "episode-1"
assert same.payload["step_id"] == 1
```

Next, add a subscription that consumes only the event kinds a worker needs.
