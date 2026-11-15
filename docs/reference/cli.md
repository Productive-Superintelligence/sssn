# CLI

SSSN's CLI runs as `sssn` and as `lllm network`; the two are the same command,
and `lllm network` is always available because `sssn` depends on `lllm-core`.
`--store DIR` (default `.lllm/network`) goes before the subcommand, and the
folder is created if it does not exist. Every command prints one JSON object
per line; errors print a message and exit with status 2.

Create and inspect channels:

```bash
sssn --store .lllm/network create-channel events --schema demo.Event --metadata '{"owner":"demo"}'
sssn --store .lllm/network channels
sssn --store .lllm/network get-channel events
```

Store paths passed to `--store` must be non-empty and unpadded.

Append and query events:

```bash
sssn append events '{"text":"hello"}' --kind message --source demo
sssn append events '{"text":"child"}' --schema demo.Event --metadata '{"role":"child"}' --correlation-id corr-1 --parent-id <event-id>
sssn query-events events --limit 10
sssn get-event <event-id>
```

Subscriptions:

```bash
sssn create-subscription events --id worker --kind message
sssn pull-subscription worker --limit 10
sssn get-subscription worker
```

Artifacts and snapshots:

```bash
sssn write-artifact 'hello' --media-type text/plain --event-id <event-id>
sssn get-artifact <artifact-id>
sssn read-artifact <artifact-id>
sssn put-snapshot latest '{"status":"ok"}' --source-event-id <event-id>
sssn get-snapshot latest
```

Serve (needs the `server` extra):

```bash
sssn serve --host 127.0.0.1 --port 7700
```

The same commands through LLLM:

```bash
lllm network create-channel events
lllm network --store ../other/.lllm/network channels
```

| Command | Arguments and options |
| --- | --- |
| `channels` | |
| `create-channel NAME` | `--schema`, `--form` (default `log`), `--description`, `--metadata JSON` |
| `get-channel NAME` | |
| `append CHANNEL PAYLOAD_JSON` | `--kind` (default `event`), `--source`, `--schema`, `--timestamp`, `--metadata JSON`, `--correlation-id`, `--parent-id ID` (repeatable) |
| `query-events CHANNEL` | `--after-cursor` (default 0), `--limit` (default 100), `--kind` |
| `get-event ID` | |
| `create-subscription CHANNEL` | `--id`, `--consumer`, `--batch-size` (default 100), `--kind` |
| `get-subscription ID` | |
| `pull-subscription ID` | `--limit` |
| `write-artifact DATA` | `--encoding text\|base64`, `--channel`, `--media-type`, `--metadata JSON`, `--event-id ID` (repeatable) |
| `get-artifact ID` | prints metadata |
| `read-artifact ID` | `--encoding text\|base64`; prints the payload |
| `put-snapshot NAME VALUE_JSON` | `--channel`, `--schema`, `--source-event-id`, `--metadata JSON` |
| `get-snapshot NAME` | |
| `serve` | `--host` (default `127.0.0.1`), `--port` (default `7700`), `--log-level` |

The other `lllm` commands, such as `lllm serve` for packages with channels,
are documented at [lllm.one](https://lllm.one/reference/cli/).
