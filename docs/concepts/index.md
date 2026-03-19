# Concepts

SSSN is built on two abstractions — **Channel** and **System** — and a small set of principles that govern how they compose.

This section explains each abstraction in depth: what it is, what invariants it maintains, and why it is designed the way it is.

---

## Two abstractions, one graph

```
System ──writes──► Channel ──reads──► System
```

A **Channel** is a durable, secured message store. It does not push; it holds. Consumers pull (or subscribe). Producers write.

A **System** is an autonomous agent. It owns channels, wires itself to other systems' channels, and runs a tick loop.

The graph formed by wiring Systems and Channels together is a **holonic network** — a hierarchy where every node can itself be a network.

---

## What to read next

- [Channel](channel.md) — the full consumption interface, `MessageStore`, security checks, lifecycle
- [Channel Types](channel-types.md) — the six built-in channel variants and when to use each
- [System](system.md) — `setup`, `step`, `run`, `launch`, `publish`, subsystem topology
- [Security](security.md) — `OpenSecurity`, `ACLSecurity`, `JWTChannelSecurity`
- [Transport & Client](transport.md) — in-process and HTTP transport, `ChannelClient`
