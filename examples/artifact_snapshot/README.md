# Artifact Snapshot

This example shows a small local-store workflow:

- append a semantic event,
- write an artifact linked to that event,
- update a `latest` snapshot with the materialized state.

```python
from sssn import LocalStore
from examples.artifact_snapshot.workflow import run_workflow

result = run_workflow(LocalStore(".sssn"))
```
