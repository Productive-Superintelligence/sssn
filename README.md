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
