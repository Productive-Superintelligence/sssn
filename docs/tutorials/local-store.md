# Local Store

Goal: create a local store, inspect its layout, and use cursors.

```python
from sssn import Channel, LocalStore

store = LocalStore(".sssn")
store.create_channel(Channel(name="events"))
first = store.append_event({"channel": "events", "payload": {"n": 1}})
second = store.append_event({"channel": "events", "payload": {"n": 2}})

events = store.query_events("events", after_cursor=first.cursor)
assert events == (second,)
```

Expected local layout:

```text
.sssn/
  sssn.sqlite
  artifacts/
```

Next, serve the same store with the CLI or FastAPI app helper.
