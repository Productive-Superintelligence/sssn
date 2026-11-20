# Simple System of Systems Network (SSSN)

<p align="center">
  <img src="assets/sssn-logo-text-dark.png" alt="SSSN" width="420">
</p>

Simple System of Systems Network (SSSN) is the protocol and service layer for
semantic channels, built on [LLLM](https://lllm.one/). Documentation:
[sssn.one](https://sssn.one/).

The center model is `Channel`: a named semantic data interface. Stores,
brokers, databases, feeds, object stores, graph stores, and local filesystems
are backing implementations under that stable protocol. The first backend is
deliberately boring: SQLite for metadata and a filesystem directory for
artifacts.

SSSN is LLLM-centric. It depends on `lllm-core` for tactics, refs, and package
manifests and runs any LLLM tactic over a channel with `TacticProcessor`;
installing it adds `lllm network` to the `lllm` command.

```bash
pip install sssn                    # or: pip install "lllm-core[network]"
pip install "sssn[server,client]"   # with the store server and clients
```

## Local Store

```python
from sssn import Event, LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "events", "form": "log"})
event = store.append_event(
    Event(channel="events", source="demo", kind="raw", payload={"text": "hello"})
)

assert store.query_events("events")[0].id == event.id
```

Default layout, shared by `LocalStore()`, `sssn`, and `lllm network`:

```text
.lllm/network/
  network.sqlite
  artifacts/
```

## Resources

- `Channel`: named semantic data interface.
- `Event`: timestamped semantic record in a channel.
- `Subscription`: consumer cursor over one channel.
- `Artifact`: larger payload stored by reference.
- `Snapshot`: latest state or materialized view.

SSSN does not control services. It provides the channel protocol those services
can read from and write to.

## Run LLLM Tactics Over Channels

`TacticProcessor` reads a channel through a named subscription, runs each event
payload through an LLLM tactic, and appends the output to a sink channel with
the input event as its parent:

```python
from lllm import as_tactic
from sssn import TacticProcessor


def triage(ticket: dict) -> dict:
    return {"priority": "urgent" if "down" in ticket["text"] else "normal"}


store.create_channel({"name": "triaged"})
processor = TacticProcessor(as_tactic(triage), store, source="events", sink="triaged")
for result in processor.process():
    print(result.payload, result.parent_ids == (event.id,))
```

Processing is at least once: an event is acknowledged only after its output is
written, so an event cut short by an error or a crash runs again. The
subscription lives in the store, so a restarted processor resumes where it
stopped. `examples/lllm_tactic_processor/workflow.py` runs this path without
external services or provider keys.

## Errors And Cursors

Store methods raise stable `NetworkError` subclasses for missing resources and
invalid request values; appending an event whose id is taken raises
`EventExistsError`. `after_cursor` starts at `0`, cursors must be non-negative
integers, and subscription/query limits must be greater than `0`. Returned
events include `cursor`; pass the last one back as `after_cursor` to continue a
query. Cursors are store-wide, so a channel's cursors are ordered but have
gaps. Local stores reject event `parent_ids` that do not point at existing
events. Subscription filters support only `{"kind": "..."}`; unsupported
filter keys are rejected instead of being ignored.

HTTP clients raise `RemoteStoreError` with `status_code`, `error_type`,
`message`, and raw `detail` fields copied from the server error envelope. It is
a `NetworkError`, and for a store error it is also an instance of that error's
class, so `except ChannelNotFoundError` works on local and remote stores.

## LLLM Packages And Refs

SSSN does not own `lllm.toml`, but it exports channel and snapshot metadata for
LLLM packages and the LLLM hub:

```python
from sssn import Channel, Snapshot, channel_resource, snapshot_resource

resource = channel_resource(Channel(name="events", schema="demo.schemas:Event"))
latest = snapshot_resource(
    Snapshot(name="latest", channel="events", schema="demo.schemas:Event"),
    description="Latest event state.",
)
```

Custom SSSN endpoint decorators can be included so generated package cards show
domain routes alongside the portable channel API. Use `@endpoint.get`,
`@endpoint.post`, `@endpoint.put`, `@endpoint.patch`, or `@endpoint.delete`
with `scope="channel"` on channel-specific routes and `scope="snapshot"` on
latest-state routes so package cards can group them correctly.
`examples/hub_manifest` builds the channel and snapshot sections of an
`lllm.toml` manifest this way, and `sssn.resources.open_package_store` opens a
package's store (`<package>/.lllm/network`) with its declared channels, which
is what `lllm serve PACKAGE --resource channels.NAME` serves.

Projects bind `lllm://` refs in `.lllm/config.toml`:

```toml
[refs."lllm://demo/events/channels/raw"]
store = ".lllm/network"

[refs."lllm://demo/events/snapshots/latest"]
store = "archive"

[stores.archive]
path = "data/events-store"
```

```python
from sssn import ChannelResolver

resolver = ChannelResolver.from_config(".")
store = resolver.local_store("lllm://demo/events/channels/raw")
```

`ChannelResolver` ignores refs owned by other layers, such as LLLM tactics and
services, so one local config file can bind a composed workspace.
`lllm.Resolver` reads the same file and returns SSSN stores for channel and
snapshot refs.

## Serve The Store

For a step-by-step local store walkthrough, see
`docs/tutorials/first-channel.md`.

```python
from sssn import LocalStore, create_app

app = create_app(LocalStore(".lllm/network"))
```

Portable HTTP endpoints include:

- `POST /channels`, `GET /channels`, `GET /channels/{name}`
- `POST /events`, `GET /events?channel=...`, `GET /events/{id}`
- `POST /subscriptions`, `GET /subscriptions/{id}`, `POST /subscriptions/{id}/pull`
- `POST /artifacts`, `GET /artifacts/{id}`, `GET /artifacts/{id}/metadata`
- `PUT /snapshots/{name}`, `GET /snapshots/{name}`

Custom endpoints can be mounted alongside the portable API:

```python
from sssn import LocalStore, create_app, endpoint


@endpoint.get("/channels/{name}/count")
def count_events(store, name: str):
    return {"count": len(store.query_events(name))}


app = create_app(LocalStore(".lllm/network"), custom_endpoints=[count_events])
```

## Call A Server

```python
from sssn import AsyncRemoteStore

client = AsyncRemoteStore("http://127.0.0.1:7700")
channel = await client.create_channel({"name": "events"})
event = await client.append_event({"channel": channel.name, "payload": {"ok": True}})
same_event = await client.get_event(event.id)
```

`RemoteStore` provides the same shape for synchronous code; both have the
`LocalStore` methods. Subscription creation accepts an optional
`subscription_id`; if that id already exists, the existing subscription is
returned so processors can keep a stable cursor across restarts. Reusing an id
for a different channel returns a stable conflict error. Every store's
`write_artifact()` takes `bytes`, `bytearray`, `memoryview`, or `str` (stored
as UTF-8); HTTP clients send bytes as base64 so binary payloads round-trip
through the portable API. Artifact writes also accept
`metadata` and `event_ids` so larger payloads can stay linked to the events
that introduced them; local stores reject links to missing events. Artifact
downloads use the stored `media_type`; use `get_artifact()` to inspect artifact
metadata without downloading the payload. `put_snapshot` takes a `Snapshot`, a
dict of snapshot fields, or a name and a value with `channel`, `schema`,
`source_event_id`, and `metadata` keywords, on every store.

## CLI

The CLI runs as `sssn` and as `lllm network`; `--store` defaults to
`.lllm/network`.

```bash
sssn create-channel events --schema demo.Event --metadata '{"owner":"demo"}'
sssn get-channel events
sssn append events '{"text":"hello"}'
sssn append events '{"text":"child"}' --schema demo.Event --metadata '{"role":"child"}' --correlation-id corr-1 --parent-id <event-id>
sssn query-events events --limit 10
sssn get-event <event-id>
sssn create-subscription events --id worker --kind event
sssn pull-subscription worker --limit 10
sssn get-subscription worker
sssn write-artifact 'hello' --media-type text/plain
sssn get-artifact <artifact-id>
sssn read-artifact <artifact-id>
sssn put-snapshot latest '{"status":"ok"}'
sssn get-snapshot latest
sssn channels
sssn serve --host 127.0.0.1 --port 7700
lllm network channels        # the same command through lllm
```

## Service-Style Processing

`examples/channel_processor` shows the intended service shape: a process pulls
events from one channel subscription and appends derived events to another
channel. The example is covered by the test suite so it stays executable.

## Artifact And Snapshot Example

`examples/artifact_snapshot` shows the local-store shape for larger payloads and
latest-state materialization: append an event, write an event-linked artifact,
then update a `latest` snapshot.

## Upgrading

SSSN 0.2 is the code LLLM 0.3 shipped as its network module, back in its own
package and built on `lllm-core`. `CHANGELOG.md` lists what changed from SSSN
0.1: the default store folder, `lllm://` refs in `.lllm/config.toml`, and the
renamed classes.
