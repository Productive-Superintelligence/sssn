"""Core semantic channel resources."""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChannelForm = Literal[
    "log",
    "queue",
    "topic",
    "blackboard",
    "latest-state",
    "artifact-index",
    "pipeline-edge",
    "database-view",
    "feed",
    "time-series",
    "tree",
    "forum",
    "hub",
]


class Channel(BaseModel):
    """A named semantic data interface."""

    model_config = ConfigDict(frozen=True)

    name: str
    schema_ref: str | None = Field(default=None, alias="schema")
    form: ChannelForm = "log"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str | None:
        return self.schema_ref


class Event(BaseModel):
    """Timestamped semantic record in a channel."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel: str
    timestamp: float = Field(default_factory=time.time)
    source: str | None = None
    kind: str = "event"
    payload: Any = None
    schema_ref: str | None = Field(default=None, alias="schema")
    metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    parent_ids: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def schema(self) -> str | None:
        return self.schema_ref


class Artifact(BaseModel):
    """Larger payload stored by reference."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel: str | None = None
    path: str
    media_type: str = "application/octet-stream"
    size: int
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_ids: tuple[str, ...] = Field(default_factory=tuple)


class Snapshot(BaseModel):
    """Latest state or materialized view."""

    name: str
    channel: str | None = None
    timestamp: float = Field(default_factory=time.time)
    value: Any = None
    schema_ref: str | None = Field(default=None, alias="schema")
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str | None:
        return self.schema_ref


class Subscription(BaseModel):
    """Consumer cursor over one channel."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel: str
    cursor: int = 0
    consumer: str | None = None
    batch_size: int = 100
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
