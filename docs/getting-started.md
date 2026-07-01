# Getting Started

This guide creates a local semantic channel store, appends an event, queries
it back, and exposes the same store over HTTP.

## Install

```bash
python -m pip install -e ".[dev,server]"
```

For documentation work:

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```

Run the package tests before changing protocol or service behavior:

```bash
python -m pytest
```

## Create A Channel

```bash
sssn --store .sssn create-channel events --schema demo.Event
```

Append a semantic event:

```bash
sssn --store .sssn append events '{"text":"hello"}' --kind message --source demo
```

Query it back:

```bash
sssn --store .sssn query-events events
```

The local store will create:

```text
.sssn/
  sssn.sqlite
  artifacts/
```

## Use Python

```python
from sssn import Channel, Event, LocalStore

store = LocalStore(".sssn")
store.create_channel(Channel(name="events", schema="demo.Event", form="log"))
event = store.append_event(
    Event(channel="events", source="demo", kind="message", payload={"text": "hello"})
)

print(event.id)
print(store.query_events("events")[0].payload)
```

Events receive store cursors when the backend can provide them. Use the
returned cursor as `after_cursor` to continue polling without rereading old
events.

## Serve A Store

```bash
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```

Call it with the sync client:

```python
from sssn import SSSNClient

client = SSSNClient("http://127.0.0.1:7700")
channel = client.create_channel({"name": "remote-events", "form": "log"})
event = client.append_event({"channel": channel.name, "payload": {"ok": True}})
same_event = client.get_event(event.id)
```

Use `AsyncSSSNClient` for async workers and services.

## Continue

- [Channels](concepts/channels.md) explains the center resource.
- [Local Store](guides/local-store.md) covers cursor, artifact, and snapshot behavior.
- [HTTP Client](guides/http-client.md) covers remote calls and error envelopes.
