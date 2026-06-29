"""SSSN: protocol and service layer for semantic channels."""

from .core import (
    Artifact,
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelForm,
    ChannelNotFoundError,
    Event,
    EventNotFoundError,
    InvalidPayloadError,
    SSSNError,
    Snapshot,
    SnapshotNotFoundError,
    Subscription,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from .stores import LocalStore
from .server import EndpointScope, StoreEndpointSpec, create_app, endpoint
from .client import AsyncSSSNClient, SSSNClient, SSSNClientError
from .integrations import channel_resource, snapshot_resource

__version__ = "0.1.0"

__all__ = [
    "Artifact",
    "ArtifactNotFoundError",
    "AsyncSSSNClient",
    "Channel",
    "ChannelExistsError",
    "ChannelForm",
    "ChannelNotFoundError",
    "EndpointScope",
    "Event",
    "EventNotFoundError",
    "InvalidPayloadError",
    "LocalStore",
    "SSSNError",
    "SSSNClient",
    "SSSNClientError",
    "StoreEndpointSpec",
    "Snapshot",
    "SnapshotNotFoundError",
    "Subscription",
    "SubscriptionExistsError",
    "SubscriptionNotFoundError",
    "__version__",
    "channel_resource",
    "create_app",
    "endpoint",
    "snapshot_resource",
]
