# Channel

SSSN's channel protocol is the stable contract for semantic channels. It describes how
services, workers, robots, apps, and agents name data streams, append typed
events, attach artifacts, materialize snapshots, and subscribe to new records.

The protocol does not require one storage engine. SQLite, object stores,
brokers, feeds, graph stores, or hosted services can sit behind the same
channel boundary.

## Design Concept

SSSN channels combine two complementary patterns:

- **Flow.** A channel can behave like a pub/sub stream for ongoing inputs:
  news, articles, time series, robot observations, policy calls, application
  events, or other signals that arrive over time.
- **Blackboard.** A channel can also behave like a shared accumulation surface:
  findings, experiments, artifacts, analyses, snapshots, and derived records
  that distributed agents read from and write back to.

This lineage comes from agent systems for societal analysis and scientific
discovery: SocioDojo uses real-world text and time-series flows for lifelong
analytical agents, while Language Modeling by Language Models organizes
research-agent work around accumulating findings, experiments, literature, code,
and evaluations. SSSN keeps the protocol neutral so the same channel contract
can serve robotics, society, science, business, infrastructure, and other
system-of-systems applications.

<div class="psi-tiles">
  <div class="psi-tile">
    <strong>Channel</strong>
    Named semantic interface with schema, form, description, and metadata.
  </div>
  <div class="psi-tile">
    <strong>Event</strong>
    Append-only record with payload, source, kind, and correlation metadata.
  </div>
  <div class="psi-tile">
    <strong>Artifact</strong>
    Larger payload stored by reference and linked back to semantic records.
  </div>
  <div class="psi-tile">
    <strong>Snapshot</strong>
    Latest materialized state for a channel, name, or derived view.
  </div>
</div>

## Shape

```mermaid
flowchart TD
  P["Producer"] --> C["Channel"]
  C --> E["Events"]
  C --> A["Artifacts"]
  C --> S["Snapshots"]
  E --> U["Subscription"]
  U --> W["Worker"]
  W --> D["Derived channel"]
```

## What The Protocol Owns

- channel, event, artifact, snapshot, and subscription models,
- resource identifiers and portable validation rules,
- event correlation and parent links,
- artifact metadata and payload references,
- snapshot source pointers,
- HTTP service and Python client request shapes.

## What Stays Outside

- the concrete database, broker, object store, or filesystem,
- process launch and orchestration,
- package storage and cards,
- tactic/model execution,
- observability vendor formats.

That split lets a local `LocalStore` and a hosted SSSN service speak the same
language while using different backends.

## Next

- Read [Channels](../concepts/channels.md) for the center model.
- Read [Events, Artifacts, Snapshots](../concepts/events-artifacts-snapshots.md)
  for record shapes.
- Read [Data Plane](../concepts/data-plane.md) for backend ownership.
