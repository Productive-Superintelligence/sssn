# Channels and events

A channel is a named, append-only sequence of events in a store. Writers
append events; readers query them in order, or follow them with a
[subscription](subscriptions.md). Each event is a JSON payload inside an
envelope that says what happened, who wrote it, and which other events it
came from, so readers can act on events without knowing their writers.

```python title="orders.py"
from sssn import Channel, LocalStore

store = LocalStore(".lllm/network")
orders = store.create_channel(  # (1)!
    Channel(
        name="orders",
        schema="shop.schemas:Order",
        description="Orders as customers place them.",
    )
)
print(orders.form)
#> log

for kind, order in [("placed", "A-1"), ("placed", "A-2"), ("paid", "A-1")]:
    store.append_event(  # (2)!
        {
            "channel": "orders",
            "kind": kind,
            "source": "checkout",
            "correlation_id": order,
            "payload": {"order": order},
        }
    )

paid = store.query_events("orders", kind="paid")  # (3)!
print([(event.cursor, event.correlation_id) for event in paid])
#> [(3, 'A-1')]
newer = store.query_events("orders", after_cursor=1)  # (4)!
print([(event.kind, event.payload["order"]) for event in newer])
#> [('placed', 'A-2'), ('paid', 'A-1')]
```

1. A channel is described once, when it is created. The form defaults to
   `log`; the schema is a reference that readers can use to parse payloads.
2. An event is a dict (or an `Event`). Only `channel` is required; the
   store fills in the id, the timestamp, and the cursor.
3. `kind` is the field readers filter on.
4. Every event has a cursor. Asking for events after a cursor is how a
   reader continues from where it stopped.

## Creating channels

`create_channel()` takes a `Channel` or a dict with the same fields and
returns the stored channel:

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | required | Unique in the store; see [Names](#names) |
| `form` | `"log"` | How the channel is meant to be used; see [Forms](#forms) |
| `schema` | `None` | A ref to the payload schema, such as `shop.schemas:Order`; stored, not enforced |
| `description` | `""` | What the channel carries, for people and package cards |
| `metadata` | `{}` | A JSON object for anything else |

`get_channel(name)` returns one channel and raises `ChannelNotFoundError`
for an unknown name; `list_channels()` returns all of them, sorted by name.
Creating a channel whose name is taken raises `ChannelExistsError`.
Channels are permanent: the store has no method to change or delete one.

A worker usually makes sure its channels exist when it starts. Catch
`ChannelExistsError` so that a restart does not fail:

```python title="ensure.py"
from sssn import ChannelExistsError, LocalStore


def ensure_channel(store, **fields):
    try:
        return store.create_channel(fields)
    except ChannelExistsError:
        return store.get_channel(fields["name"])


store = LocalStore(".lllm/network")
ensure_channel(store, name="orders", form="queue")
ensure_channel(store, name="orders", form="queue")  # after a restart
print([channel.name for channel in store.list_channels()])
#> ['orders']
```

The helper works on any store: a served store reports a taken name with
the same `ChannelExistsError` ([Stores](stores.md#the-store-interface)). In
an LLLM package, declare channels in `lllm.toml` instead, and they are
created when the package's store is opened
([Packages and refs](packages.md)).

## Forms

The form says how a channel is meant to be used. It is `log` unless you
choose another:

| Form | Meant for |
| --- | --- |
| `log` | Append-only event history |
| `queue` | Work items that consumers take in order |
| `topic` | Broadcast or pub/sub streams |
| `blackboard` | A shared surface where agents post and build on findings |
| `latest-state` | The latest materialized state for a key |
| `artifact-index` | Event metadata over larger payloads |
| `pipeline-edge` | The hand-off between two processing stages |
| `database-view` | Records mirrored from, or derived for, a database |
| `feed` | Items from an outside source as they arrive |
| `time-series` | Ordered observations with temporal meaning |
| `tree` | Records that form a hierarchy through parent links |
| `forum` | Threads of posts and replies |
| `hub` | A meeting point that gathers several channels |

A form is a promise to readers, not a storage mode. `LocalStore` keeps every
channel as an append-only log whatever its form, and the API is the same
for all of them; the form tells readers and tools what to expect. Any other
value fails validation (there is no `stream` form; use `log` or `topic`).
`sssn.ChannelForm` lists the forms, and the LLLM hub checks the forms in a
package's `[channels.NAME]` tables against the same list.

## Appending events

`append_event()` takes an `Event` or a dict of its fields and returns the
stored event, with its cursor:

| Field | Default | Meaning |
| --- | --- | --- |
| `channel` | required | The channel; it must exist |
| `payload` | `None` | Any JSON value |
| `kind` | `"event"` | What happened, as a token readers filter on: `placed`, `result`, `error` |
| `source` | `None` | Who wrote it: a service, a worker, a device |
| `correlation_id` | `None` | The piece of work it belongs to: an order, a ticket, a run |
| `parent_ids` | `()` | The events it was derived from, in any channel; they must exist |
| `id` | a random UUID | Unique in the store; set your own to make retries safe ([Event ids](#event-ids-and-retries)) |
| `timestamp` | now | Seconds since the epoch; set it to when the thing happened |
| `schema` | `None` | A ref to this payload's schema |
| `metadata` | `{}` | A JSON object for small hints |
| `cursor` | set by the store | The event's position; a value you pass is ignored |

Payloads are stored as JSON. A Pydantic model is stored as its JSON form
and read back as a dict, so readers validate it into their own model, as
`Order.model_validate(event.payload)`. A value that has no JSON form, such
as an arbitrary object, raises `InvalidPayloadError`, and nothing is
written. [Stores](stores.md) shows how other values, such as dates and
tuples, are stored.

## Reading events

`query_events(channel, *, after_cursor=0, limit=100, kind=None)` returns up
to `limit` events of one channel in the order they were appended, starting
after `after_cursor`, optionally only those of one `kind`.
`get_event(event_id)` returns a single event from any channel and raises
`EventNotFoundError` for an unknown id.

Cursors are store-wide: the store numbers events across all its channels,
so the cursors of one channel increase but have gaps. To read a long
channel in pages, pass the last cursor you saw:

```python title="paging.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "orders"})
store.create_channel({"name": "refunds"})
for n in range(5):
    store.append_event({"channel": "orders", "payload": n})
    store.append_event({"channel": "refunds", "payload": n})

cursor = 0
while page := store.query_events("orders", after_cursor=cursor, limit=2):
    print([(event.cursor, event.payload) for event in page])
    #> [(1, 0), (3, 1)]
    #> [(5, 2), (7, 3)]
    #> [(9, 4)]
    cursor = page[-1].cursor
```

`after_cursor` must be 0 or more and `limit` at least 1, or the store raises
`InvalidPayloadError`. With `query_events`, the reader keeps track of the
cursor. A [subscription](subscriptions.md) keeps it in the store instead,
so it survives restarts.

## Linking events

Two fields connect events across channels. `correlation_id` groups every
event of one piece of work, and `parent_ids` names the events this one was
derived from. Parents can live in any channel, and they must exist:

```python title="lineage.py"
from sssn import EventNotFoundError, LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "orders"})
store.create_channel({"name": "invoices"})

order = store.append_event(
    {
        "channel": "orders",
        "correlation_id": "A-1",
        "payload": {"total": 9.5},
    }
)
invoice = store.append_event(
    {
        "channel": "invoices",
        "kind": "issued",
        "correlation_id": order.correlation_id,
        "parent_ids": [order.id],
        "payload": {"amount": 9.5},
    }
)
print(store.get_event(invoice.parent_ids[0]).channel)
#> orders

try:
    store.append_event({"channel": "invoices", "parent_ids": ["missing"]})
except EventNotFoundError as error:
    print(error)
    #> Event not found: missing
```

Because a parent must exist before its children, lineage always points to
earlier events, and a reader can walk from any result to the events that
produced it. `TacticProcessor` sets both fields on every output it writes
([Processing with tactics](processing.md)).

## Event ids and retries

A producer that times out cannot tell whether its append reached the store.
If it sets the event id from something stable, such as the id of the
payment or message it reports, a retry cannot write the event twice:

```python title="retries.py"
from sssn import EventExistsError, LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "payments"})


def record_payment(payment_id, amount):
    try:
        store.append_event(
            {
                "id": payment_id,
                "channel": "payments",
                "payload": {"amount": amount},
            }
        )
    except EventExistsError:
        pass  # an earlier attempt already recorded it


record_payment("pay-1001", 25)
record_payment("pay-1001", 25)  # a retry after a timeout
print(len(store.query_events("payments")))
#> 1
```

Ids are unique in the whole store, not per channel: an id that is taken in
any channel raises `EventExistsError`, and the original event is kept.

## Names

Channel names, event ids, subscription ids, snapshot names, and artifact
ids appear in URLs (`/channels/orders`) and in refs
(`lllm://acme/shop/channels/orders`), so they
must be non-empty path segments. They cannot contain whitespace, and they
must avoid percent escapes, `.`, `..`, `/`, `\`, and `:`. The dots are
rejected only as whole names, so `orders.v2` is fine. Kinds, correlation
ids, and consumer names follow the same rule.

```python title="names.py"
from sssn import InvalidPayloadError, LocalStore

store = LocalStore(".lllm/network")
for name in ["orders.v2", "eu/orders", "two words", "100%", "..", "a:b"]:
    try:
        store.create_channel({"name": name})
        print("ok:", name)
        #> ok: orders.v2
    except InvalidPayloadError:
        print("rejected:", name)
        #> rejected: eu/orders
        #> rejected: two words
        #> rejected: 100%
        #> rejected: ..
        #> rejected: a:b
```

Other characters, such as `?`, `#`, and `é`, are allowed, and remote
stores escape them in URLs, so a name that works with `LocalStore` works
over HTTP too. Letters, digits, `-`, `_`, and `.` are still the easiest to
type in a URL or a shell.

## Errors

| Error | Raised when |
| --- | --- |
| `ChannelExistsError` | creating a channel whose name is taken |
| `ChannelNotFoundError` | reading, appending to, or subscribing to a channel that does not exist |
| `EventExistsError` | appending an event whose id is taken, in any channel |
| `EventNotFoundError` | `get_event()` with an unknown id, or a parent that does not exist |
| `InvalidPayloadError` | an invalid name, form, field, cursor, or limit, or a payload with no JSON form |

All of them subclass `NetworkError`. Building a model yourself, as in
`Channel(name="two words")`, raises Pydantic's `ValidationError` instead;
a dict passed to the store is reported as `InvalidPayloadError`. A served
store answers 404 for the not-found errors, 409 for the exists errors, and
400 for the rest, and `RemoteStore` raises the same classes. Its errors are
also `RemoteStoreError`s, with the `status_code` and the `error_type`
([Over HTTP](http.md)).
