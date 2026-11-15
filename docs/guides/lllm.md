# Use with LLLM

SSSN is the channel layer of the [LLLM](https://lllm.one/) family. LLLM runs
tactics and owns packages and the hub; SSSN keeps the events those tactics read
and write. The `sssn` package depends on `lllm-core` and plugs into it in four
places:

| LLLM piece | What SSSN adds |
| --- | --- |
| Tactics | `TacticProcessor` runs any LLLM tactic over a channel's events. |
| The `lllm` command | `lllm network`, the SSSN store CLI. |
| Packages and the hub | `[channels.*]` and `[snapshots.*]` resources in `lllm.toml`, served and indexed by LLLM tooling. |
| Refs | `lllm.Resolver` resolves `lllm://` channel and snapshot refs to SSSN stores. |

## Install

```bash
pip install sssn                    # or: pip install "lllm-core[network]"
pip install "sssn[server,client]"   # with the store server and clients
```

LLLM never needs SSSN to run tactics. `lllm.Resolver` and `lllm serve` import
SSSN only for channel resources and say what to install when it is missing.

## The `lllm network` Command

Installing `sssn` adds `lllm network` through an entry point in SSSN's
`pyproject.toml`:

```toml
[project.entry-points."lllm.commands"]
network = "sssn.cli"
```

`lllm network` and `sssn` are the same CLI, with the same default store
(`.lllm/network`), so they work on the same events:

```bash
lllm network create-channel inbox --description "Support messages."
lllm network append inbox '{"text": "Checkout is down"}' --kind message
sssn query-events inbox      # the same store
lllm --help                  # lists network next to the core commands
```

Without `sssn`, `lllm network` prints
`lllm network needs the sssn package: pip install sssn` and exits with
status 2. Every command is listed in the [CLI reference](../reference/cli.md).

## Run Tactics Over Channels

`TacticProcessor` reads a channel through a named subscription, runs each
event's payload through a tactic, and appends the output to a sink channel.
Each output points back at its input through `parent_ids` and carries the
input's `correlation_id`, so chains of processors stay traceable. The examples
in this section run top to bottom as one session.

```python
import re

from pydantic import BaseModel

from lllm import Tactic
from sssn import Event, LocalStore, TacticProcessor

URGENT = re.compile(r"\b(down|outage|failing|broken)\b", re.IGNORECASE)


class Ticket(BaseModel):
    text: str


class Triage(BaseModel):
    priority: str


class TriageTicket(Tactic[Ticket, Triage]):
    name = "triage"
    input_type = Ticket
    output_type = Triage

    def _run(self, input_value, *, context=None):
        urgent = URGENT.search(input_value.text)
        return Triage(priority="urgent" if urgent else "normal")


store = LocalStore(".lllm/network")
store.create_channel({"name": "inbox"})
store.create_channel({"name": "triaged"})


def submit(text, ticket):
    store.append_event(
        Event(channel="inbox", kind="message", payload={"text": text}, correlation_id=ticket)
    )


submit("Checkout is down", "T-100")
submit("How do I export my data?", "T-101")

processor = TacticProcessor(TriageTicket(), store, source="inbox", sink="triaged")
for event in processor.process():
    print(event.source, event.kind, event.correlation_id, event.payload)
print(processor.process())
```

```text
triage-inbox-processor result T-100 {'priority': 'urgent'}
triage-inbox-processor result T-101 {'priority': 'normal'}
[]
```

The second `process()` call returns `[]`: the subscription lives in the store
and remembers where it stopped, across restarts and across processes. Any
tactic works: a `Tactic` subclass, `as_tactic(fn)`, a native tactic with
agents, or a `RemoteTactic` that calls a served one.

| Argument | Default | Meaning |
| --- | --- | --- |
| `tactic` | required | Any LLLM tactic. |
| `store` | required | `LocalStore` or `RemoteStore` for `process()`; any store, including `AsyncRemoteStore`, for `aprocess()`. |
| `source` | required | Channel to read. |
| `sink` | `None` | Channel to append outputs to. Without one, outputs are returned instead. Create it before processing. |
| `consumer` | `"<tactic name>-<source>-processor"`, or `"<tactic name>-<source>-<kind>-processor"` with a `kind` | Subscription id, and the `source` of output events. |
| `kind` | `None` | Only process source events of this kind. |
| `output_kind` | `"result"` | `kind` of the output events. |
| `errors` | `"raise"` | What a failure does; see [Delivery and failures](#delivery-and-failures). |

Output events hold the tactic output as JSON (Pydantic models are dumped with
`model_dump(mode="json")`), `parent_ids=(input.id,)`, and the input's
`correlation_id`, or the input's id when it has none.

### What the tactic sees

The tactic gets the event's payload as its input, validated against its input
type, and a `CallContext` that describes the event:

| Context field | Value |
| --- | --- |
| `caller` | The consumer name. |
| `tags` | `{"channel": <source>}` |
| `metadata["event_id"]` | The input event's id. |
| `metadata["event_kind"]` | The input event's kind. |
| `metadata["correlation_id"]` | The input's correlation id, or its id. |

### Delivery and failures

Events are processed one at a time and at least once. The processor reads the
next event at the subscription cursor, runs the tactic, appends the output to
the sink, and only then acknowledges the event. An event that was not
acknowledged, because processing raised or the worker stopped, runs again on
the next call, so a tactic can see an event twice and the sink can hold more
than one output for it.

With `errors="raise"` (the default), the exception propagates and the failing
event stays pending; the next call runs it again before any event behind it.
With `errors="record"`, the failure is written to the sink as a `kind="error"`
event with the same lineage fields, the event is acknowledged, and processing
continues:

```python
submit("Search is broken", "T-102")
store.append_event(
    Event(channel="inbox", kind="message", payload={"subject": "no text"}, correlation_id="T-103")
)

recording = TacticProcessor(
    TriageTicket(), store, source="inbox", sink="triaged", errors="record"
)
results = recording.process()
print([(event.kind, event.correlation_id) for event in results])
print(results[1].payload["type"])
```

```text
[('result', 'T-102'), ('error', 'T-103')]
SchemaError
```

The error payload is `{"error": str(exc), "type": type(exc).__name__}`. Use
`"record"` in long-running workers so one bad event cannot block the
subscription; read failures back with `store.query_events("triaged", kind="error")`.
`"record"` needs a sink; without one it acts like `"raise"`. If the error event
cannot be written either, `process()` raises and the event stays pending.

### Consumers

The default consumer joins the tactic name (`tactic.tactic_name`, the function
name for `as_tactic(fn)`), the source, and the `kind` filter if there is one,
so one tactic can process several channels:

- Name consumers explicitly when two processors would share the default; the
  sink is not part of it.
- If the default would contain whitespace, `?`, or `#`, the constructor raises
  `ValueError`; pass `consumer=`.
- To process a channel again from the start, use a new consumer name.
- A subscription keeps the channel and `kind` filter it was created with.
  Reusing a consumer name with another channel or kind makes `process()` raise
  `ValueError`.
- Run one worker per consumer. Workers sharing a consumer can process the same
  event twice, and with `errors="raise"` they can lose one.

### Remote and async stores

The processor only calls store methods, so a `RemoteStore` works with
`process()` exactly like a `LocalStore`. `aprocess()` is the async variant: it
calls `tactic.arun()` and awaits store calls that return coroutines, so it
works with `AsyncRemoteStore` as well as the sync stores. `process()` raises
`TypeError` when given an async store. A worker is a loop around `process()`
that sleeps when there is nothing to do:

```python
import time


def run_worker(processor, *, idle_seconds=1.0):
    while True:
        if not processor.process(limit=100):
            time.sleep(idle_seconds)
```

## Channel Packages

An LLLM package declares channels and snapshots in `lllm.toml`. For a folder
`support-desk/`:

```toml
[package]
org = "demo"
name = "support-desk"
version = "0.1.0"
kind = "channel"
primary = "channels.inbox"
description = "Support messages and their triage."

[channels.inbox]
form = "log"
description = "Support messages as they arrive."

[channels.triaged]
form = "log"
description = "One triage result per message."

[snapshots.latest-reply]
channel = "triaged"
description = "The newest drafted reply."
```

`open_package_store(manifest, *, store=None)` opens the package's store,
`<package>/.lllm/network` by default, and creates every declared channel that
does not exist yet:

```python
from lllm.hub import load_manifest
from sssn.resources import open_package_store

manifest = load_manifest("support-desk")
package_store = open_package_store(manifest)
print(package_store.root.relative_to(manifest.base_dir))
print([channel.name for channel in package_store.list_channels()])
```

```text
.lllm/network
['inbox', 'triaged']
```

The LLLM tooling uses it for channel resources:

```bash
lllm serve support-desk --resource channels.inbox --port 7700   # the package store over HTTP
lllm hub validate support-desk                                  # forms are checked against SSSN's
lllm hub publish support-desk --local
lllm hub config-template demo/support-desk                      # a starting .lllm/config.toml
```

`lllm serve` serves the whole package store (every declared channel) with
SSSN's `create_app`; `--store DIR` picks another folder. The config template
binds each channel and snapshot ref to `store = ".lllm/network"`. To describe
channels from code, or to add custom endpoint metadata to the hub's cards, use
`channel_resource` and `snapshot_resource` ([Refs and Packages](packages.md)).

## Channel Refs in `lllm.Resolver`

`lllm.Resolver` reads tactic, channel, and snapshot bindings from the same
`.lllm/config.toml`, so a worker can get both its tactic and its store by ref:

```toml
[refs."lllm://demo/support-desk/tactics/triage"]
url = "http://127.0.0.1:8000/tactics/triage"

[refs."lllm://demo/support-desk/channels/inbox"]
store = ".lllm/network"
```

```python
from lllm import Resolver
from sssn import TacticProcessor

resolver = Resolver.from_config(".")
worker = TacticProcessor(
    resolver.tactic("lllm://demo/support-desk/tactics/triage"),   # a RemoteTactic
    resolver.store("lllm://demo/support-desk/channels/inbox"),    # LocalStore or RemoteStore
    source="inbox",
    sink="triaged",
)
```

`resolver.resolve(ref)` returns a tactic for `/tactics/` refs and a store for
`/channels/` and `/snapshots/` refs; `resolver.channels` is the
`sssn.ChannelResolver` behind it ([Refs and Packages](packages.md#resolve-shared-config)).
A ref resolves to a whole store; the channel inside it is the ref's last
segment. Bind the ref to the `url` of a store served with `sssn serve` and the
same code gets a `RemoteStore`.

## Tactics and Channels in One API

[AAAX](https://aaax.one/), the strategy shell built on LLLM, mounts a
package's tactics and channels behind one served API. Install it with
`pip install aaax`; then `lllm shell serve PACKAGE` serves them together.

## Coming From `lllm.network`

LLLM 0.3 shipped this code as `lllm.network`. In LLLM 0.4 that module is a
deprecated alias: it imports `sssn`, warns once, and keeps old import paths
working (`lllm.network.server.fastapi` is `sssn.server.fastapi`). Replace
`from lllm.network import ...` with `from sssn import ...`; the names are the
same.
