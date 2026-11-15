# Getting Started

This guide creates a local semantic channel store, appends an event, queries
it back, and exposes the same store over HTTP.

## Install

```bash
pip install sssn                    # models, stores, processor, CLI
pip install "sssn[server,client]"   # with the store server and clients
```

`sssn` depends on `lllm-core`; `pip install "lllm-core[network]"` installs the
same thing from the LLLM side. From a checkout:

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
sssn create-channel events --schema demo.Event
```

Append a semantic event:

```bash
sssn append events '{"text":"hello"}' --kind message --source demo
```

Query it back:

```bash
sssn query-events events
```

`--store DIR` picks the store folder and defaults to `.lllm/network`, so these
commands share one store. With LLLM installed, `lllm network` is the same
command: `lllm network query-events events` reads the same events.

The local store will create:

```text
.lllm/network/
  network.sqlite
  artifacts/
```

## Use Python

```python
from sssn import Channel, Event, LocalStore

store = LocalStore(".lllm/network")
store.create_channel(Channel(name="inbox", schema="demo.Event", form="log"))
event = store.append_event(
    Event(channel="inbox", source="demo", kind="message", payload={"text": "hello"})
)

print(event.cursor > 0)
print(store.query_events("inbox")[0].payload)
```

```text
True
{'text': 'hello'}
```

Events receive store cursors when the backend can provide them. Use the last
cursor you read as `after_cursor` to continue polling without rereading old
events.

## Serve A Store

```bash
sssn serve --host 127.0.0.1 --port 7700
```

Call it with the sync client:

```python
from sssn import RemoteStore

client = RemoteStore("http://127.0.0.1:7700")
channel = client.create_channel({"name": "remote-events", "form": "log"})
event = client.append_event({"channel": channel.name, "payload": {"ok": True}})
same_event = client.get_event(event.id)
```

Use `AsyncRemoteStore` for async workers and services. Both clients have the
`LocalStore` methods, so code written against a local store runs against a
served one.

## Continue

- [Channels](concepts/channels.md) explains the center resource.
- [Local Store](guides/local-store.md) covers cursor, artifact, and snapshot behavior.
- [HTTP Client](guides/http-client.md) covers remote calls and error envelopes.
- [Use with LLLM](guides/lllm.md) runs LLLM tactics over channels.
