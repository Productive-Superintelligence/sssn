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

Package helpers:

```python
from sssn import channel_resource, endpoint, snapshot_resource
```

Resource names:

Channel names, event ids, artifact ids, snapshot names, subscription ids, and
channel references must be non-empty path segments. Use names such as `events`,
`latest_analysis`, or `worker-events`; avoid `.`, `..`, `/`, `\`, and `:`.
