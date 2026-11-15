# LLLM Tactic Processor

This example shows SSSN and LLLM composed through their intended boundary:

- SSSN owns channels, subscriptions, cursors, and event lineage.
- LLLM owns the typed tactic that transforms one event payload.
- `TacticProcessor` reads raw events and writes tactic outputs as analysis
  events.

Run it from a workspace where `sssn` is installed (it brings `lllm-core`):

```bash
python examples/lllm_tactic_processor/workflow.py
```
