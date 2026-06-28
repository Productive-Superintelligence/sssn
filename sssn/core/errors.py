"""Stable SSSN errors."""

from __future__ import annotations


class SSSNError(RuntimeError):
    """Base SSSN error."""


class ChannelExistsError(SSSNError):
    """Raised when creating a duplicate channel."""


class ChannelNotFoundError(SSSNError):
    """Raised when a channel does not exist."""


class ArtifactNotFoundError(SSSNError):
    """Raised when an artifact does not exist."""


class SnapshotNotFoundError(SSSNError):
    """Raised when a snapshot does not exist."""


class SubscriptionNotFoundError(SSSNError):
    """Raised when a subscription does not exist."""
