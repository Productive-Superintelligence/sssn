# Data Plane

SSSN is not observability. Observability systems explain how software behaves.
SSSN defines the channel protocol and service surface for data that other
systems consume.

The backing implementation can be SQLite, a broker, a database, an object
store, a feed API, a graph store, or a remote service. The public contract stays
centered on `Channel`.

Use SSSN for:

- policy samples,
- analysis results,
- robot state,
- human annotations,
- latest snapshots,
- artifacts linked to semantic events.

Use OpenTelemetry or Logfire for traces, logs, metrics, costs, and runtime
behavior.
