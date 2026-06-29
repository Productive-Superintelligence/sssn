# CLI

Create and inspect channels:

```bash
sssn --store .sssn create-channel events --schema demo.Event --metadata '{"owner":"demo"}'
sssn --store .sssn channels
sssn --store .sssn get-channel events
```

Store paths passed to `--store` must be non-empty and unpadded.

Append and query events:

```bash
sssn --store .sssn append events '{"text":"hello"}' --kind message --source demo
sssn --store .sssn append events '{"text":"child"}' --schema demo.Event --metadata '{"role":"child"}' --correlation-id corr-1 --parent-id <event-id>
sssn --store .sssn query-events events --limit 10
sssn --store .sssn get-event <event-id>
```

Subscriptions:

```bash
sssn --store .sssn create-subscription events --id worker --kind message
sssn --store .sssn pull-subscription worker --limit 10
sssn --store .sssn get-subscription worker
```

Artifacts and snapshots:

```bash
sssn --store .sssn write-artifact 'hello' --media-type text/plain --event-id <event-id>
sssn --store .sssn get-artifact <artifact-id>
sssn --store .sssn read-artifact <artifact-id>
sssn --store .sssn put-snapshot latest '{"status":"ok"}' --source-event-id <event-id>
sssn --store .sssn get-snapshot latest
```

Serve:

```bash
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```
