# CLI

Create and inspect channels:

```bash
sssn --store .sssn create-channel events --schema demo.Event
sssn --store .sssn channels
sssn --store .sssn get-channel events
```

Append and query events:

```bash
sssn --store .sssn append events '{"text":"hello"}' --kind message
sssn --store .sssn query-events events --limit 10
sssn --store .sssn get-event <event-id>
```

Subscriptions:

```bash
sssn --store .sssn create-subscription events --id worker --kind message
sssn --store .sssn pull-subscription worker --limit 10
```

Artifacts and snapshots:

```bash
sssn --store .sssn write-artifact 'hello' --media-type text/plain
sssn --store .sssn put-snapshot latest '{"status":"ok"}'
```

Serve:

```bash
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```
