"""Core semantic channel resources."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "metadata", deepcopy(self.metadata))

    @model_validator(mode="after")
    def _validate_name(self) -> "Channel":
        _validate_segment(self.name, "channel.name")
        return self


class Event(BaseModel):
    """Timestamped semantic record in a channel."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cursor: int | None = None
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

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "payload", deepcopy(self.payload))
        _set_model_attr(self, "metadata", deepcopy(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Event":
        _validate_segment(self.id, "event.id")
        _validate_segment(self.channel, "event.channel")
        return self


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

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "metadata", deepcopy(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Artifact":
        _validate_segment(self.id, "artifact.id")
        _validate_optional_segment(self.channel, "artifact.channel")
        return self


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

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "value", deepcopy(self.value))
        _set_model_attr(self, "metadata", deepcopy(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Snapshot":
        _validate_segment(self.name, "snapshot.name")
        _validate_optional_segment(self.channel, "snapshot.channel")
        return self


class Subscription(BaseModel):
    """Consumer cursor over one channel."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel: str
    cursor: int = 0
    consumer: str | None = None
    batch_size: int = 100
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "filters", deepcopy(self.filters))
        _set_model_attr(self, "metadata", deepcopy(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Subscription":
        _validate_segment(self.id, "subscription.id")
        _validate_segment(self.channel, "subscription.channel")
        return self


def _validate_optional_segment(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_segment(value, field_name)


def _validate_segment(value: str, field_name: str) -> None:
    if not value or value in {".", ".."} or any(ch in value for ch in "/:\\"):
        raise ValueError(f"{field_name} must be a non-empty path segment.")


def _set_model_attr(model: BaseModel, name: str, value: Any) -> None:
    object.__setattr__(model, name, value)
