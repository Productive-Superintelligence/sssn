# Contributing To SSSN

SSSN is the protocol and service layer for semantic channels in PSI services.

## Development Setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
```

Run:

```bash
.venv/bin/python -m pytest
```

## Design Rules

- Keep `Channel` as the stable top-level resource.
- Keep databases, brokers, object stores, feeds, graph stores, and local
  filesystems behind the `Channel` protocol.
- Keep local SQLite/filesystem behavior deterministic for tests.
- Keep store-specific behavior behind store implementations.
- Keep default FastAPI endpoints portable and custom endpoints metadata-driven.
- Keep PsiHub package metadata optional and integration-scoped.
