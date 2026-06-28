# Channels

`Channel` is SSSN's center model. A channel is a named semantic data interface
with schema, form, description, and metadata.

```python
from sssn import Channel

channel = Channel(
    name="events",
    schema="demo.schemas:Event",
    form="log",
    description="Local event stream.",
)
```

Common channel forms include `log`, `queue`, `topic`, `latest-state`,
`artifact-index`, and `time-series`. The first backend is intentionally boring:
SQLite metadata plus filesystem artifact payloads.
