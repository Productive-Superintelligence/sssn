# Changelog

## 0.2.0

SSSN is its own package again, now built on LLLM. LLLM 0.3 carried this code
as `lllm.network`; SSSN 0.2 is that code, improved there, back under the
`sssn` name. It depends on `lllm-core` (0.4 or newer) for tactics, refs,
validation helpers, and package manifests, and plugs into the `lllm` command.

**LLLM integration**

- `sssn` depends on `lllm-core>=0.4`; `pip install "lllm-core[network]"`
  installs it from the LLLM side. SSSN uses only LLLM's public modules
  (`lllm.protocol`, `lllm.protocol.refs`, `lllm.protocol.validation`).
- Installing `sssn` adds `lllm network` through the `lllm.commands` entry
  point; it is the same CLI as `sssn`, which stays. Usage and error messages
  name the command that ran.
- `TacticProcessor` runs any LLLM tactic over a channel: it reads through a
  named subscription, appends outputs to a sink channel with `parent_ids` and
  `correlation_id`, and works with `LocalStore`, `RemoteStore`, and (with
  `aprocess()`) `AsyncRemoteStore`. Processing is at least once: an event is
  acknowledged only after its output is written. `errors="raise"` retries a
  failing event on the next call; `errors="record"` writes a `kind="error"`
  event and moves on. Default consumers are `<tactic name>-<source>-processor`,
  or `<tactic name>-<source>-<kind>-processor` with a kind filter.
- Refs are LLLM refs: `lllm://org/package/channels/name` (and `snapshots`),
  bound in `.lllm/config.toml`, the file `lllm.Resolver` reads. A binding's
  `store` can name a `[stores.<name>]` table. `ChannelResolver.from_text`
  parses config text in memory.
- Packages are LLLM packages: `channel_resource` and `snapshot_resource` (now
  in `sssn.resources`) produce the metadata the LLLM hub indexes, and
  `sssn.resources.open_package_store(manifest)` opens a package's store with
  its declared channels; `lllm serve PACKAGE --resource channels.NAME` serves
  it. `lllm.hub` keeps a copy of the channel forms, and the tests keep it
  equal to `sssn.ChannelForm`.
- The old `lllm.network` import path is a deprecated alias in LLLM 0.4 that
  imports `sssn`; import `sssn` instead.
- The store app (`create_app`) keeps its store at `app.state.sssn_store` and,
  for code written against `lllm.network`, also at `app.state.network_store`
  (the same object).

**Stores and the HTTP API**

- Appending an event whose id is taken raises `EventExistsError` (409 over
  HTTP) instead of a raw `sqlite3.IntegrityError`.
- `put_snapshot` takes the same arguments on every store:
  `put_snapshot(snapshot=None, value=None, *, name=None, channel=None, ...)`,
  with a `Snapshot`, a dict of snapshot fields, or a name and a value. The
  HTTP clients store a dict value exactly as given; they no longer treat a
  dict with snapshot-field keys as the request body. Fields set to `None`
  count as unset on every store.
- Custom store endpoints get the query string through a `params` argument.
- The FastAPI app reports the package version in its OpenAPI document.

**Renamed** (no aliases are kept)

| SSSN 0.1 | SSSN 0.2 |
| --- | --- |
| `SSSNError` | `NetworkError` |
| `SSSNClient`, `AsyncSSSNClient` | `RemoteStore`, `AsyncRemoteStore` |
| `SSSNClientError` | `RemoteStoreError` |
| `SSSNRef`, `SSSNRefError`, `SSSNResolver`, `ResolvedSSSNRef` | `ChannelRef`, `ChannelRefError`, `ChannelResolver`, `ResolvedChannelRef` |
| `psi://` refs in `.psi/config.toml` | `lllm://` refs in `.lllm/config.toml` |
| store default `.sssn/` with `sssn.sqlite` | `.lllm/network/` with `network.sqlite` |
| `sssn.integrations` (the PsiHub helpers) | `sssn.resources`; `channel_resource` and `snapshot_resource` are still exported from `sssn` |

To keep an SSSN 0.1 store, move `.sssn/sssn.sqlite` to
`.lllm/network/network.sqlite` and `.sssn/artifacts/` to
`.lllm/network/artifacts/`.

**Docs**

- sssn.one is SSSN's own site again, deployed to Firebase Hosting. The header
  switches between LLLM, SSSN, and AAAX, the nav has no Home section (the logo
  leads home), and a new "Use with LLLM" page covers `TacticProcessor`,
  channel packages on the LLLM hub, `lllm network`, and `lllm.Resolver`
  channel refs.

## 0.1.0

- Added the `Channel` centered semantic data model.
- Added local SQLite/filesystem store support.
- Added FastAPI server, sync client, and async client workflows.
- Added events, subscriptions, artifacts, snapshots, and stable errors.
- Added custom channel endpoint metadata and optional PsiHub helpers.
