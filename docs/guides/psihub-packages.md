# PsiHub Packages

SSSN does not own `psi.toml`, but it can export channel and snapshot metadata
for PsiHub.

```python
from sssn import Channel, Snapshot, channel_resource, snapshot_resource

channel = channel_resource(Channel(name="events", schema="demo.schemas:Event"))
latest = snapshot_resource(
    Snapshot(name="latest", channel="events", schema="demo.schemas:Event")
)
```

Manifest shape:

```toml
[channels.events]
schema = "event_payload"
form = "log"

[snapshots.latest]
schema = "event_payload"
channel = "events"
```
