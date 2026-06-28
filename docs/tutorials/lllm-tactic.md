# LLLM Tactic Processor

Goal: consume SSSN events, run each payload through an LLLM tactic, and write
the tactic output back to an analysis channel.

The same flow is available as an executable example at
`examples/lllm_tactic_processor/workflow.py`.

## Boundary

SSSN owns the durable data plane: channels, subscriptions, cursors, event
lineage, artifacts, and snapshots. LLLM owns the typed compute boundary. The
processor between them should stay small.

## Tactic

```python
from pydantic import BaseModel
from lllm import Tactic


class RawMessage(BaseModel):
    text: str


class AnalysisMessage(BaseModel):
    summary: str
    length: int


class AnalyzeMessage(Tactic[RawMessage, AnalysisMessage]):
    name = "analyze_message"
    input_type = RawMessage
    output_type = AnalysisMessage

    def _run(self, input_value, *, context=None):
        return AnalysisMessage(
            summary=input_value.text.upper(),
            length=len(input_value.text),
        )
```

## Processor

```python
from sssn import Event, LocalStore

store = LocalStore(".sssn")
store.create_channel({"name": "raw", "schema": "demo.RawMessage"})
store.create_channel({"name": "analysis", "schema": "demo.AnalysisMessage"})
subscription = store.create_subscription(
    "raw",
    consumer="lllm_tactic_processor",
    filters={"kind": "message"},
)

raw = store.append_event(
    Event(
        channel="raw",
        source="example",
        kind="message",
        payload={"text": "hello from sssn"},
        correlation_id="episode-1",
    )
)

tactic = AnalyzeMessage()
for event in store.pull_subscription(subscription.id):
    result = tactic.run(event.payload)
    store.append_event(
        Event(
            channel="analysis",
            source="lllm_tactic_processor",
            kind="analysis",
            payload=result.model_dump(),
            correlation_id=event.correlation_id or event.id,
            parent_ids=(event.id,),
        )
    )
```

The analysis event keeps the raw event as a parent, so downstream services can
trace an LLLM result back to the SSSN input that produced it.

## Verify

```bash
python examples/lllm_tactic_processor/workflow.py
```

Expected shape:

```json
{
  "analysis_event_ids": ["..."],
  "raw_event_id": "...",
  "root": "...",
  "tactic": "analyze_message"
}
```
