# Stores

A store keeps channels and everything recorded in them: events,
subscription cursors, artifacts, and snapshots. Every store has the same
methods, so code written against one store runs against any other.
SSSN ships one storage backend, `LocalStore`: a SQLite file and a folder of
artifact files, with no server to run and nothing to configure.

```python title="local_store.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")  # (1)!
store.create_channel({"name": "readings"})
store.append_event({"channel": "readings", "payload": {"celsius": 21.5}})
store.create_subscription("readings", subscription_id="dashboard")
print(len(store.pull_subscription("dashboard")))
#> 1
print(sorted(path.name for path in store.root.iterdir()))  # (2)!
#> ['artifacts', 'network.sqlite']

restarted = LocalStore(".lllm/network")  # (3)!
print([channel.name for channel in restarted.list_channels()])
#> ['readings']
print(restarted.get_subscription("dashboard").cursor)
#> 1
```

1. The folder is created if it does not exist. `LocalStore()` with no
   argument uses `.lllm/network` in the working directory, the folder the
   `sssn` and `lllm network` commands use by default.
2. `network.sqlite` holds channels, events, subscriptions, snapshots, and
   artifact records. `artifacts/` holds the artifact bytes.
3. A second store object on the same folder, in this process or another,
   sees the same data, subscription cursor included. Nothing is kept in the
   object: every call opens its own SQLite connection and commits before it
   returns.

Because all state is in the folder, a worker can stop and start again, a
command-line tool can inspect what a program wrote, and a test can create a
store in a temporary folder and throw it away.

## Where the data lives

```text
.lllm/network/
├── network.sqlite        # channels, events, subscriptions, snapshots,
│                         # and artifact records
└── artifacts/
    └── 2cf24dba5fb0a...  # artifact bytes, named by their SHA-256
```

`LocalStore(root=".lllm/network")` takes one argument, the folder. A
relative path is relative to the working directory, and `~` is expanded. A
root that is empty or padded with spaces raises `ValueError`.

| Attribute | Value |
| --- | --- |
| `root` | The store folder, as an absolute path |
| `db_path` | `root / "network.sqlite"` |
| `artifacts_dir` | `root / "artifacts"` |

To start over, delete the folder. To back up or move a store, copy the
folder while no process is writing to it.

An event's cursor is its row number in the SQLite file. Cursors increase
across the whole store, so within one channel they are ordered but can have
gaps; resume from the last cursor you read instead of adding one
([Reading events](channels.md#reading-events)). Artifact files are named
by the SHA-256 of their bytes, so writing the same bytes twice makes two
artifact records that share one file
([Artifacts and snapshots](artifacts.md)).

## How values are stored

Payloads, metadata, and snapshot values are stored as JSON. Pydantic models
are dumped, tuples become lists, dates become strings, and dict keys are
sorted:

```python title="stored_values.py"
from datetime import date

from pydantic import BaseModel

from sssn import LocalStore


class Reading(BaseModel):
    sensor: str
    celsius: float


store = LocalStore(".lllm/network")
store.create_channel({"name": "readings"})
event = store.append_event(
    {
        "channel": "readings",
        "payload": Reading(sensor="boiler", celsius=64.0),
        "metadata": {"day": date(2026, 11, 18), "tags": ("hot", "east")},
    }
)
print(type(event.payload).__name__)  # (1)!
#> Reading
stored = store.get_event(event.id)
print(stored.payload)
#> {'celsius': 64.0, 'sensor': 'boiler'}
print(stored.metadata)
#> {'day': '2026-11-18', 'tags': ['hot', 'east']}
```

1. The event that `append_event` returns holds the value you passed. Read
   the event back to see what other processes will get.

A value that cannot become JSON, such as an arbitrary object, raises
`InvalidPayloadError` and nothing is written. Readers get plain JSON data,
so validate it back into your model where you need one, as a
[tactic](processing.md#what-the-tactic-sees) does with its input model.

## The store interface

These are all the methods of a store. `LocalStore` and `RemoteStore` have
all of them with the same arguments, and `AsyncRemoteStore` has them as
coroutines:

| Resource | Methods | Guide |
| --- | --- | --- |
| Channels | `create_channel`, `list_channels`, `get_channel` | [Channels and events](channels.md) |
| Events | `append_event`, `query_events`, `get_event` | [Channels and events](channels.md) |
| Subscriptions | `create_subscription`, `get_subscription`, `pull_subscription` | [Subscriptions](subscriptions.md) |
| Artifacts | `write_artifact`, `read_artifact`, `get_artifact` | [Artifacts and snapshots](artifacts.md) |
| Snapshots | `put_snapshot`, `get_snapshot` | [Artifacts and snapshots](artifacts.md) |

SSSN has no base class for stores. Everything that takes a store, such as
[`TacticProcessor`](processing.md), the [HTTP server](http.md), and your
own functions, calls only these methods, so a function written and tested
against a `LocalStore` works on a store served from another machine. The
store server is built the same way: `create_app` turns each method into a
route, and `RemoteStore` turns each route back into the method
([Over HTTP](http.md)).

Two things differ between local and remote stores. Artifact data:
`LocalStore` takes `bytes`, `bytearray`, or `memoryview`, and `RemoteStore`
takes `bytes` or `str`, sent as UTF-8 text. And errors have different
classes: `LocalStore` raises `NetworkError` subclasses such as
`ChannelExistsError`, while a remote store raises `RemoteStoreError`, whose
`error_type` holds the server's class name. Code that should run on both
can compare names:

```python title="any_store.py"
from sssn import LocalStore, NetworkError, RemoteStoreError


def error_type(error: Exception) -> str:
    return getattr(error, "error_type", None) or type(error).__name__


def ensure_channel(store, name: str) -> None:
    """Create a channel unless it exists, on any store."""
    try:
        store.create_channel({"name": name})
    except (NetworkError, RemoteStoreError) as error:
        if error_type(error) != "ChannelExistsError":
            raise


store = LocalStore(".lllm/network")
ensure_channel(store, "readings")
ensure_channel(store, "readings")  # (1)!
print([channel.name for channel in store.list_channels()])
#> ['readings']
```

1. The second call finds the channel and does nothing. On a `RemoteStore`
   the same call gets a 409 response, which arrives as a `RemoteStoreError`
   with `error_type` `"ChannelExistsError"`.

## Concurrency

Several processes can share one store folder, such as a store server and a
worker on the same machine. Each call opens its own SQLite connection, so
one `LocalStore` object can also be shared between threads.

- **Writes are serialized.** SQLite lets one writer commit at a time, and
  each write is one short transaction. A call that waits more than
  SQLite's 5-second busy timeout for another process fails with
  `sqlite3.OperationalError`.
- **One reader per subscription.** `pull_subscription` reads the cursor and
  then moves it, in two steps, so two processes pulling the same
  subscription at once can receive the same events. Give each worker its
  own subscription
  ([Several consumers](subscriptions.md#several-consumers-on-one-channel)).
- **Share over HTTP, not over a network drive.** SQLite's file locking is
  unreliable on network file systems. To share a store between machines,
  [serve it](http.md) and point the others at its URL.

## Durability

- **A write that returned is on disk.** Every method commits before it
  returns, so once `append_event` returns, the event survives a crash of the
  process that wrote it.
- **An artifact record always has its bytes.** `write_artifact` writes the
  file first and then commits the record, so a process that stops midway can
  leave a file without a record, never a record without its file.
- **Nothing is deleted.** A store has no delete methods. `put_snapshot`
  replaces a snapshot, but events, artifacts, channels, and subscriptions
  stay until you delete the folder.

## Next steps

- [Serve a store over HTTP](http.md) so other machines can share it, and
  add your own routes next to the standard ones.
- [Run a tactic over a channel](processing.md) with `TacticProcessor`.
- [Bind a package's channels to a store](packages.md) per machine in
  `.lllm/config.toml`.
