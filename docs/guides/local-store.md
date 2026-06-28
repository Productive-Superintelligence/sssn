# Local Store

The local store creates a deterministic directory:

```text
.sssn/
  sssn.sqlite
  artifacts/
```

```python
from sssn import LocalStore

store = LocalStore(".sssn")
```

The store owns channel metadata, event cursors, subscription cursor state,
artifact metadata, artifact payload files, and snapshots.
