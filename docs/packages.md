# Packages and refs

An LLLM package can declare channels and snapshots in its `lllm.toml`, next
to its tactics, and the [LLLM Hub](https://lllm.one/publishing/) lists them.
The manifest says which channels exist. Which store holds their events is
decided on each machine, in `.lllm/config.toml`, where each channel's
`lllm://` ref is bound to a store folder or to a served store's URL. Code
names a channel by its ref, so it keeps working when the store moves.

```python title="open_package.py"
from pathlib import Path

from lllm.hub import load_manifest
from sssn.resources import open_package_store

Path("support-desk").mkdir()
Path("support-desk/lllm.toml").write_text(
    """
[package]
org = "demo"
name = "support-desk"
version = "0.1.0"
kind = "channel"
primary = "channels.inbox"

[channels.inbox]
description = "Support messages as they arrive."
metadata = {port = 7700}

[channels.triaged]
description = "One triage result per message."

[snapshots.queue-depth]
channel = "triaged"
description = "Open tickets per priority."
"""
)

manifest = load_manifest("support-desk")  # (1)!
print(manifest.ref("channel", "inbox"))  # (2)!
#> lllm://demo/support-desk/channels/inbox
store = open_package_store(manifest)  # (3)!
print(store.root.relative_to(Path.cwd()))
#> support-desk/.lllm/network
print([channel.name for channel in store.list_channels()])
#> ['inbox', 'triaged']
```

1. `load_manifest` is LLLM's manifest reader. It rejects a channel whose
   `form` is not one SSSN can create.
2. Every declared channel and snapshot gets a ref from the package's `org`
   and `name`.
3. `open_package_store` opens the package's store, `.lllm/network` inside
   the package folder, and creates each declared channel that does not
   exist yet.

The same store, served over HTTP on the port the manifest declares:

```bash
lllm serve support-desk --resource channels.inbox
```

## Declare channels and snapshots

Each `[channels.NAME]` table declares one channel, and each
`[snapshots.NAME]` table one snapshot:

| Field | Applies to | Meaning |
| --- | --- | --- |
| `form` | channels | One of the [channel forms](channels.md); `"log"` by default |
| `channel` | snapshots | The channel the snapshot summarizes; it must be declared too |
| `schema` | both | The event or value shape: a `[schemas.NAME]` entry, a built-in such as `object`, or a `module:Model` import |
| `description` | both | One line for the hub card |
| `metadata` | both | Free-form; on a channel, `port` sets the port `lllm serve` uses |
| `endpoints` | both | Custom route metadata for the hub card ([Custom endpoints](http.md#custom-endpoints)) |

`channel_resource(channel, *, custom_endpoints=())` and
`snapshot_resource(snapshot, *, description="", custom_endpoints=())` build
these tables from `Channel` and `Snapshot` objects, so a manifest can be
generated from the channels your code creates:

```python title="resources.py"
from sssn import Channel, Snapshot, channel_resource, snapshot_resource

inbox = Channel(
    name="inbox", description="Support messages as they arrive."
)
print(channel_resource(inbox))
"""
{
    'name': 'inbox',
    'schema': None,
    'form': 'log',
    'description': 'Support messages as they arrive.',
    'metadata': {},
    'endpoints': [],
}
"""
depth = Snapshot(name="queue-depth", channel="triaged")
print(snapshot_resource(depth, description="Open tickets per priority."))
"""
{
    'name': 'queue-depth',
    'schema': None,
    'channel': 'triaged',
    'description': 'Open tickets per priority.',
    'metadata': {},
    'endpoints': [],
}
"""
```

`name` is the table's name, so leave it out of the table, along with
`None` values, which TOML cannot hold. With `custom_endpoints=[...]`,
`endpoints` lists each decorated route. The repository's
[hub manifest example](https://github.com/Productive-Superintelligence/sssn/tree/main/examples/hub_manifest)
builds a whole manifest this way.

`open_package_store(manifest, *, store=None)` takes another folder as
`store`, relative to the working directory. It creates only missing
channels: a channel that is already in the store keeps its form,
description, and metadata even if the manifest changes.

## Serve a package's channels

`lllm serve` serves a channel resource with SSSN's `create_app` and
`open_package_store`:

```bash
lllm serve support-desk --resource channels.inbox
lllm serve support-desk --resource channels.inbox --store data/desk
lllm serve support-desk                     # primary = "channels.inbox"
```

- The app serves the whole store, with every channel in it, not only the
  one named; the routes are those in [Over HTTP](http.md#routes).
- The port is `--port`, else the channel's `metadata.port`, else 8000.
- `--store DIR` serves another folder, relative to the working directory.
- Before it starts, `lllm serve` checks the API keys the package declares
  ([API keys](https://lllm.one/packages/#api-keys)); `--skip-key-check`
  skips the check.

A channel resource serves the standard routes only. To serve a package's
store with [custom endpoints](http.md#custom-endpoints), declare a service
whose entry builds the app, and serve it with
`lllm serve support-desk --resource services.store`:

```toml title="support-desk/lllm.toml"
[services.store]
entry = "store_app:build_app"
description = "The package store with its custom endpoints."
metadata = {port = 7701}
```

```python title="support-desk/store_app.py" test="skip" reason="runs inside the package folder"
from pathlib import Path

from lllm.hub import load_manifest
from sssn import create_app
from sssn.resources import open_package_store

from endpoints import channel_tail  # a module in the package


def build_app():
    store = open_package_store(load_manifest(Path(__file__).parent))
    return create_app(store, custom_endpoints=[channel_tail])
```

To serve a package's tactics and channels together as one API, mount the
package in an [AAAX](https://aaax.one/) strategy.

## Refs

A channel ref names a channel by package, not by location:

```text
lllm://ORG/PACKAGE/channels/NAME
lllm://ORG/PACKAGE/snapshots/NAME
```

`ChannelRef(value)` parses one into `org`, `package`, `resource_kind`, and
`name`, and raises `ChannelRefError` for anything else, such as a tactic
ref. `ChannelRefError` is a `NetworkError` and a `ValueError`. A ref
resolves to a whole store; the channel inside it is the ref's last segment.

## Bind refs to stores

A project binds refs in `.lllm/config.toml`, the same file where LLLM binds
tactic refs ([Local configuration](https://lllm.one/packages/#local-configuration)).
`ChannelResolver` reads the channel and snapshot bindings:

```python title="channel_refs.py"
from pathlib import Path

from sssn import ChannelRef, ChannelResolver

INBOX = "lllm://demo/support-desk/channels/inbox"
RAW = "lllm://demo/events/channels/raw"
DEPTH = "lllm://demo/support-desk/snapshots/queue-depth"

Path(".lllm").mkdir()
Path(".lllm/config.toml").write_text(
    f"""
[refs."{INBOX}"]
store = ".lllm/network"

[refs."{RAW}"]
url = "http://127.0.0.1:7700"
owner = "data-team"

[refs."{DEPTH}"]
store = "archive"

[stores.archive]
path = "data/archive"
"""
)

resolver = ChannelResolver.from_config(".")  # (1)!
print(resolver.refs())
"""
(
    'lllm://demo/events/channels/raw',
    'lllm://demo/support-desk/channels/inbox',
    'lllm://demo/support-desk/snapshots/queue-depth',
)
"""
raw = ChannelRef(RAW)
print(raw.org, raw.package, raw.resource_kind, raw.name)
#> demo events channels raw
binding = resolver.resolve(RAW)  # (2)!
print(binding.url, binding.metadata)
#> http://127.0.0.1:7700 {'owner': 'data-team'}
print(type(resolver.client(RAW)).__name__)  # (3)!
#> RemoteStore
print(resolver.local_store(INBOX).root.relative_to(resolver.root))
#> .lllm/network
print(resolver.store_path(DEPTH).relative_to(resolver.root))  # (4)!
#> data/archive
```

1. `from_config` takes a project folder and reads its `.lllm/config.toml`,
   or takes the file's own path. Relative store paths resolve against the
   folder that holds `.lllm/`.
2. `resolve()` returns the binding: its target, plus the binding's other
   keys as `metadata`.
3. `client(ref)` builds a `RemoteStore` for a `url` binding. Nothing is
   sent until you call a method.
4. `store = "archive"` names the `[stores.archive]` table, so the binding
   uses that table's `path`.

Each binding has exactly one target: `store`, a folder or the name of a
`[stores.NAME]` table; `path`, always a folder; or `url`, the absolute
`http` or `https` URL of a served store. A binding with no target or more
than one raises `ChannelRefError`, and so does resolving a ref that is not
bound.

The resolver loads only `/channels/` and `/snapshots/` refs. Refs to
LLLM's other sections, such as `tactics`, `services`, and `schemas`, are
left to their own layers, such as `lllm.Resolver`.
All binding keys must still be valid `lllm://` refs:
malformed SSSN and non-SSSN refs fail validation with `ChannelRefError`,
and so does a ref to a section LLLM does not define.

| Method | Returns |
| --- | --- |
| `ChannelResolver.from_config(path)` | A resolver for `path/.lllm/config.toml`, or for a config file's path; the file must exist |
| `ChannelResolver.from_text(text, *, root=None)` | A resolver for config text, parsed in memory without writing files; relative paths resolve against `root` (default: the working directory) |
| `ChannelResolver(root=".")`, `bind(ref, *, url=None, store=None, path=None, metadata=None)` | An empty resolver, and bindings made in code, as in tests |
| `resolve(ref)` | A `ResolvedChannelRef`: `ref`, `resource_kind`, `name`, `url`, `store`, `path`, `metadata` |
| `local_store(ref)`, `store_path(ref)` | A `LocalStore`, or its folder, for a `store` or `path` binding |
| `client(ref)`, `async_client(ref)` | A `RemoteStore` or `AsyncRemoteStore` for a `url` binding; both take `timeout=` and `transport=` |
| `refs()`, `stores()`, `store(name)` | The bound refs, sorted, and the `[stores.NAME]` tables |

As with `LocalStore` roots, resolver config paths must be
non-empty and unpadded: an empty path, or one with spaces around it,
raises `ValueError`.

## Tactics and channels from one config

`lllm.Resolver` reads the same file and resolves tactic refs too, so a
worker can get its tactic and its store by ref. `Resolver.from_config(".")`
loads the file, `resolver.store(ref)` returns a `LocalStore` or a
`RemoteStore`, and `resolver.channels` is the `ChannelResolver` behind it:

```python title="worker_by_ref.py"
from pathlib import Path

from lllm import Resolver, Tactic
from sssn import TacticProcessor

TRIAGE = "lllm://demo/support-desk/tactics/triage"
INBOX = "lllm://demo/support-desk/channels/inbox"

Path(".lllm").mkdir()
Path(".lllm/config.toml").write_text(
    f"""
[refs."{INBOX}"]
store = ".lllm/network"
"""
)


class Triage(Tactic):
    name = "triage"

    def call(self, ticket: dict) -> str:
        return "urgent" if "down" in ticket["text"] else "normal"


resolver = Resolver.from_config(".")
resolver.register(TRIAGE, Triage())  # (1)!
store = resolver.store(INBOX)  # (2)!
store.create_channel({"name": "inbox"})
store.create_channel({"name": "triaged"})
store.append_event({"channel": "inbox", "payload": {"text": "API is down"}})

worker = TacticProcessor(
    resolver.tactic(TRIAGE), store, source="inbox", sink="triaged"
)
print([event.payload for event in worker.process()])
#> ['urgent']
```

1. `register()` binds the tactic ref to a tactic in this process. Bind the
   ref to a `url` in the config instead, and `resolver.tactic(TRIAGE)`
   returns a `RemoteTactic`; the worker code stays the same.
2. Bind the channel ref to a `url`, and this is a `RemoteStore`. A
   processor reads and writes one store, so bind its source and sink
   channels to the same store.

## Publish to the LLLM Hub

The hub lists a package's channels and snapshots with their refs, forms,
descriptions, and endpoint metadata. The commands are LLLM's
([The hub](https://lllm.one/publishing/)):

```bash
lllm hub validate support-desk              # check the manifest
lllm hub publish support-desk --local       # copy it into .lllm/hub
lllm hub config-template demo/support-desk  # a starting .lllm/config.toml
```

- Publishing copies the package folder but leaves `.lllm/` behind, so a
  store inside the package is never published: the hub lists the channels,
  not their events.
- The config template binds each channel and snapshot ref to
  `store = ".lllm/network"`, a store in the project that uses the package.
  To share the store that `lllm serve` runs, bind the refs to its `url`
  instead.
