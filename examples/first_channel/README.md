# First Channel Example

This example mirrors `docs/tutorials/first-channel.md`.

It creates one local channel, appends one semantic event, and reads that event
back from the same store.

```python
from sssn import LocalStore

from workflow import run_workflow

result = run_workflow(LocalStore(".sssn"))
print(result["events"][0].payload)
```
