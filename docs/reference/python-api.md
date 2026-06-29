# Python API

Core imports:

```python
from sssn import (
    Artifact,
    Channel,
    Event,
    LocalStore,
    Snapshot,
    Subscription,
)
```

Clients:

```python
from sssn import SSSNClient, AsyncSSSNClient
```

Refs and local config:

```python
from sssn import ResolvedSSSNRef, SSSNRef, SSSNRefError, SSSNResolver
```

`SSSNResolver.from_config(path)` reads shared `.psi/config.toml` bindings and
loads only `/channels/` and `/snapshots/` refs. Use `local_store(ref)` for
local `store` or `path` bindings, and `client(ref)` or `async_client(ref)` for
HTTP `url` bindings. `LocalStore` roots and resolver config paths must be
non-empty and unpadded.

Package helpers:

```python
from sssn import channel_resource, endpoint, snapshot_resource
```

Resource names:

Channel names, event ids, artifact ids, snapshot names, subscription ids, and
channel references must be non-empty path segments. Use names such as `events`,
`latest_analysis`, or `worker-events`; avoid percent escapes, `.`, `..`, `/`,
`\`, and `:`.
