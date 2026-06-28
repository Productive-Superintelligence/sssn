# HTTP Client

Goal: use the portable HTTP client against a running store service.

Start the server:

```bash
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```

Call it:

```python
from sssn import SSSNClient

client = SSSNClient("http://127.0.0.1:7700")
client.create_channel({"name": "events", "schema": "demo.Event"})
event = client.append_event(
    {"channel": "events", "kind": "message", "payload": {"text": "hello"}}
)

assert client.get_event(event.id).payload == {"text": "hello"}
```

Next, use subscriptions for restartable worker loops.
