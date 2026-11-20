# Over HTTP

A store can be served over HTTP, so processes on other machines can share
it. `create_app` turns each store method into a route, and `RemoteStore`
turns each route back into the same method, so code that takes a store
does not change when the store moves behind a URL.

```python title="round_trip.py"
import asyncio

import httpx

from sssn import AsyncRemoteStore, LocalStore, RemoteStoreError, create_app

store = LocalStore(".lllm/network")
app = create_app(store)  # (1)!


async def main():
    remote = AsyncRemoteStore(
        "http://store.internal:7700",
        transport=httpx.ASGITransport(app=app),  # (2)!
    )
    await remote.create_channel({"name": "orders"})
    order = {
        "channel": "orders",
        "id": "order-1001",
        "payload": {"total": 42},
    }
    event = await remote.append_event(order)  # (3)!
    print(event.id, event.cursor)
    #> order-1001 1
    try:
        await remote.append_event(order)  # (4)!
    except RemoteStoreError as error:
        print(error.status_code, error.error_type)
        #> 409 EventExistsError


asyncio.run(main())
print([event.payload for event in store.query_events("orders")])  # (5)!
#> [{'total': 42}]
```

1. `create_app` builds a FastAPI app whose routes call the store.
   `sssn serve` runs the same app with Uvicorn.
2. Only for this example: the transport sends requests to the app in this
   process. Against a running server, pass the URL alone. `RemoteStore` is
   the same client for synchronous code, without `await`.
3. A remote store has the store methods with the same arguments and return
   types ([The store interface](stores.md#the-store-interface)).
4. Event ids are unique in a store, so sending an event again is a 409
   conflict. A producer that retries with its own ids cannot write an event
   twice.
5. The server writes to an ordinary `LocalStore`, so a process on the same
   machine can read the events directly.

## Serve a store

`sssn serve` serves a store folder. It needs the `server` extra, which
brings FastAPI and Uvicorn:

```bash
pip install "sssn[server]"
sssn serve                                   # .lllm/network on port 7700
sssn --store data/events serve --host 0.0.0.0 --port 8100
lllm network serve                           # the same command
```

| Option | Default |
| --- | --- |
| `--store DIR`, given before `serve` | `.lllm/network` |
| `--host` | `127.0.0.1` |
| `--port` | `7700` |
| `--log-level` | `info` |

To add your own routes or middleware, or to choose the server and its
settings, build the app in a module and run it with any ASGI server:

```python title="store_app.py"
from sssn import LocalStore, create_app

app = create_app(LocalStore("data/events"))
```

```bash
uvicorn store_app:app --port 7700
```

`create_app(store=None, *, custom_endpoints=())` returns a plain FastAPI
app titled "SSSN Store". Without a store it opens `LocalStore()`, the
`.lllm/network` folder in the working directory, and the app keeps the
store it serves as `app.state.sssn_store`. To serve the channels a package
declares, use `lllm serve PACKAGE --resource channels.NAME`
([Packages and refs](packages.md#serve-a-packages-channels)).

## Routes

Each route calls one store method, and the JSON bodies follow the models,
such as `Channel` and `Event`:

| Routes | Store methods |
| --- | --- |
| `POST /channels`, `GET /channels`, `GET /channels/{name}` | `create_channel`, `list_channels`, `get_channel` |
| `POST /events`, `GET /events?channel=...`, `GET /events/{id}` | `append_event`, `query_events`, `get_event` |
| `POST /subscriptions`, `GET /subscriptions/{id}`, `POST /subscriptions/{id}/pull` | `create_subscription`, `get_subscription`, `pull_subscription` |
| `POST /artifacts`, `GET /artifacts/{id}/metadata`, `GET /artifacts/{id}` | `write_artifact`, `get_artifact`, `read_artifact` (the raw bytes) |
| `PUT /snapshots/{name}`, `GET /snapshots/{name}` | `put_snapshot`, `get_snapshot` |
| `GET /health` | Returns `{"ok": true}` |

FastAPI adds interactive docs at `/docs` and the OpenAPI document at
`/openapi.json`. Any HTTP client can use the routes:

```python title="routes.py"
from fastapi.testclient import TestClient

from sssn import LocalStore, create_app

client = TestClient(create_app(LocalStore(".lllm/network")))
client.post("/channels", json={"name": "orders"})
order = {"channel": "orders", "id": "order-1001", "payload": {"total": 42}}
client.post("/events", json=order)
response = client.get("/events", params={"channel": "orders"})
event = response.json()[0]
print(event["id"], event["cursor"], event["payload"])
#> order-1001 1 {'total': 42}

response = client.get("/channels/refunds")
print(response.status_code)
#> 404
print(response.json())
"""
{
    'detail': {
        'error': {
            'type': 'ChannelNotFoundError',
            'message': 'Channel not found: refunds',
        }
    }
}
"""
```

The [HTTP API](api/http-api.md) reference lists every body and query
parameter.

## Errors

Every error has the same body: the error's class name as `type`, and its
message. The status says what kind of error it is:

| Status | Errors |
| --- | --- |
| 400 | `InvalidPayloadError` and other `NetworkError`s; a request body that does not validate is reported as `InvalidPayloadError` with the field, as in `channel: Field required` |
| 404 | `ChannelNotFoundError`, `EventNotFoundError`, `SubscriptionNotFoundError`, `ArtifactNotFoundError`, `SnapshotNotFoundError` |
| 409 | `ChannelExistsError`, `EventExistsError`, `SubscriptionExistsError` |
| 500 | Anything else, with the exception's class name and message |

A 409 is often not a failure. A producer that retries after a timeout and
gets `EventExistsError` knows its event was written the first time, and a
worker that creates its channels on every start can ignore
`ChannelExistsError`. Creating a subscription with an id that exists on
the same channel is not a conflict: the server returns the existing
subscription, so a worker resumes where it stopped.

## Use a served store from Python

`RemoteStore` and `AsyncRemoteStore` take the same arguments. They need the
`client` extra (httpx):

| Argument | Default | Meaning |
| --- | --- | --- |
| `base_url` | required | The server's absolute `http` or `https` URL; a trailing `/` is dropped |
| `timeout` | `30.0` | Seconds to wait for each request; `None` waits forever |
| `transport` | `None` | An httpx transport, such as `httpx.ASGITransport` in tests |
| `headers` | `None` | Headers sent with every request, such as `{"Authorization": "Bearer ..."}` ([Securing a store](#securing-a-store)) |
| `auth` | `None` | An httpx authentication, such as `httpx.BasicAuth(user, password)` |

```python test="skip" reason="needs a running store server"
from sssn import RemoteStore

store = RemoteStore("http://127.0.0.1:7700")
store.create_channel({"name": "orders"})
store.append_event({"channel": "orders", "payload": {"total": 42}})
```

Each call opens its own HTTP connection and closes it after the response.
Before sending, the client checks names and ids and raises
`InvalidPayloadError` for a bad one, without a request. A server error
raises `RemoteStoreError` with `status_code`, `error_type` (the server's
class name, such as `"ChannelNotFoundError"`), `message`, and `detail`
(the raw response body). A response that does not match the expected
model raises `RemoteStoreError` with `error_type="InvalidResponse"`.

`RemoteStoreError` is a `NetworkError`. When the server reports one of the
store errors, the error raised is also an instance of that class, so
`except ChannelNotFoundError` catches a missing channel from a remote store
as it does from a `LocalStore`
([The store interface](stores.md#the-store-interface)). A store served by
`create_app` can itself be a `RemoteStore`; the app then reports the store
errors of the server behind it as that server did.
Artifact data may be `bytes`, sent base64-encoded, or `str`, sent as UTF-8
text.

## Custom endpoints

A store server can have routes of your own next to the standard ones, such
as a query your consumers need. Decorate a function with `endpoint.get`
(or `post`, `put`, `patch`, `delete`) and pass it to
`create_app(..., custom_endpoints=...)`:

```python title="tail.py"
import json

from fastapi.testclient import TestClient

from sssn import Channel, LocalStore, channel_resource, create_app, endpoint


@endpoint.get(
    "/channels/{name}/tail",
    scope="channel",
    description="Return the newest events of a channel.",
    tags=("channels",),
)
def channel_tail(store, name: str, params=None):  # (1)!
    limit = int((params or {}).get("limit", 3))
    events, cursor = [], 0
    while batch := store.query_events(name, after_cursor=cursor, limit=500):
        events.extend(batch)
        cursor = batch[-1].cursor
    return [event.payload for event in events[-limit:]]  # (2)!


store = LocalStore(".lllm/network")
store.create_channel({"name": "readings"})
for celsius in (20.5, 21.0, 21.5, 22.0):
    store.append_event({"channel": "readings", "payload": {"c": celsius}})

app = create_app(store, custom_endpoints=[channel_tail])
client = TestClient(app)
response = client.get("/channels/readings/tail", params={"limit": 2})
print(response.json())
#> [{'c': 21.5}, {'c': 22.0}]
print(client.get("/channels/refunds/tail").status_code)  # (3)!
#> 404

resource = channel_resource(  # (4)!
    Channel(name="readings"), custom_endpoints=[channel_tail]
)
print(json.dumps(resource["endpoints"][0], indent=2))
"""
{
  "name": "channel_tail",
  "method": "GET",
  "path": "/channels/{name}/tail",
  "scope": "channel",
  "description": "Return the newest events of a channel.",
  "tags": [
    "channels"
  ]
}
"""
```

1. Parameters are bound by name: `store` gets the store, `name` the path
   parameter, and `params` the query string as a dict of strings.
2. The return value is the response body, encoded as JSON, with no
   envelope.
3. Store errors map to statuses as they do on the standard routes:
   `query_events` raised `ChannelNotFoundError`, so the response is a 404.
   Raise `InvalidPayloadError` from a handler for a 400.
4. The decorator records a `StoreEndpointSpec` on the function.
   `channel_resource` copies it into a package's channel metadata, so the
   [hub](packages.md#publish-to-the-lllm-hub) can list the route next to
   the standard ones.

| Handler parameter | Receives |
| --- | --- |
| `store` | The store the app serves |
| `body` | The parsed JSON body; `None` for `GET` and `DELETE`, or a body that is not JSON |
| A path parameter's name | That path parameter |
| `params` | The query parameters as a dict of strings; for a repeated key, the last value wins |
| Anything else | Its default; a parameter without one fails every request with a 500 `TypeError` |

The decorators take
`(path, *, name=None, scope="store", description="", tags=())`. `name`
defaults to the function's name and `description` to its docstring; both
appear in the OpenAPI docs. `scope` is an `EndpointScope`:
`"store"`, `"channel"`, `"subscription"`, `"artifact"`, or `"snapshot"`. It
says what the route is about and does not change routing. Handlers may be
`async`.

`create_app` checks the endpoints when it builds the app and raises
`ValueError` if two share a name or a method and path, or if one would
shadow a standard route such as `GET /channels/{name}`. A function without
a decorator is skipped. `sssn serve` and
`lllm serve PACKAGE --resource channels.NAME` serve the standard routes
only; serve custom endpoints from your own app module, as in
[Serve a store](#serve-a-store), or from a package service
([Packages and refs](packages.md#serve-a-packages-channels)).

## Securing a store

!!! warning "The store server has no authentication"
    Anyone who can reach the port can read and write every channel. Keep it
    on `127.0.0.1`, or put it behind a gateway that checks who is calling.

`create_app` returns a plain FastAPI app, so you can add a middleware that
checks every request, as you would in any FastAPI app. Clients send their
credentials with `headers=` (or `auth=`):

```python title="token_store.py"
import asyncio

import httpx
from fastapi.responses import JSONResponse

from sssn import AsyncRemoteStore, LocalStore, RemoteStoreError, create_app

TOKEN = "s3cret"  # in production, read it from the environment
app = create_app(LocalStore(".lllm/network"))


@app.middleware("http")
async def require_token(request, call_next):  # (1)!
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
        return JSONResponse({"detail": "Invalid token."}, status_code=401)
    return await call_next(request)


async def main():
    transport = httpx.ASGITransport(app=app)  # (2)!
    store = AsyncRemoteStore(
        "https://store.internal",
        headers={"Authorization": f"Bearer {TOKEN}"},  # (3)!
        transport=transport,
    )
    await store.create_channel({"name": "orders"})
    print([channel.name for channel in await store.list_channels()])
    #> ['orders']

    anonymous = AsyncRemoteStore(
        "https://store.internal", transport=transport
    )
    try:
        await anonymous.list_channels()
    except RemoteStoreError as error:
        print(error.status_code, error.message)
        #> 401 Invalid token.


asyncio.run(main())
```

1. The middleware runs before every route, the standard ones and your own.
   LLLM's [serving guide](https://lllm.one/serving/#authentication) shows
   the same check for tactic services.
2. Only for this example: requests go to the app in this process. Against
   a running server, pass the URL alone.
3. `headers` go with every request. `RemoteStore` takes the same
   arguments, and `auth=` takes an httpx authentication instead, such as
   `httpx.BasicAuth(user, password)`.

A store behind a gateway that checks tokens works the same way. For TLS
settings, such as a private certificate authority, pass a transport that
carries them: `transport=httpx.HTTPTransport(verify=context)`, with an
`ssl.SSLContext` as `context`.
