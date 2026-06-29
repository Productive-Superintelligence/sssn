# HTTP API

Portable endpoints:

| Endpoint | Use |
| --- | --- |
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

Custom endpoints mounted with `create_app(..., custom_endpoints=...)` must use unique endpoint names and unique method/path pairs. They cannot shadow reserved SSSN service routes such as `/health`, `/channels/{name}`, `/events/{id}`, `/subscriptions/{id}/pull`, `/artifacts/{id}`, or `/snapshots/{name}`. Endpoint paths, names, and tags must avoid whitespace and percent escapes; paths must also avoid `//` network-path prefixes.
