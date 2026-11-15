# LLLM Hub Manifest

This example builds the channel and snapshot sections of an LLLM package
manifest (`lllm.toml`) from SSSN `Channel` and `Snapshot` objects.

```python
from examples.hub_manifest.package_manifest import build_manifest

manifest = build_manifest()
```

SSSN does not publish packages itself. The generated structure is intended to
be copied into `lllm.toml`; the LLLM hub tooling (`lllm hub`) owns validation
and publication.
