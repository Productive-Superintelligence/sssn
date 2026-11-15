"""SSSN: protocol and service layer for semantic channels, built on LLLM."""

from .core import (
    Artifact,
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelForm,
    ChannelNotFoundError,
    Event,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    NetworkError,
    Snapshot,
    SnapshotNotFoundError,
    Subscription,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from .stores import LocalStore
from .server import EndpointScope, StoreEndpointSpec, create_app, endpoint
from .client import AsyncRemoteStore, RemoteStore, RemoteStoreError
from .processing import TacticProcessor
from .resources import channel_resource, snapshot_resource
from .resolver import ChannelRef, ChannelRefError, ChannelResolver, ResolvedChannelRef

__version__ = "0.2.0"

__all__ = [
    "Artifact",
    "ArtifactNotFoundError",
    "AsyncRemoteStore",
    "Channel",
    "ChannelExistsError",
    "ChannelForm",
    "ChannelNotFoundError",
    "ChannelRef",
    "ChannelRefError",
    "ChannelResolver",
    "EndpointScope",
    "Event",
    "EventExistsError",
    "EventNotFoundError",
    "InvalidPayloadError",
    "LocalStore",
    "NetworkError",
    "RemoteStore",
    "RemoteStoreError",
    "ResolvedChannelRef",
    "Snapshot",
    "SnapshotNotFoundError",
    "StoreEndpointSpec",
    "Subscription",
    "SubscriptionExistsError",
    "SubscriptionNotFoundError",
    "TacticProcessor",
    "__version__",
    "channel_resource",
    "create_app",
    "endpoint",
    "snapshot_resource",
]
