# Refs and Packages

SSSN does not own `lllm.toml`, but it can export channel and snapshot metadata
for LLLM packages and the LLLM hub. Treat these helpers as manifest/card
adapters: SSSN describes the data resources, while LLLM's hub tooling owns
validation, publication, downloads, and generated cards. SSSN also resolves
the `lllm://` channel and snapshot refs a project binds in
`.lllm/config.toml`.

## Channel And Snapshot Resources

```python
from sssn import Channel, Snapshot, channel_resource, snapshot_resource

raw = channel_resource(
    Channel(
        name="raw",
        schema="raw_event",
        form="log",
        description="Incoming events.",
    )
)
latest = snapshot_resource(
    Snapshot(name="latest_analysis", channel="raw", schema="analysis_event"),
    description="Latest derived analysis event.",
)
print(raw)
print(latest)
```

```text
{'name': 'raw', 'schema': 'raw_event', 'form': 'log', 'description': 'Incoming events.', 'metadata': {}, 'endpoints': []}
{'name': 'latest_analysis', 'schema': 'analysis_event', 'channel': 'raw', 'description': 'Latest derived analysis event.', 'metadata': {}, 'endpoints': []}
```

Manifest shape in `lllm.toml`:

```toml
[channels.raw]
schema = "raw_event"
form = "log"
description = "Incoming events."

[snapshots.latest_analysis]
schema = "analysis_event"
channel = "raw"
description = "Latest derived analysis event."
```

The hub validates each channel's `form` against the forms SSSN can create (see
[Channels](../concepts/channels.md#channel-forms)).
`examples/hub_manifest/package_manifest.py` builds a whole manifest this way.

## Custom Endpoints

Custom endpoint decorators carry route metadata that can be copied into channel
or snapshot resource descriptions. The same decorated callable can also be
mounted on the FastAPI store service with `create_app(..., custom_endpoints=...)`.

```python
import json
from collections import deque

from sssn import Channel, channel_resource, endpoint


@endpoint.get(
    "/channels/{name}/tail",
    scope="channel",
    description="Return the most recent events for a channel.",
    tags=("channels",),
)
def channel_tail(store, name: str, params=None):
    tail = deque(maxlen=int((params or {}).get("limit", 20)))
    cursor = 0
    while batch := store.query_events(name, after_cursor=cursor, limit=500):
        tail.extend(batch)
        cursor = batch[-1].cursor
    return list(tail)


raw = channel_resource(
    Channel(name="raw", schema="raw_event", form="log"),
    custom_endpoints=[channel_tail],
)
print(json.dumps(raw, indent=2))
```

The exported resource includes the route in `endpoints`, which lets generated
package cards show domain routes beside the portable channel API:

```json
{
  "name": "raw",
  "schema": "raw_event",
  "form": "log",
  "description": "",
  "metadata": {},
  "endpoints": [
    {
      "name": "channel_tail",
      "method": "GET",
      "path": "/channels/{name}/tail",
      "scope": "channel",
      "description": "Return the most recent events for a channel.",
      "tags": [
        "channels"
      ]
    }
  ]
}
```

`create_app` binds handler parameters by name:

- a parameter named `store` receives the store,
- a parameter named `body` receives the parsed JSON body (`None` for `GET`,
  `DELETE`, or a body that is not JSON),
- any other parameter is filled from the path parameter of the same name,
- a parameter named `params` that is not a path parameter receives the query
  string as a dict of strings (for a repeated key, the last value wins),
- anything else keeps its default; a parameter without one fails every request
  with a 500 `TypeError`.

The decorators are `endpoint.get`, `.post`, `.put`, `.patch`, and `.delete`.
Their arguments are metadata: `name` (defaults to the function name), `scope`
(`store`, `channel`, `subscription`, `artifact`, or `snapshot`), `description`
(defaults to the docstring), and `tags`. Raise `NetworkError` subclasses from a
handler for 4xx responses.

## Resolve Shared Config

A channel ref names a channel by package, not by location:

```text
lllm://<org>/<package>/channels/<name>
lllm://<org>/<package>/snapshots/<name>
```

A project binds refs in `.lllm/config.toml`, the same file that binds LLLM
tactic refs. Each binding has exactly one target: a `store` folder, a `path`
folder, or the `url` of a served store.

```toml
[refs."lllm://demo/events/channels/raw"]
store = ".lllm/network"            # a LocalStore folder, relative to the project root

[refs."lllm://demo/events/channels/analysis"]
url = "http://127.0.0.1:7700"      # a served store
owner = "analysis"                 # extra keys are kept as binding metadata

[refs."lllm://demo/events/snapshots/latest"]
store = "archive"                  # names the [stores.archive] table below

[refs."lllm://demo/analyzer/tactics/analyze"]
url = "http://127.0.0.1:8000/tactics/analyze"

[stores.archive]
path = "data/events-store"         # relative to the project root
```

```python
from sssn import ChannelRef, ChannelResolver

resolver = ChannelResolver.from_config(".")
print(resolver.refs())

ref = ChannelRef("lllm://demo/events/channels/raw")
print(ref.org, ref.package, ref.resource_kind, ref.name)

analysis = resolver.resolve("lllm://demo/events/channels/analysis")
print(analysis.url, analysis.metadata)
print(type(resolver.local_store("lllm://demo/events/channels/raw")).__name__)
print(type(resolver.client("lllm://demo/events/channels/analysis")).__name__)
print(resolver.store_path("lllm://demo/events/snapshots/latest").relative_to(resolver.root))
```

```text
('lllm://demo/events/channels/analysis', 'lllm://demo/events/channels/raw', 'lllm://demo/events/snapshots/latest')
demo events channels raw
http://127.0.0.1:7700 {'owner': 'analysis'}
LocalStore
RemoteStore
data/events-store
```

The resolver loads only `/channels/` and `/snapshots/` refs. Tactic, service,
schema, docs, example, and asset refs stay in the same file for their owning
layers, such as `lllm.Resolver`. All binding keys must still be valid `lllm://`
resource refs: malformed SSSN and non-SSSN refs fail validation with
`ChannelRefError`, and so do unbound refs.

| Method | Returns |
| --- | --- |
| `ChannelResolver.from_config(path)` | A resolver for `path/.lllm/config.toml`, or for a config file path. Relative store paths resolve against the folder that contains `.lllm/`. The file must exist. |
| `ChannelResolver.from_text(text, *, root=None)` | A resolver for config text, parsed in memory. Relative store paths resolve against `root` (default: the working directory). Writes no files. |
| `ChannelResolver(root=".")` and `bind(ref, *, url=None, store=None, path=None, metadata=None)` | Bind refs in code. |
| `resolve(ref)` | A `ResolvedChannelRef`: `ref`, `resource_kind`, `name`, `url`, `store`, `path`, `metadata`. |
| `local_store(ref)`, `store_path(ref)` | A `LocalStore` (or its path) for `store`/`path` bindings. |
| `client(ref)`, `async_client(ref)` | A `RemoteStore` or `AsyncRemoteStore` for `url` bindings; both accept `timeout=` and `transport=`. |
| `refs()` | The bound refs, sorted. |
| `stores()`, `store(name)` | The `[stores.<name>]` tables. |

`path` is always a folder path. `store` is one too, unless it names a
`[stores.<name>]` table: then the binding uses that table's `path`
(`ChannelRefError` if the table has none). A ref resolves to a whole store;
the channel inside it is the ref's last segment. `lllm.Resolver` reads the same
file for tactic and channel refs alike; see
[Use with LLLM](lllm.md#channel-refs-in-lllmresolver).

## Verify

```bash
python -m pytest tests/test_resources.py tests/test_resolver.py tests/test_examples.py -q
```

Expected output:

```text
... passed
```

Next, publish and serve channel packages with the LLLM tooling in
[Use with LLLM](lllm.md#channel-packages).
