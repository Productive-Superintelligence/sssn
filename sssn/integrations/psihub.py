"""Small helpers for PsiHub integration.

PsiHub owns package manifests. SSSN only exposes channel and snapshot metadata
in a manifest-friendly shape.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..core import Channel, Snapshot
from ..server.endpoints import endpoint_spec


def channel_resource(
    channel: Channel,
    *,
    custom_endpoints: Sequence[Callable[..., Any]] = (),
) -> dict[str, Any]:
    """Return manifest/card-friendly metadata for a channel."""

    return {
        "name": channel.name,
        "schema": channel.schema,
        "form": channel.form,
        "description": channel.description,
        "metadata": dict(channel.metadata),
        "endpoints": [
            {
                "name": spec.name,
                "method": spec.method,
                "path": spec.path,
                "scope": spec.scope,
                "description": spec.description,
                "tags": list(spec.tags),
            }
            for fn in custom_endpoints
            if (spec := endpoint_spec(fn)) is not None
        ],
    }


def snapshot_resource(
    snapshot: Snapshot,
    *,
    description: str = "",
    custom_endpoints: Sequence[Callable[..., Any]] = (),
) -> dict[str, Any]:
    """Return manifest/card-friendly metadata for a snapshot."""

    return {
        "name": snapshot.name,
        "schema": snapshot.schema,
        "channel": snapshot.channel,
        "description": description,
        "metadata": dict(snapshot.metadata),
        "endpoints": [
            {
                "name": spec.name,
                "method": spec.method,
                "path": spec.path,
                "scope": spec.scope,
                "description": spec.description,
                "tags": list(spec.tags),
            }
            for fn in custom_endpoints
            if (spec := endpoint_spec(fn)) is not None
        ],
    }
