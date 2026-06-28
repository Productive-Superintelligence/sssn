# HTTP Client

Serve a local store:

```bash
sssn --store .sssn serve --port 7700
```

Call it from Python:

```python
from sssn import SSSNClient

client = SSSNClient("http://127.0.0.1:7700")
channel = client.create_channel({"name": "events"})
event = client.append_event({"channel": channel.name, "payload": {"ok": True}})
same_event = client.get_event(event.id)
```

`AsyncSSSNClient` provides the same shape for async code.
