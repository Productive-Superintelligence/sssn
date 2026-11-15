# Python API

Everything below imports from the top-level `sssn` package. `sssn.__version__`
is the installed version.

Core imports:

```python
from sssn import (
    Artifact,
    Channel,
    ChannelForm,
    Event,
    LocalStore,
    Snapshot,
    Subscription,
)
```

`ChannelForm` is the `Literal` type of the channel forms; see
[Channels](../concepts/channels.md#channel-forms).

Clients:

```python
from sssn import AsyncRemoteStore, RemoteStore, RemoteStoreError
```

`RemoteStore` and `AsyncRemoteStore` call a served store with the `LocalStore`
methods. Server errors raise `RemoteStoreError` (`status_code`, `error_type`,
`message`, `detail`).

Serving:

```python
from sssn import EndpointScope, StoreEndpointSpec, create_app, endpoint
```

`create_app(store=None, *, custom_endpoints=())` returns a FastAPI app for a
store (`LocalStore(".lllm/network")` by default); it needs the `server` extra.

Processing:

```python
from sssn import TacticProcessor
```

`TacticProcessor(tactic, store, *, source, sink=None, consumer=None, kind=None, output_kind="result", errors="raise")`
runs an LLLM tactic over a channel; `process(limit=None)` and
`aprocess(limit=None)` return the sink events they wrote. See
[Use with LLLM](../guides/lllm.md#run-tactics-over-channels).

Refs and local config:

```python
from sssn import ChannelRef, ChannelRefError, ChannelResolver, ResolvedChannelRef
```

`ChannelResolver.from_config(path)` reads shared `.lllm/config.toml` bindings
and loads only `/channels/` and `/snapshots/` refs. Use `local_store(ref)` for
local `store` or `path` bindings, and `client(ref)` or `async_client(ref)` for
HTTP `url` bindings. `LocalStore` roots and resolver config paths must be
non-empty and unpadded.

Package helpers:

```python
from sssn import channel_resource, endpoint, snapshot_resource
from sssn.resources import open_package_store
```

`channel_resource` and `snapshot_resource` return the metadata the LLLM hub
indexes. `open_package_store(manifest, *, store=None)` opens an LLLM package's
store (`<package>/.lllm/network`) and creates its declared channels.

Errors:

```python
from sssn import (
    ArtifactNotFoundError,
    ChannelExistsError,
    ChannelNotFoundError,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    NetworkError,
    SnapshotNotFoundError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
```

Every store error subclasses `NetworkError`, a `RuntimeError`. `ChannelRefError`
is a `NetworkError` and a `ValueError`. See
[Local Store](../guides/local-store.md#error-shape) for when each is raised.

Resource names:

Channel names, event ids, artifact ids, snapshot names, subscription ids, and
channel references must be non-empty path segments. Use names such as `events`,
`latest_analysis`, or `worker-events`; avoid percent escapes, `.`, `..`, `/`,
`\`, and `:`.
