# HTTP API

`create_app(store)` (and `sssn serve`) exposes a store over these portable
endpoints. [Over HTTP](../http.md) shows how to serve a store and call it
from Python.

| Endpoint | Use |
| --- | --- |
| `GET /health` | Liveness check; returns `{"ok": true}`. |
| `POST /channels` | Create a channel. |
| `GET /channels` | List channels. |
| `GET /channels/{name}` | Read one channel. |
| `POST /events` | Append an event. |
| `GET /events?channel=...` | Query events. |
| `GET /events/{id}` | Read one event. |
| `POST /subscriptions` | Create a subscription. |
| `GET /subscriptions/{id}` | Read subscription cursor and metadata. |
| `POST /subscriptions/{id}/pull` | Pull pending events. |
| `POST /artifacts` | Write artifact data. |
| `GET /artifacts/{id}` | Read artifact payload bytes. |
| `GET /artifacts/{id}/metadata` | Read artifact metadata only. |
| `PUT /snapshots/{name}` | Write latest state. |
| `GET /snapshots/{name}` | Read latest state. |

Request bodies and query parameters:

| Endpoint | Body or query |
| --- | --- |
| `POST /channels` | `name`, `schema`, `form`, `description`, `metadata` |
| `POST /events` | `channel`, `payload`, `kind`, `source`, `schema`, `metadata`, `correlation_id`, `parent_ids`, optional `id` and `timestamp`; returns the event with its `cursor` |
| `GET /events` | `?channel=...&after_cursor=0&limit=100&kind=...`; events oldest first; `limit` is at most 10,000 |
| `POST /subscriptions` | `channel`, `id`, `consumer`, `batch_size` (capped at 10,000 for a new subscription), `filters`, `metadata`; returns the existing subscription if the id is taken, unless it reads another `channel` or `filters` names another kind (a 409); `filters` that name no kind, such as `{}`, keep the subscription's filter |
| `POST /subscriptions/{id}/pull` | `?limit=...`, at most 10,000; without one, the subscription's `batch_size`, capped at 10,000; moves the cursor past the returned events |
| `POST /artifacts` | `data`, `encoding` (`text` or `base64`), `channel`, `media_type`, `metadata`, `event_ids` |
| `PUT /snapshots/{name}` | `value`, `channel`, `timestamp`, `schema`, `source_event_id`, `metadata`; replaces any previous value |

Any store can hold a string with a lone surrogate, sent as a JSON escape.
A store written by sssn 0.2.0 can also hold an infinite timestamp, sent as
`"inf"` or `"-inf"`, and other NaN or infinite numbers, sent as `NaN` or
`Infinity` as Python's `json` module writes them. Strict JSON parsers
reject these, and a pull moves the cursor before the client parses the
response.

FastAPI also serves the OpenAPI schema at `/openapi.json` and interactive docs
at `/docs`. The server has no authentication.

## Errors

Errors come back in one envelope, with the error class name as `type`:

```json
{
  "detail": {
    "error": {
      "type": "ChannelNotFoundError",
      "message": "Channel not found: missing"
    }
  }
}
```

| Status | When |
| --- | --- |
| 400 | `InvalidPayloadError`, other `NetworkError`s, and request bodies that fail validation (reported as `InvalidPayloadError`). A served `RemoteStore` is different; see below. |
| 404 | `ChannelNotFoundError`, `EventNotFoundError`, `SubscriptionNotFoundError`, `ArtifactNotFoundError`, `SnapshotNotFoundError`. |
| 409 | `ChannelExistsError`, `EventExistsError` (an event id that is taken), `SubscriptionExistsError`. |
| 503 | `StoreBusyError`: another process kept the store locked past SQLite's busy timeout; retry the request. |
| 500 | Anything else, with the exception's class name and message. |

When the served store is a `RemoteStore`, a store error from the server
behind it keeps that server's status and type, another client error (4xx)
from it passes through with its status as a `RemoteStoreError`, and
anything else is a 500.

## Custom endpoints

Custom endpoints mounted with `create_app(..., custom_endpoints=...)` must be functions decorated with `@endpoint.get` (or `post`, `put`, `patch`, `delete`), with unique endpoint names and unique method/path pairs; `create_app` raises `ValueError` otherwise. They cannot shadow reserved SSSN service routes such as `/health`, `/channels/{name}`, `/events/{id}`, `/subscriptions/{id}/pull`, `/artifacts/{id}`, or `/snapshots/{name}`. Endpoint paths, names, and tags must avoid whitespace and percent escapes; paths must also avoid `//` network-path prefixes. Handler parameters are bound by name:

| Parameter | Receives |
| --- | --- |
| `store` | The served store |
| `body` | The parsed JSON body; `None` for `GET` and `DELETE`, or a body that is not JSON |
| A path parameter's name | That path parameter, also one from the path of an enclosing mount, such as `/tenants/{tenant}/network` (give such a parameter a default) |
| `params` | The query parameters as a dict of strings; for a repeated key, the last value wins |
| Anything else | Its default; a parameter without one makes `create_app` raise `ValueError` |

The handler's return value is the response body, JSON-encoded. A
`NetworkError` it raises maps to a status as on the portable routes. See
[Custom endpoints](../http.md#custom-endpoints) for an example.
