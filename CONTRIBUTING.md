# Contributing To SSSN

SSSN is the protocol and service layer for semantic channels, built on
[LLLM](https://github.com/Productive-Superintelligence/lllm). It depends on
`lllm-core` and plugs into the `lllm` command as `lllm network`.

## Development Setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev,docs]"
```

SSSN needs `lllm-core` 0.4 or newer. Until that release is on PyPI, install it
from LLLM's main branch first:

```bash
.venv/bin/python -m pip install "lllm-core @ git+https://github.com/Productive-Superintelligence/lllm@main"
```

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/mkdocs build --strict
```

## Layout

| Path | What lives there |
| --- | --- |
| `sssn/core/` | Channel, event, subscription, artifact, and snapshot models and errors. Imports no store, server, or client. |
| `sssn/stores/` | `LocalStore`, the SQLite/filesystem backend. |
| `sssn/server/`, `sssn/client/` | The FastAPI store server, custom endpoint metadata, and the HTTP clients. |
| `sssn/processing.py` | `TacticProcessor`, which runs LLLM tactics over channels. |
| `sssn/resolver.py`, `sssn/resources.py` | `lllm://` channel refs, and metadata for LLLM packages and the hub. |
| `sssn/cli.py` | The `sssn` command, also `lllm network`. |
| `docs/` | sssn.one, the docs site, deployed to Firebase Hosting by `.github/workflows/docs.yml`. |

## Design Rules

- Keep `Channel` as the stable top-level resource.
- Keep databases, brokers, object stores, feeds, graph stores, and local
  filesystems behind the `Channel` protocol.
- Keep local SQLite/filesystem behavior deterministic for tests.
- Keep store-specific behavior behind store implementations.
- Keep default FastAPI endpoints portable and custom endpoints metadata-driven.
- Build on LLLM's public modules only (`lllm.protocol`,
  `lllm.protocol.refs`, `lllm.protocol.validation`, `lllm.hub`). LLLM must
  never need SSSN: it imports SSSN only for channel resources.
- Keep `lllm.hub`'s copy of the channel forms equal to `sssn.ChannelForm`
  (`tests/test_lllm.py` checks it).
- `sssn` and `lllm network` are one CLI with one default store,
  `.lllm/network`.
- Every user-facing behavior needs a test, and every docs snippet should run.
