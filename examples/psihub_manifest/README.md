# PsiHub Manifest

This example builds channel and snapshot portions of a PsiHub-style manifest
from SSSN `Channel` and `Snapshot` objects.

```python
from examples.psihub_manifest.package_manifest import build_manifest

manifest = build_manifest()
```

SSSN does not publish packages itself. The generated structure is intended to
be copied into `psi.toml` or passed to PsiHub-side tooling that owns validation
and publication.
