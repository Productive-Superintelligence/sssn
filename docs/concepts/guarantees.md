# Guarantees & Non-Goals

This page defines the behaviors SSSN intentionally guarantees today, and the ones it does not.

These boundaries matter because SSSN is designed to be small, composable, and extensible. If you need stronger semantics, build them above SSSN or extend the framework explicitly rather than assuming they already exist.

---

## What SSSN guarantees

### 1. Stable local topology semantics

- `add_channel()` connects a channel to the owning system's `ChannelClient`.
- `add_subsystem(..., channels=[...])` wires only the named channels into the subsystem.
- A subsystem does not gain implicit access to channels you did not wire.

This is the core local access model: topology is explicit.

### 2. Message-store semantics are durable but not destructive

- Shared reads are cursor-based and non-destructive.
- Exclusive reads claim messages until they are acknowledged, nacked, or reclaimed.
- Messages stay in the store until host operations or retention policies remove them.

This means SSSN is a durable channel log with claim semantics, not an auto-deleting queue.

### 3. HTTP JWT enforcement is real

- `HttpTransport` requires a Bearer token.
- For `JWTChannelSecurity`, HTTP operations validate signature, expiry, role, and channel scope before dispatching into the channel.
- For `OpenSecurity` and `ACLSecurity`, the Bearer token resolves to a `system_id`, and the channel's normal authorize path applies.

### 4. Lifecycle hooks are resilient by default

- `BaseSystem.run()` catches `step()` exceptions and forwards them to `on_step_error()`.
- `BaseChannel` logs pull/process/db/transport errors and keeps running unless you override that behavior.
- `drain()` stops accepting writes before shutdown.

The default posture is "log and continue", not fail-fast.

### 5. `publish()` only exposes public channels

- `Visibility.PUBLIC` channels receive `HttpTransport` when a system is published.
- `Visibility.PRIVATE` channels stay local even when the parent system is published.
- If a discovery channel is present, `publish()` registers public channels there automatically.

---

## What SSSN does not guarantee

### 1. In-process capability enforcement

Local channel access is not enforced by JWT scope checks. For in-process systems, `JWTChannelSecurity.authorize_*()` allows access and trusts the system topology you built.

If you need strong local mediation, add a proxy/gateway layer or extend the local security model explicitly.

### 2. Exactly-once delivery

`WorkQueueChannel` uses claim, acknowledge, nack, and reclaim semantics. Claimed work can return to the queue if a worker disappears or a claim expires.

Write side effects above SSSN should therefore be idempotent.

### 3. Hard suspend semantics

`BaseSystem.pause()` changes the observable state to `PAUSED`, but the default run loop keeps executing. `resume()` only flips the state back to `RUNNING`.

If you need real suspension, override `run()` or add a stricter lifecycle controller.

### 4. Process isolation or sandboxing

`launch()` runs systems in the same Python process with direct object references for local channels. This is efficient and composable, but it is not a security boundary.

### 5. Automatic crash recovery

SSSN does not persist full system execution state or restart failed systems automatically. Recovery strategy belongs to the application or orchestration layer.

---

## Guidance for higher layers

- Treat topology as the authority model for local systems.
- Treat HTTP transport as the authority model for remote systems.
- Make externally visible actions idempotent.
- Add stricter lifecycle or mediation layers only where your application actually needs them.
