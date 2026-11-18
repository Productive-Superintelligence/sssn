# Installation

SSSN needs Python 3.10 or later. It is one package, `sssn`, built on
`lllm-core`, the base of [LLLM](https://lllm.one/install/):

```bash
pip install sssn
```

or with uv:

```bash
uv add sssn
```

`pip install "lllm-core[network]"` installs the same thing from the LLLM
side. The base package depends only on `lllm-core` and Pydantic (plus
`tomli` on Python 3.10). It has the models, `LocalStore`,
`TacticProcessor`, the ref resolver, and the `sssn` command, which is all
you need to work with a store on one machine.

## Extras

| Extra | Adds | Install it for |
| --- | --- | --- |
| `server` | FastAPI, Uvicorn | serving a store with `sssn serve` or `create_app` ([Over HTTP](http.md)) |
| `client` | httpx | calling a served store with `RemoteStore` and `AsyncRemoteStore` |
| `all` | both of the above | |

```bash
pip install "sssn[server,client]"
```

Without the `server` extra, `sssn serve` stops with
`Install sssn[server] to serve stores (pip install 'sssn[server]')` and
exits with status 2.

SSSN runs any LLLM tactic, and plain tactics such as the ones in these docs
need nothing more. Tactics whose agents call models need LLLM's `native`
extra:

```bash
pip install sssn "lllm-core[native]"
```

## Check the install

```python title="check_install.py"
from sssn import LocalStore

store = LocalStore()  # (1)!
store.create_channel({"name": "smoke-test"})
store.append_event({"channel": "smoke-test", "payload": "SSSN works."})
print(store.query_events("smoke-test")[0].payload)
#> SSSN works.
```

1. With no argument, the store lives in `.lllm/network` under the current
   folder: the same store the `sssn` command uses.

The command line reads the same folder:

```bash
sssn channels    # one line of JSON per channel: {"name":"smoke-test",...}
```

## The command line

Installing SSSN adds two commands that are the same program: `sssn` and
`lllm network`. Because `sssn` depends on `lllm-core`,
`lllm network` is always available once `sssn` is installed. SSSN
registers it with an entry point in its `pyproject.toml`:

```toml
[project.entry-points."lllm.commands"]
network = "sssn.cli"
```

Both commands default to the store in `.lllm/network`, so they work on the
same events:

```bash
sssn create-channel inbox --description "Support messages."
sssn append inbox '{"text": "Checkout is down"}' --kind ticket
lllm network query-events inbox    # the event appended above
lllm --help                        # lists network next to the core commands
```

`--store DIR`, given before the subcommand, picks another folder. In an
environment that has `lllm-core` but not `sssn`, `lllm network` prints
`lllm network needs the sssn package: pip install sssn` and exits with
status 2. Every subcommand is listed in the [CLI reference](api/cli.md).

## Upgrading

**From `lllm.network`.** LLLM 0.3 shipped this code as `lllm.network`. In
LLLM 0.4 that module is a deprecated alias: it imports `sssn`, issues a
`DeprecationWarning`, and keeps old import paths working. Replace
`from lllm.network import ...` with `from sssn import ...`; the names are
the same.

**From SSSN 0.1.** Some classes were renamed, with no aliases kept:

| SSSN 0.1 | SSSN 0.2 |
| --- | --- |
| `SSSNError` | `NetworkError` |
| `SSSNClient`, `AsyncSSSNClient` | `RemoteStore`, `AsyncRemoteStore` |
| `SSSNClientError` | `RemoteStoreError` |
| `SSSNRef`, `SSSNRefError` | `ChannelRef`, `ChannelRefError` |
| `SSSNResolver`, `ResolvedSSSNRef` | `ChannelResolver`, `ResolvedChannelRef` |
| `sssn.integrations` | `sssn.resources` |
| `psi://` refs in `.psi/config.toml` | `lllm://` refs in `.lllm/config.toml` |

The default store moved from `.sssn/` to `.lllm/network/`. To keep an old
store, move `.sssn/sssn.sqlite` to `.lllm/network/network.sqlite` and
`.sssn/artifacts/` to `.lllm/network/artifacts/`. The
[changelog](https://github.com/Productive-Superintelligence/sssn/blob/main/CHANGELOG.md)
lists every change.

## From source

```bash
git clone https://github.com/Productive-Superintelligence/sssn
cd sssn
pip install -e ".[all,dev,docs]"
pytest
```
