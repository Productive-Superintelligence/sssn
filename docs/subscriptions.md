# Subscriptions

A subscription is a named cursor over one channel, kept in the store. A
consumer pulls the events after its cursor, and the cursor moves past them,
so the consumer resumes where it stopped after a restart, even in another
process. Each consumer has its own subscription, so several of them can
read the same channel without taking events from each other.

```python title="consumers.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "orders"})
for order in ["A-1", "A-2"]:
    store.append_event({"channel": "orders", "payload": order})

for consumer in ["billing", "shipping"]:  # (1)!
    store.create_subscription("orders", subscription_id=consumer)

batch = store.pull_subscription("billing")  # (2)!
print([event.payload for event in batch])
#> ['A-1', 'A-2']
store.append_event({"channel": "orders", "payload": "A-3"})

restarted = LocalStore(".lllm/network")  # (3)!
batch = restarted.pull_subscription("billing")
print([event.payload for event in batch])
#> ['A-3']
batch = restarted.pull_subscription("shipping")  # (4)!
print([event.payload for event in batch])
#> ['A-1', 'A-2', 'A-3']
```

1. Each consumer gets its own subscription, named after it. A new
   subscription starts at the beginning of the channel.
2. A pull returns the events after the cursor and moves the cursor past
   them.
3. A new `LocalStore` on the same folder stands in for a restarted process.
   The cursor was saved in the store, so billing gets only the new order.
4. Shipping has its own cursor. Billing's pulls took nothing from it.

## Creating subscriptions

`create_subscription(channel, *, subscription_id=None, ...)` returns a
`Subscription`:

| Argument | Default | Meaning |
| --- | --- | --- |
| `channel` | required | The channel to read; it must exist |
| `subscription_id` | a random UUID | The subscription's name; see below |
| `filters` | `{}` | `{"kind": "..."}` to receive only events of one kind |
| `batch_size` | `100` | How many events a pull returns when it has no `limit` |
| `consumer` | `None` | The name of the reader, for your records |
| `metadata` | `{}` | A JSON object for anything else |

Give every long-lived consumer a fixed `subscription_id`. Creating a
subscription whose id exists returns the existing one, unchanged, with its
cursor, filter, and batch size, so a worker can call `create_subscription`
every time it starts. An id that exists for a different channel raises
`SubscriptionExistsError`. Without an id, every call makes a new
subscription with a random id, which is right only for a reader that never
restarts.

`get_subscription(subscription_id)` returns a subscription, with its
current `cursor`, and raises `SubscriptionNotFoundError` for an unknown id.

A kind filter makes a subscription skip every other kind:

```python title="refunds.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "orders"})
history = [("placed", "A-1"), ("refunded", "A-0"), ("placed", "A-2")]
for kind, order in history:
    store.append_event(
        {"channel": "orders", "kind": kind, "payload": order}
    )

store.create_subscription(
    "orders", subscription_id="refunds", filters={"kind": "refunded"}
)
print([event.payload for event in store.pull_subscription("refunds")])
#> ['A-0']
```

`kind` is the only filter. Any other key raises `InvalidPayloadError`, so a
filter you meant to apply is never silently ignored.

## Pulling events

`pull_subscription(subscription_id, *, limit=None)` returns up to `limit`
events after the cursor (`batch_size` when there is no limit), in the order
they were appended, and moves the cursor to the last one. When the consumer
has caught up, it returns an empty tuple. A worker is a loop around it that
sleeps when there is nothing to do:

```python title="worker.py"
import time


def run_billing(store, bill):
    while True:
        batch = store.pull_subscription("billing", limit=50)
        for event in batch:
            bill(event.payload)
        if not batch:
            time.sleep(1.0)
```

That loop has a gap. A pull reads events and moves the cursor in one step,
so the events are acknowledged as soon as they are returned. If `bill()`
raises, or the process dies halfway through a batch, the rest of the batch
is never seen again by this subscription. That is at-most-once delivery:
fine for a dashboard, wrong for billing.

## Acknowledging events

For at-least-once delivery, read the next event without moving the cursor,
do the work, and then acknowledge the event by pulling it. A failure before
the acknowledgment leaves the event pending, and the next run retries it:

```python title="mailer.py"
from sssn import LocalStore

store = LocalStore(".lllm/network")
store.create_channel({"name": "emails"})
for to in ["ada@example.com", "bob@example.com"]:
    store.append_event({"channel": "emails", "payload": {"to": to}})
store.create_subscription("emails", subscription_id="mailer")


def peek(store, subscription_id):  # (1)!
    """Return the next event without moving the cursor."""
    sub = store.get_subscription(subscription_id)
    return store.query_events(
        sub.channel,
        after_cursor=sub.cursor,
        limit=1,
        kind=sub.filters.get("kind"),
    )


sent = []
server_up = False


def send(message):
    if not server_up:
        raise ConnectionError("mail server is down")
    sent.append(message["to"])


def deliver():
    while pending := peek(store, "mailer"):
        send(pending[0].payload)  # (2)!
        store.pull_subscription("mailer", limit=1)  # (3)!


try:
    deliver()
except ConnectionError as error:
    print(error)
    #> mail server is down
print(store.get_subscription("mailer").cursor)  # (4)!
#> 0

server_up = True
deliver()
print(sent)
#> ['ada@example.com', 'bob@example.com']
```

1. `query_events` from the subscription's cursor reads what a pull would
   return, without moving anything.
2. The work happens before the acknowledgment.
3. Pulling one event moves the cursor past the event that `send()`
   handled: this is the acknowledgment.
4. The send failed, so nothing was acknowledged, and the first email is
   still pending. The second run delivers both.

The price of at-least-once is repeats: if the process dies after `send()`
and before the pull, the event runs again on restart. Make the work safe to
repeat, for example by recording the event id with its result and skipping
ids you have already handled. `TacticProcessor` runs this same loop around
a tactic ([Processing with tactics](processing.md)).

## Cursors

A cursor is an event's position in the store. A subscription's `cursor` is
the cursor of the last event it acknowledged, and 0 before the first pull.
Cursors count events across the whole store, so they increase but have gaps
within one channel.

- **Start from the beginning.** A new subscription reads the channel's
  whole history.
- **Start from now.** Pull and discard what is already there:
  `while store.pull_subscription(sub_id, limit=1000): pass`.
- **Read it all again.** Create a subscription with a new id. A cursor
  cannot be moved back.
- **Read without a subscription.** `query_events(channel,
  after_cursor=...)` reads from any cursor and moves nothing; the reader
  keeps the cursor itself ([Reading events](channels.md#reading-events)).

## Several consumers on one channel

Subscriptions give each consumer its own view of a channel, which is
publish/subscribe: every subscription sees every event (of its kind), as
billing and shipping do at the top of this page. Add a consumer at any time;
it starts at the beginning and catches up.

Workers can share one subscription with plain pulls. A pull reads the
events and moves the cursor in one transaction, so workers pulling the same
subscription at once get different events, like workers taking items from
a queue, with at-most-once delivery. The at-least-once loop above is
different: reading ahead and acknowledging are separate calls, so two
workers would run the same event, and one could acknowledge an event the
other has not finished. Give each such worker its own subscription, and to
spread one channel's work over several of them, give each its own share: a
kind filter per worker, or a channel per worker.

## Over HTTP and on the command line

A served store has the same subscription API, and the CLI works on a local
store:

| Python | HTTP | CLI |
| --- | --- | --- |
| `create_subscription(channel, ...)` | `POST /subscriptions` | `sssn create-subscription CHANNEL --id ID` |
| `get_subscription(subscription_id)` | `GET /subscriptions/{id}` | `sssn get-subscription ID` |
| `pull_subscription(subscription_id, limit=N)` | `POST /subscriptions/{id}/pull?limit=N` | `sssn pull-subscription ID --limit N` |

The HTTP body for `POST /subscriptions` names the id `id`, as in
`{"id": "billing", "channel": "orders"}`, and `RemoteStore` takes the same
arguments as `LocalStore`. `sssn create-subscription` also takes
`--consumer`, `--batch-size`, and `--kind`. See [Over HTTP](http.md) and
the [CLI reference](api/cli.md).
