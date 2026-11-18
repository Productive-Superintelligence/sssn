# HTTP API

`create_app(store)` (and `sssn serve`) exposes a store over these portable
endpoints:

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
| `GET /events` | `?channel=...&after_cursor=0&limit=100&kind=...`; events oldest first |
| `POST /subscriptions` | `channel`, `id`, `consumer`, `batch_size`, `filters`, `metadata`; returns the existing subscription if the id is taken on the same channel |
| `POST /subscriptions/{id}/pull` | `?limit=...`; moves the cursor past the returned events |
| `POST /artifacts` | `data`, `encoding` (`text` or `base64`), `channel`, `media_type`, `metadata`, `event_ids` |
| `PUT /snapshots/{name}` | `value`, `channel`, `timestamp`, `schema`, `source_event_id`, `metadata`; replaces any previous value |

FastAPI also serves the OpenAPI schema at `/openapi.json` and interactive docs
at `/docs`. The server has no authentication.

## Errors

Errors come back in one envelope, with the error class name as `type`:

```json
{"detail": {"error": {"type": "ChannelNotFoundError", "message": "Channel not found: missing"}}}
```

| Status | When |
| --- | --- |
| 400 | `InvalidPayloadError`, other `NetworkError`s, and request bodies that fail validation (reported as `InvalidPayloadError`). |
| 404 | `ChannelNotFoundError`, `EventNotFoundError`, `SubscriptionNotFoundError`, `ArtifactNotFoundError`, `SnapshotNotFoundError`. |
| 409 | `ChannelExistsError`, `EventExistsError` (an event id that is taken), `SubscriptionExistsError`. |
| 500 | Anything else, with the exception's class name and message. |

## Custom Endpoints

Custom endpoints mounted with `create_app(..., custom_endpoints=...)` must use unique endpoint names and unique method/path pairs. They cannot shadow reserved SSSN service routes such as `/health`, `/channels/{name}`, `/events/{id}`, `/subscriptions/{id}/pull`, `/artifacts/{id}`, or `/snapshots/{name}`. Endpoint paths, names, and tags must avoid whitespace and percent escapes; paths must also avoid `//` network-path prefixes. See [Refs and Packages](../guides/packages.md#custom-endpoints) for how handler parameters are bound.
