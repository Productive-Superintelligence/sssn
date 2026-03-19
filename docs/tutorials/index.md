# Tutorials

Five tutorials that build progressively from a single channel to a secured, multi-system network.

| Tutorial | What you'll build | New concepts |
|----------|------------------|--------------|
| [1 · First Channel](01-first-channel.md) | Write and read your first message | `PassthroughChannel`, `read`, `write` |
| [2 · Broadcast Bus](02-broadcast.md) | Fan-out event bus with subscribers | `BroadcastChannel`, `subscribe` |
| [3 · Work Queue](03-work-queue.md) | Competing workers, claim and ack | `WorkQueueChannel`, `exclusive`, `acknowledge`, `nack` |
| [4 · Multi-System](04-multi-system.md) | Umbrella system coordinating subsystems | `BaseSystem`, `add_subsystem`, `launch` |
| [5 · Securing Channels](05-securing-channels.md) | ACL and JWT access control | `ACLSecurity`, `JWTChannelSecurity` |

Each tutorial is self-contained and runnable. Start from the beginning or jump to the topic you need.

!!! tip "Prerequisites"
    Install SSSN before starting:
    ```bash
    pip install sssn
    ```
