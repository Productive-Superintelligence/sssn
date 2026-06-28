# Events, Artifacts, Snapshots

SSSN separates three data shapes:

| Resource | Use |
| --- | --- |
| `Event` | Append-only semantic record in a channel. |
| `Artifact` | Larger payload stored by reference. |
| `Snapshot` | Latest materialized state for a name. |

Events can carry schema refs, kind, source, metadata, correlation IDs, and
parent event IDs. Artifacts can link back to events. Snapshots can point at the
event that produced their current value.
