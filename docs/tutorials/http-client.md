# HTTP Client

Goal: use the portable HTTP client against a running store service.

## Prerequisites

```bash
python -m pip install -e ".[dev,server]"
```

## Files Used

- `sssn/server/fastapi.py` exposes the portable FastAPI app.
- `sssn/client/http.py` implements `RemoteStore` and `AsyncRemoteStore`.
- `tests/test_http_client.py` verifies the client against the API shape.

## Start The Server

```bash
sssn serve --host 127.0.0.1 --port 7700
```

## Call The Server

```python
from sssn import RemoteStore

client = RemoteStore("http://127.0.0.1:7700")
client.create_channel({"name": "events", "schema": "demo.Event"})
event = client.append_event(
    {"channel": "events", "kind": "message", "payload": {"text": "hello"}}
)

assert client.get_event(event.id).payload == {"text": "hello"}
```

Server errors come back as `RemoteStoreError` with `status_code` and
`error_type`; creating `events` a second time is a 409 `ChannelExistsError`.

## Verify

```bash
python -m pytest tests/test_http_client.py -q
```

Expected output:

```text
... passed
```

Next, use subscriptions for restartable worker loops.
