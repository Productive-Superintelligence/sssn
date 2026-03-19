# Example · Request–Response

A synchronous call-and-reply pattern over two `PassthroughChannel`s, with correlation IDs to match replies to their requests.

This is how SSSN implements RPC-style communication between systems without any framework coupling.

---

## Pattern overview

```
Requester                    Responder
   │                            │
   │──write(request_channel)──►│
   │     correlation_id=X       │
   │                            │── process ──
   │                            │
   │◄─write(response_channel)──│
   │     correlation_id=X       │
   │                            │
   ▼ poll response_channel      ▼
     until correlation_id=X
```

---

## Using the built-in helper

`sssn.infra.helpers` provides `request_via_channel()` which handles correlation ID generation, writing the request, and polling for the reply:

```python
import asyncio
from sssn.channels.passthrough import PassthroughChannel
from sssn.infra.helpers import request_via_channel

async def main():
    request_ch  = PassthroughChannel(id="compute-request",  name="Compute Request")
    response_ch = PassthroughChannel(id="compute-response", name="Compute Response")

    await request_ch.start()
    await response_ch.start()

    # --- Responder (runs in the background) ---
    async def responder():
        while True:
            reqs = await request_ch.read("compute-service", limit=10)
            for req in reqs:
                result = req.content.data["a"] + req.content.data["b"]
                import time, uuid
                from sssn.core.channel import ChannelMessage, GenericContent
                reply = ChannelMessage(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    sender_id="compute-service",
                    content=GenericContent(data={"result": result}),
                    correlation_id=req.correlation_id,  # Echo back the correlation ID
                )
                await response_ch.write("compute-service", reply, direct=True)
            await asyncio.sleep(0.05)

    responder_task = asyncio.create_task(responder())

    # --- Requester ---
    response = await request_via_channel(
        request_channel=request_ch,
        response_channel=response_ch,
        sender_id="client-a",
        data={"a": 7, "b": 35},
        timeout=5.0,
    )

    if response:
        print(f"7 + 35 = {response.content.data['result']}")  # → 42
    else:
        print("Request timed out")

    responder_task.cancel()

asyncio.run(main())
```

---

## Building it manually

The helper is thin — here's the equivalent hand-rolled version to illustrate the full pattern:

```python
import asyncio, time, uuid
from sssn.core.channel import ChannelMessage, GenericContent
from sssn.channels.passthrough import PassthroughChannel

async def call(
    request_ch: PassthroughChannel,
    response_ch: PassthroughChannel,
    sender_id: str,
    payload: dict,
    timeout: float = 10.0,
) -> dict | None:
    corr_id = uuid.uuid4().hex

    # Build and send request
    request = ChannelMessage(
        id=str(uuid.uuid4()),
        timestamp=time.time(),
        sender_id=sender_id,
        content=GenericContent(data=payload),
        correlation_id=corr_id,
        reply_to=response_ch.id,
    )
    await request_ch.write(sender_id, request, direct=True)

    # Poll for matching reply
    deadline = time.monotonic() + timeout
    last_msg_id = None

    while time.monotonic() < deadline:
        kw = {"after": last_msg_id} if last_msg_id else {}
        msgs = await response_ch.read(sender_id, limit=20, **kw)
        for msg in msgs:
            if msg.correlation_id == corr_id:
                return msg.content.data
            last_msg_id = msg.id
        await asyncio.sleep(0.05)

    return None  # Timeout
```

---

## Typed request/response with MessageContent

For production use, define typed payloads to get validation and IDE support:

```python
from sssn.core.channel import MessageContent

class ComputeRequest(MessageContent):
    a: float
    b: float
    operation: str = "add"

class ComputeResponse(MessageContent):
    result: float
    error: str | None = None
```

The responder validates the request type:

```python
from pydantic import ValidationError

async def responder():
    while True:
        reqs = await request_ch.read("compute-service", limit=10)
        for req in reqs:
            try:
                req_data = ComputeRequest.model_validate(req.content.model_dump())
                if req_data.operation == "add":
                    result = req_data.a + req_data.b
                elif req_data.operation == "mul":
                    result = req_data.a * req_data.b
                else:
                    raise ValueError(f"Unknown operation: {req_data.operation}")
                content = ComputeResponse(result=result)
            except (ValidationError, ValueError) as e:
                content = ComputeResponse(result=0, error=str(e))

            reply = ChannelMessage(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                sender_id="compute-service",
                content=content,
                correlation_id=req.correlation_id,
            )
            await response_ch.write("compute-service", reply, direct=True)
        await asyncio.sleep(0.05)
```

---

## Multiple concurrent requests

The correlation ID pattern handles concurrent requests safely — each requester waits for its own `correlation_id`:

```python
async def main():
    # ... setup channels and start responder ...

    # Fire 10 requests concurrently
    tasks = [
        request_via_channel(
            request_ch, response_ch,
            sender_id="client",
            data={"a": i, "b": i * 2},
            timeout=5.0,
        )
        for i in range(10)
    ]
    responses = await asyncio.gather(*tasks)
    for i, resp in enumerate(responses):
        print(f"{i} + {i*2} = {resp.content.data['result']}")
```
