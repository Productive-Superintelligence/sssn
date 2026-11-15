# LLLM Tactic Processor

Goal: consume SSSN events, run each payload through an LLLM tactic, and write
the tactic output back to an analysis channel.

The same flow is available as an executable example at
`examples/lllm_tactic_processor/workflow.py`.

## Prerequisites

```bash
python -m pip install -e ".[dev]"   # brings lllm-core
```

## Files Used

- `examples/lllm_tactic_processor/workflow.py` contains the runnable
  composition.
- `tests/test_examples.py` keeps the example executable.
- `sssn/processing.py` implements `TacticProcessor`.
- `sssn/stores/local.py` provides durable channels and subscription cursors.

## Boundary

SSSN owns the durable data plane: channels, subscriptions, cursors, event
lineage, artifacts, and snapshots. LLLM owns the typed compute boundary.
`TacticProcessor` is the small piece between them.

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
from sssn import Event, LocalStore, TacticProcessor

store = LocalStore(".lllm/network")
store.create_channel({"name": "raw", "schema": "demo.RawMessage"})
store.create_channel({"name": "analysis", "schema": "demo.AnalysisMessage"})
processor = TacticProcessor(
    AnalyzeMessage(),
    store,
    source="raw",
    sink="analysis",
    consumer="lllm_tactic_processor",
    kind="message",
    output_kind="analysis",
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

for output in processor.process():
    print(output.kind, output.payload, output.parent_ids == (raw.id,))
```

```text
analysis {'summary': 'HELLO FROM SSSN', 'length': 15} True
```

The analysis event keeps the raw event as a parent and carries its
`correlation_id`, so downstream services can trace an LLLM result back to the
SSSN input that produced it.

The `lllm_tactic_processor` subscription lives in the store, so the next
`process()` call handles only new events. Processing is at least once: an event
is acknowledged only after its output is written, so an event cut short by an
error or a crash runs again. [Use with LLLM](../guides/lllm.md#run-tactics-over-channels)
covers failures, default consumer names, and async workers.

## Config Refs

When channels come from an LLLM package, keep their local binding in
`.lllm/config.toml`:

```toml
[refs."lllm://demo/events/channels/raw"]
store = ".lllm/network"

[refs."lllm://demo/events/channels/analysis"]
store = ".lllm/network"
```

```python
from lllm import Resolver

store = Resolver.from_config(".").store("lllm://demo/events/channels/raw")
```

`lllm.Resolver` reads tactic refs from the same file, and `sssn.ChannelResolver`
reads only the channel and snapshot refs.

## Verify

```bash
python examples/lllm_tactic_processor/workflow.py
```

Expected output:

```json
{
  "analysis_event_ids": ["..."],
  "raw_event_id": "...",
  "root": "...",
  "tactic": "analyze_message"
}
```

Next, replace the local tactic with a `RemoteTactic` from `lllm.Resolver`
while keeping the SSSN subscription and output-channel shape unchanged.
