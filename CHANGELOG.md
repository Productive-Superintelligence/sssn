# Changelog

## 0.2.1

A bug-fix release. Writes refuse NaN and infinity in plain values instead
of storing `null`, workers pulling one subscription get different events,
remote stores raise the same error classes as `LocalStore`, and the
server and the CLI write strict JSON for everything a `LocalStore` holds,
lone surrogates and 0.2.0's infinite timestamps included. Where a call
now raises or returns something else, the bullet says what 0.2.0 did.
Runtime requirements are unchanged, and `lllm-core` 0.4.0 still works.

**Stores**

- A NaN or infinity in a plain value (at the top level, or in a dict,
  list, tuple, or set) now raises `InvalidPayloadError` and nothing is
  written; 0.2.0's `LocalStore` stored it as `null`. Values are stored as
  exactly the JSON Pydantic writes for them, so inside a Pydantic model
  the model's own JSON decides: `null` by default, or what the model
  chooses, such as `ser_json_inf_nan="strings"`. A NaN or infinity in a
  model's `float` field now reads back as `None` by default, where
  0.2.0's `LocalStore` kept it as NaN or infinity. This covers payloads,
  snapshot values, and metadata, on every store.
- Strings with lone surrogates, such as file names decoded with
  `surrogateescape`, are stored as 0.2.0's `LocalStore` stored them, and
  now also travel over HTTP and print in the CLI. The Stores page lists
  the exceptions; the new one is that, in a value holding such a string,
  a NaN or infinity in a model's `float` field is refused, where 0.2.0
  stored it.
- Writes refuse an event or snapshot `timestamp` that is NaN or infinite
  with `InvalidPayloadError`: `LocalStore`, the remote stores before
  sending, and `POST /events` and `PUT /snapshots/{name}` with a 400.
  0.2.0 stored an infinite timestamp and failed on a NaN one with a raw
  `sqlite3.IntegrityError`. `Event` and `Snapshot` still take any float,
  so a 0.2.0 store with infinite timestamps stays readable.
- `append_event`, `create_channel`, `create_subscription`,
  `write_artifact`, and `put_snapshot` return the record as stored, which
  is what `get_event` and other readers get. 0.2.0's `LocalStore`
  returned the values as passed; now a model payload comes back as a
  dict, a tuple as a list, and a date as a string. Validate a payload
  back into your model where you need one.
- Workers pulling one subscription at once get different events: a pull
  moves the cursor with a compare-and-set, and reads again if another
  pull moved it first. 0.2.0 could give two workers the same events. A
  pull that fails on a `LocalStore` still leaves its events pending. Over
  HTTP the server moves the cursor before it answers, as in 0.2.0, so the
  events of a lost response are not delivered again: plain pulls are at
  most once.
- `create_subscription` with an existing id now also raises
  `SubscriptionExistsError` (409 over HTTP) when `filters` names a kind
  and the subscription filters on another kind or none; 0.2.0 returned
  the subscription with its old filter. Use a new id to change what a
  subscription delivers. `filters` that name no kind (`None`, or `{}` as
  0.2.0 clients send) still return the subscription as it is, and
  `batch_size`, `consumer`, and `metadata` are still not compared. The
  error's message now names the channel and kind filter the id reads,
  where 0.2.0's said "Subscription already exists for a different
  channel".
- Two workers creating one subscription at once both get it, where 0.2.0
  could fail one with `sqlite3.IntegrityError`. To do this,
  `create_subscription` takes the write lock even when the id exists, so
  it can wait behind another writer (and time out with `StoreBusyError`),
  where 0.2.0 only read the row. It also checks `metadata` when the id
  exists: metadata that cannot be stored raises `InvalidPayloadError`,
  where 0.2.0 returned the subscription.
- A call that waits past SQLite's 5-second busy timeout raises the new
  `StoreBusyError`, a `NetworkError` exported from `sssn`. It wrote no
  record, so retry it; a `write_artifact` may already have written its
  file, which the retry reuses. From a `LocalStore` it is also the
  `sqlite3.OperationalError` that 0.2.0 raised, with "database is locked"
  in its message and the SQLite error codes, and its `db_path` names the
  database file. A served store answers it with a 503, and remote stores
  raise it as `StoreBusyError`.
- `write_artifact` takes `bytes`, `bytearray`, `memoryview`, or `str` on
  every store: `LocalStore` now takes text, stored as its UTF-8 bytes,
  and the remote stores now take `bytearray` and `memoryview`; 0.2.0
  refused both with `InvalidPayloadError`. Text that cannot be encoded
  as UTF-8 raises `InvalidPayloadError`; 0.2.0's remote stores raised
  `UnicodeEncodeError` for it with httpx 0.28.
- Artifact files appear whole: new bytes go to a temporary file that
  replaces the target, and bytes the store already holds are not written
  again, so a reader never gets an empty or partial file. Metadata that
  cannot be stored now raises before the file is written; 0.2.0 wrote
  the file first.

**Remote stores**

- `except ChannelNotFoundError` and the other store error classes now
  catch errors from remote stores: when the server reports a store
  error, the error raised is a `RemoteStoreError` subclass that is also
  an instance of that class. `RemoteStoreError` is now a `NetworkError`
  (still a `RuntimeError`), so an `except NetworkError` clause placed
  before `except RemoteStoreError` now catches every `RemoteStoreError`,
  and a store error class placed before it catches the errors the server
  reported as that class. A `RemoteStoreError` now pickles intact;
  0.2.0's unpickled copy repeated "SSSN server returned HTTP" in its
  text.
- A valid name with `?` or `#` now works over HTTP: names and ids are
  escaped as one URL path segment. 0.2.0 sent `get_channel("what?")` as a
  request for channel `what`.
- `RemoteStore` and `AsyncRemoteStore` take `headers=`, sent with every
  request (such as a bearer token), and `auth=`, any httpx
  authentication. `ChannelResolver.client()` and `async_client()` pass
  both on.
- Request bodies are encoded as `LocalStore` stores values. A Pydantic
  model or a date in a payload, metadata, or snapshot value is sent in
  its JSON form (0.2.0 raised `TypeError` unless it came inside a
  `Channel`, `Event`, or `Snapshot` object), and a lone surrogate as an
  escape (0.2.0 raised `UnicodeEncodeError` with httpx 0.28). A value
  that cannot be stored raises `InvalidPayloadError` before sending: NaN
  or infinity, an `Event` or `Snapshot` with a non-finite timestamp, an
  arbitrary object, or an int too long for Python's `json`. 0.2.0 raised
  `TypeError`, `ValueError`, or `PydanticSerializationError` for these,
  or sent a NaN in an `Event`'s or `Snapshot`'s payload, value, or
  metadata as `null`. These are plain `InvalidPayloadError`s, not
  `RemoteStoreError`s.
- A plain FastAPI error body, such as `{"detail": "Invalid token."}`,
  now fills `RemoteStoreError.message`, which 0.2.0 left `None`.
- Creating a `RemoteStore` or `AsyncRemoteStore` without httpx raises
  `ImportError` with `pip install "sssn[client]"` in its message; 0.2.0
  failed with a bare `ModuleNotFoundError` on the first call.

**Serving**

- A request waiting on SQLite no longer holds up the server: the store
  app runs synchronous store methods and custom endpoint handlers in a
  worker thread, and awaits async ones. These can run in several threads
  at once, so a store or handler you write must be thread-safe, as
  `LocalStore` is, or async. An async store, such as an
  `AsyncRemoteStore` in front of another server, can now be served, and
  `create_app` replaces only a `None` store with `LocalStore()`, not any
  falsy one.
- A custom store gets different calls: `PUT /snapshots/{name}` passes
  `put_snapshot` a dict of snapshot fields instead of a `Snapshot`, and a
  pull without `limit` now calls `get_subscription` first and passes
  `pull_subscription` an explicit `limit`. A record subclass whose JSON
  dump is not a dict, which 0.2.0's standard routes answered with a 500,
  is written as it is.
- A request returns at most 10,000 events; 0.2.0 had no cap. A larger
  `limit` on `GET /events` or on a pull is a 400 `InvalidPayloadError`; a
  pull without `limit` returns up to the subscription's `batch_size`,
  capped at 10,000; and `POST /subscriptions` caps a new subscription's
  `batch_size` at 10,000 (an existing one comes back unchanged).
  `LocalStore` itself has no cap.
- JSON responses are strict and UTF-8, with a lone surrogate as a
  `\uXXXX` escape (0.2.0 answered 500). A non-finite timestamp, such as
  an infinite one in a store written by 0.2.0, goes out as `"inf"` or
  `"-inf"` (`"nan"` for NaN), which SSSN's clients read back as the
  float; 0.2.0 sent `null`, which its clients refused as an invalid
  response, so a remote pull lost its batch. Any other NaN or infinity,
  such as a 0.2.0 store's NaN in a model field, goes out as `null`, as
  in 0.2.0.
- Every route, `GET /channels` included, answers an error with the JSON
  error body and its status, and `StoreBusyError` with a 503; 0.2.0's
  `GET /channels` answered any failure with a plain-text 500. When the
  served store is a `RemoteStore` or `AsyncRemoteStore`, a store error
  from the server behind it keeps that server's status and type, another
  4xx (such as a 401) passes through with its status, and anything else
  is a 500; 0.2.0 answered 500 for all of them. `PUT /snapshots/{name}`
  answers an invalid name or field with a 400 `InvalidPayloadError`
  instead of a 500.
- `create_app` raises `ValueError` when it builds the app for a custom
  endpoint it cannot serve: a function without an `@endpoint` decorator,
  which 0.2.0 skipped, or a handler parameter without a default that is
  positional-only or that nothing can fill (0.2.0 failed every request
  with a 500). A parameter filled from an enclosing mount's path, such as
  `/tenants/{tenant}/network`, is still passed, but now needs a default.
  `*args` and `**kwargs` now receive nothing instead of failing every
  request.
- A custom endpoint's result is encoded as 0.2.0 encoded it, with
  FastAPI's `jsonable_encoder`, except that SSSN's records returned
  directly or inside lists, tuples, dicts, or dataclasses are written as
  the standard routes write them; a record inside a Pydantic model is
  written by that model's JSON dump, a non-finite timestamp as `null`.
  Any NaN or infinity left goes out as `null` and a lone surrogate as an
  escape, with a 200; 0.2.0 answered both with a 500.

**TacticProcessor**

- A result holding NaN or infinity outside a model, as in a dict or a
  dataclass's `float` field, now fails the event with
  `InvalidPayloadError`, where 0.2.0 stored `null`: `errors="raise"`
  raises and keeps the event pending, and `errors="record"` writes an
  error event. Results are still written by their type's own Pydantic
  schema (a model by its own serializer), now under the stores' JSON
  rule, so inside a model NaN follows the model's JSON: `null` by
  default, as 0.2.0 stored it, or what the model chooses, such as `"NaN"`
  with `ser_json_inf_nan="strings"`, where 0.2.0 stored `null`. A NaN that
  Pydantic infers, as in an `Any` field, inside a model held by a
  dataclass or NamedTuple result can now fail the event too, where 0.2.0
  stored `null`; the Processing page has the details.
- A result that cannot become JSON, such as an arbitrary object or a
  model whose serializer fails, now fails with `InvalidPayloadError` on
  every sink. 0.2.0 raised Pydantic's error, such as
  `PydanticSerializationError`, for such a model, and for any such result
  with a remote sink, so recorded error events now name the new type.
- Default consumer names may hold `?` and `#`, now that remote stores
  escape them (0.2.0 raised `ValueError`); only whitespace still needs
  `consumer=`.

**CLI**

- Records print as the server writes them: a lone surrogate as an escape
  (0.2.0 crashed, and `pull-subscription` lost the rest of its batch),
  and a 0.2.0 store's infinite timestamp as `"inf"` or `"-inf"` (0.2.0
  printed `null`).
- On a stdout that is not UTF, such as a Windows code page in a pipe,
  records print every non-ASCII character as a `\u` escape, even ones the
  code page has; 0.2.0 printed them as they are and crashed with
  `UnicodeEncodeError` on any the code page lacks. There,
  `read-artifact --encoding text` exits with status 2 and suggests
  `--encoding base64` when it cannot print the text, instead of a
  traceback.
- A command that times out writing to a locked store exits with status 2
  and prints the `StoreBusyError` message, instead of a
  `sqlite3.OperationalError` traceback.

**Docs**

- The docs are reorganized by task: Get started, a Guide from channels
  and events to packages and refs, two complete examples, and an API
  reference whose Python part is generated from the code. Nearly all of
  their Python examples run as tests.
- Stores explains how values are stored, with the NaN and lone-surrogate
  rules, and what pulls guarantee; Subscriptions says that workers can
  share a subscription with plain pulls, and when an existing id
  conflicts; Processing says how results are written and which fail.
- Over HTTP and the HTTP API reference cover the 10,000-event cap, the
  503, a served `RemoteStore`'s errors, thread safety, and how responses
  and custom endpoint results are written. "Securing a store" shows a
  token check with `headers=` in place of a custom transport, and the
  examples catch store errors by class instead of comparing `error_type`.

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
