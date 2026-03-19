from __future__ import annotations

# ---------------------------------------------------------------------------
# Core channel primitives
# ---------------------------------------------------------------------------
from sssn.core.channel import (
    BaseChannel,
    ChannelInfo,
    ChannelMessage,
    GenericContent,
    MessageContent,
    Visibility,
)

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
from sssn.core.security import (
    ACLSecurity,
    ChannelSecurity,
    JWTChannelSecurity,
    OpenSecurity,
)

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
from sssn.core.db import (
    ChannelDBClient,
    FileDBClient,
    SqliteDBClient,
)

# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
from sssn.core.transport import (
    ChannelTransport,
    HttpTransport,
    InProcessTransport,
)

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
from sssn.core.client import ChannelClient

# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
from sssn.core.system import (
    BaseSystem,
    ServiceDescriptor,
    ServiceMethod,
    SystemState,
    expose,
    register,
    system,
)

# ---------------------------------------------------------------------------
# Channel implementations
# ---------------------------------------------------------------------------
from sssn.channels import (
    BroadcastChannel,
    DiscoveryChannel,
    MailboxChannel,
    PassthroughChannel,
    PeriodicSourceChannel,
    WorkQueueChannel,
)

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
from sssn.infra import ChannelServer, request_via_channel

__all__ = [
    # Core
    "MessageContent",
    "GenericContent",
    "ChannelMessage",
    "ChannelInfo",
    "Visibility",
    "BaseChannel",
    # Security
    "ChannelSecurity",
    "OpenSecurity",
    "ACLSecurity",
    "JWTChannelSecurity",
    # DB
    "ChannelDBClient",
    "SqliteDBClient",
    "FileDBClient",
    # Transport
    "ChannelTransport",
    "InProcessTransport",
    "HttpTransport",
    # Client
    "ChannelClient",
    # System
    "SystemState",
    "ServiceMethod",
    "ServiceDescriptor",
    "BaseSystem",
    "register",
    "system",
    "expose",
    # Channels
    "PassthroughChannel",
    "BroadcastChannel",
    "WorkQueueChannel",
    "MailboxChannel",
    "PeriodicSourceChannel",
    "DiscoveryChannel",
    # Infra
    "ChannelServer",
    "request_via_channel",
]
