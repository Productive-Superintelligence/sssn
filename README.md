
<!-- Logo -->


<div align="center">
  <img src="https://raw.githubusercontent.com/Productive-Superintelligence/sssn/main/docs/assets/SSSN_logo_txt.png" alt="SSSN Logo" width="600"/>
  <br>
  <h1>Simple System of Systems Network (SSSN) </h1>
  <h4>A minimal Python framework for building composable, distributed AI agent networks.</h4>
</div>
<p align="center">
  <a href="https://sssn.one">
    <img alt="Docs" src="https://img.shields.io/badge/API-docs-red">
  </a>
  <a href="https://github.com/Productive-Superintelligence/sssn/tree/main/examples">
    <img alt="Examples" src="https://img.shields.io/badge/API-examples-994B00">
  </a>
  <a href="https://pypi.org/project/sssn/">
    <img alt="Pypi" src="https://img.shields.io/pypi/v/sssn.svg">
  </a>
  <a href="https://github.com/Productive-Superintelligence/sssn/blob/main/LICENSE">
    <img alt="GitHub License" src="https://img.shields.io/github/license/Productive-Superintelligence/sssn">
  </a>
</p>


Two abstractions. One graph.

```
System ──writes──► Channel ──reads──► System
```

A **Channel** is a typed, secured, persistent message store.
A **System** is an autonomous agent that owns channels, wires itself to the network, and runs a tick loop.

---

## Install

```bash
pip install sssn
```

Requires Python 3.10+.

---

## Quick start

```python
import asyncio
from sssn.channels.broadcast import BroadcastChannel
from sssn.core.system import BaseSystem

class Sensor(BaseSystem):
    async def setup(self):
        self.readings = BroadcastChannel(id="readings", name="Readings")
        self.add_channel(self.readings)

    async def step(self):
        await self.write_channel("readings", data={"celsius": 22.4})

class Monitor(BaseSystem):
    async def step(self):
        msgs = await self.read_channel("readings")
        for msg in msgs:
            print(msg.content)

async def main():
    sensor  = Sensor(id="sensor",  name="Sensor")
    monitor = Monitor(id="monitor", name="Monitor")
    await sensor.setup()
    sensor.add_subsystem(monitor, channels=["readings"])
    await asyncio.gather(sensor.launch())

asyncio.run(main())
```

---

## Channel types

| Channel | Pattern |
|---------|---------|
| `BroadcastChannel` | Fan-out — every consumer sees every message |
| `WorkQueueChannel` | Competing consumers — each message claimed once |
| `MailboxChannel` | Per-recipient inbox |
| `PeriodicChannel` | Active poll loop for external data sources |
| `DiscoveryChannel` | Service registry with TTL-based expiry |
| `PassthroughChannel` | Base class — inline write, no loop |

---

## Documentation

Full documentation at **[sssn.one](https://sssn.one)**:

- [Concepts](https://sssn.one/concepts/) — Channel, System, Security, Transport
- [Tutorials](https://sssn.one/tutorials/) — Step-by-step from first channel to secured multi-system network
- [Examples](https://sssn.one/examples/) — Data pipeline, request-response, service discovery

---

## Development setup

```bash
git clone https://github.com/Productive-Superintelligence/sssn.git
cd sssn
pip install -e ".[dev]"
pytest
```

Build and preview the docs locally:

```bash
pip install -e ".[docs]"
mkdocs serve          # http://127.0.0.1:8000
mkdocs build --strict # production build → site/
```

---

## Release

```bash
# 1. Bump version in pyproject.toml, then:
python -m build
python -m twine upload dist/*

# 2. Tag and push
git tag -a v0.0.1 -m "Release 0.0.1"
git push origin main --tags
```



<!-- 
git status          # ensure no stray files you don’t want in the sdist
rm -rf dist build *.egg-info    # clean

python -m build     # creates dist/lllm-<version>.tar.gz and .whl

# test locally
python -m venv /tmp/lllm-release
source /tmp/lllm-release/bin/activate
pip install dist/lllm_core-<version>-py3-none-any.whl
python -c "import lllm; print(lllm.__version__)"
deactivate

# upload
python -m twine upload dist/*

# push tag
git tag -a v0.0.1.3 -m "Release 0.0.1.3"
git push origin main --tags 

# update doc
mkdocs build --strict
mkdocs gh-deploy --force --clean


# test doc

# Install deps (one-time)
pip install mkdocs-material mkdocstrings-python


# Live-reload dev server — visit http://127.0.0.1:8000
mkdocs serve

# Strict build (same flags CI uses — catches broken links/anchors)
python -m mkdocs build --strict


-->

