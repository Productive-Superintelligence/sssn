# PsiHub Packages

SSSN does not own `psi.toml`, but it can export channel and snapshot metadata
for PsiHub. Treat these helpers as manifest/card adapters: SSSN describes the
data resources, while PsiHub owns validation, publication, downloads, and
generated cards.

## Channel And Snapshot Resources

```python
from sssn import Channel, Snapshot, channel_resource, snapshot_resource

raw = channel_resource(
    Channel(
        name="raw",
        schema="raw_event",
        form="log",
        description="Incoming events.",
    )
)
latest = snapshot_resource(
    Snapshot(name="latest_analysis", channel="raw", schema="analysis_event"),
    description="Latest derived analysis event.",
)
```

Manifest shape:

```toml
[channels.raw]
schema = "raw_event"
form = "log"
description = "Incoming events."

[snapshots.latest_analysis]
schema = "analysis_event"
channel = "raw"
description = "Latest derived analysis event."
```

## Custom Endpoints

Custom endpoint decorators carry route metadata that can be copied into channel
or snapshot resource descriptions. The same decorated callable can also be
mounted on the FastAPI store service with `create_app(..., custom_endpoints=...)`.

```python
from sssn import Channel, channel_resource, endpoint


@endpoint.get(
    "/channels/{name}/tail",
    scope="channel",
    description="Return the most recent events for a channel.",
    tags=("channels",),
)
def channel_tail(store, name: str, limit: int = 20):
    return store.query_events(name, limit=limit)


raw = channel_resource(
    Channel(name="raw", schema="raw_event", form="log"),
    custom_endpoints=[channel_tail],
)
```

The exported resource includes the route in `endpoints`, which lets generated
package cards show domain routes beside the portable channel API:

```json
{
  "name": "raw",
  "schema": "raw_event",
  "form": "log",
  "endpoints": [
    {
      "name": "channel_tail",
      "method": "GET",
      "path": "/channels/{name}/tail",
      "scope": "channel",
      "description": "Return the most recent events for a channel.",
      "tags": ["channels"]
    }
  ]
}
```

## Verify

```bash
python -m pytest tests/test_psihub_integration.py tests/test_examples.py -q
```

Expected output:

```text
... passed
```

Next, use the generated resource dictionaries inside a PsiHub package manifest
owned by PsiHub tooling.
