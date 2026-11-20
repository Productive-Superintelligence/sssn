"""Core semantic channel resources."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from lllm.protocol.validation import copy_boundary_value

from .errors import InvalidPayloadError

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

    name: StrictStr
    schema_ref: StrictStr | None = Field(default=None, alias="schema")
    form: ChannelForm = "log"
    description: StrictStr = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str | None:
        return self.schema_ref

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "metadata", copy_boundary_value(self.metadata))

    @model_validator(mode="after")
    def _validate_name(self) -> "Channel":
        _validate_segment(self.name, "channel.name")
        return self


class Event(BaseModel):
    """Timestamped semantic record in a channel."""

    id: StrictStr = Field(default_factory=lambda: str(uuid.uuid4()))
    cursor: int | None = None
    channel: StrictStr
    timestamp: float = Field(default_factory=time.time)
    source: StrictStr | None = None
    kind: StrictStr = "event"
    payload: Any = None
    schema_ref: StrictStr | None = Field(default=None, alias="schema")
    metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: StrictStr | None = None
    parent_ids: tuple[StrictStr, ...] = Field(default_factory=tuple)

    @property
    def schema(self) -> str | None:
        return self.schema_ref

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "payload", copy_boundary_value(self.payload))
        _set_model_attr(self, "metadata", copy_boundary_value(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Event":
        _validate_segment(self.id, "event.id")
        _validate_segment(self.channel, "event.channel")
        _validate_token(self.kind, "event.kind")
        if self.correlation_id is not None:
            _validate_token(self.correlation_id, "event.correlation_id")
        for parent_id in self.parent_ids:
            _validate_segment(parent_id, "event.parent_ids")
        return self


class Artifact(BaseModel):
    """Larger payload stored by reference."""

    id: StrictStr = Field(default_factory=lambda: str(uuid.uuid4()))
    channel: StrictStr | None = None
    path: StrictStr
    media_type: StrictStr = "application/octet-stream"
    size: int
    sha256: StrictStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_ids: tuple[StrictStr, ...] = Field(default_factory=tuple)

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "metadata", copy_boundary_value(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Artifact":
        _validate_segment(self.id, "artifact.id")
        _validate_optional_segment(self.channel, "artifact.channel")
        for event_id in self.event_ids:
            _validate_segment(event_id, "artifact.event_ids")
        return self


class Snapshot(BaseModel):
    """Latest state or materialized view."""

    name: StrictStr
    channel: StrictStr | None = None
    timestamp: float = Field(default_factory=time.time)
    value: Any = None
    schema_ref: StrictStr | None = Field(default=None, alias="schema")
    source_event_id: StrictStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str | None:
        return self.schema_ref

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "value", copy_boundary_value(self.value))
        _set_model_attr(self, "metadata", copy_boundary_value(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Snapshot":
        _validate_segment(self.name, "snapshot.name")
        _validate_optional_segment(self.channel, "snapshot.channel")
        _validate_optional_segment(self.source_event_id, "snapshot.source_event_id")
        return self


class Subscription(BaseModel):
    """Consumer cursor over one channel."""

    id: StrictStr = Field(default_factory=lambda: str(uuid.uuid4()))
    channel: StrictStr
    cursor: int = 0
    consumer: StrictStr | None = None
    batch_size: int = 100
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        _set_model_attr(self, "filters", copy_boundary_value(self.filters))
        _set_model_attr(self, "metadata", copy_boundary_value(self.metadata))

    @model_validator(mode="after")
    def _validate_identity(self) -> "Subscription":
        _validate_segment(self.id, "subscription.id")
        _validate_segment(self.channel, "subscription.channel")
        if self.consumer is not None:
            _validate_token(self.consumer, "subscription.consumer")
        return self


# Outside any model, "constants" writes NaN and infinity as the literals NaN
# and Infinity, which json_value then refuses. A model's own config governs
# everything inside it.
_VALUES = TypeAdapter(Any, config=ConfigDict(ser_json_inf_nan="constants"))

# What a record holds, written in JSON mode as sssn 0.2.0 wrote it: outside a
# model's typed float fields, NaN and infinity become None.
_RECORD_VALUES = TypeAdapter(Any, config=ConfigDict(ser_json_inf_nan="null"))

# SSSN's own records, what a store returns.
RECORD_CLASSES = (Channel, Event, Artifact, Snapshot, Subscription)


def json_value(value: Any) -> Any:
    """Return ``value`` as JSON data: exactly the JSON Pydantic writes for it.

    A Pydantic model is written by its own JSON serialization, which writes
    NaN and infinity as null unless the model chooses otherwise, such as
    ``ser_json_inf_nan="strings"`` (Pydantic 2.8+), a validator, or a
    serializer. Outside any
    model, tuples and sets become lists (deques and iterators too, on
    Pydantic versions that can serialize them), dates become strings, and a
    NaN or an infinity raises ``InvalidPayloadError``, since JSON cannot
    represent it. A value Pydantic cannot serialize raises
    ``InvalidPayloadError`` from Pydantic's error. A string value with a lone
    surrogate is kept, as a JSON escape, as sssn 0.2.0 kept it, with four
    exceptions: a dict key holding one is refused (as in 0.2.0); Pydantic
    replaces each one in a model's typed dict key with three U+FFFD, one per
    UTF-8 byte; a high surrogate directly followed by a low one comes back
    as the character the pair encodes (U+D83D U+DE00 becomes U+1F600), as in
    0.2.0; and in a value holding one, a NaN or infinity in a model's typed
    float field is refused, while one in an Any or dict field is written as
    null.
    """

    try:
        text = json_text(_VALUES, value)
    except Exception as exc:
        raise InvalidPayloadError(f"Value is not JSON serializable: {exc}") from exc
    return parse_json(text)


def json_text(adapter: TypeAdapter[Any], value: Any) -> str | bytes:
    """Return the JSON text ``adapter`` writes for ``value``.

    A lone surrogate, which Pydantic's JSON refuses, is written as sssn 0.2.0
    wrote it. Any other failure raises as serialization raised it.
    """

    try:
        return adapter.dump_json(value)
    except ValueError as exc:
        if "UnicodeEncodeError" not in str(exc):
            raise
        # A lone surrogate, which UTF-8 cannot hold, as in a file name
        # decoded with surrogateescape: Python's json escapes it. In this
        # rare path a NaN inside a model is refused rather than written as
        # null.
        return json.dumps(adapter.dump_python(value, mode="json"))


def parse_json(text: str | bytes) -> Any:
    """Parse JSON text, refusing NaN and Infinity with InvalidPayloadError."""

    try:
        return json.loads(text, parse_constant=_refuse_non_finite)
    except ValueError as exc:  # such as an int too long for Python's json
        raise InvalidPayloadError(f"Value is not JSON serializable: {exc}") from exc


def record_json(
    content: Any,
    *,
    default: Callable[[Any], Any] | None = None,
    ensure_ascii: bool = False,
) -> str:
    """Write records a store returned (one, or a list), or JSON data holding
    them, as strict JSON that cannot fail on what a store holds.

    Records are written by ``record_data``, so a non-finite timestamp goes
    out as "inf", "-inf", or "nan", which a float field reads back. Any
    other NaN or infinity, which only a row written before sssn 0.2.1 or a
    value built in memory can hold, goes out as null, as 0.2.0 wrote it, and
    a lone surrogate as a JSON escape. ``default`` writes anything else, as
    for ``json.dumps``, and a NaN in what it returns is null too.
    ``ensure_ascii`` writes all non-ASCII text as escapes, for an output that
    cannot encode it.
    """

    data = _records(content)
    if default is not None:
        default = _nulling(default)
    try:
        return dumps_json(
            data, allow_nan=False, default=default, ensure_ascii=ensure_ascii
        )
    except ValueError as exc:
        # Python's json, which refuses the number rather than write NaN.
        if "Out of range float" not in str(exc):
            raise
    # Only now, since it is rare: a NaN in a model's typed float field, which
    # JSON mode leaves a float, or in a value built in memory.
    return dumps_json(
        _null_non_finite(data),
        allow_nan=False,
        default=default,
        ensure_ascii=ensure_ascii,
    )


# The \uXXXX escapes of the lone surrogates, U+D800 to U+DFFF.
_SURROGATE_ESCAPES = {code: f"\\u{code:04x}" for code in range(0xD800, 0xE000)}


def dumps_json(
    value: Any,
    *,
    allow_nan: bool,
    default: Callable[[Any], Any] | None = None,
    ensure_ascii: bool = False,
) -> str:
    """Write ``value`` as compact JSON text that encodes to UTF-8.

    Text stays readable: only a lone surrogate, which UTF-8 cannot encode,
    is written as its ``\\uXXXX`` escape. A raw surrogate can only stand in
    a string literal, so the escaped text is the same JSON. With
    ``ensure_ascii``, all non-ASCII text is escaped, as ``json.dumps`` does.
    """

    text = json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        allow_nan=allow_nan,
        separators=(",", ":"),
        default=default,
    )
    if ensure_ascii:
        return text
    try:
        # At C speed, and it fails only where a lone surrogate stands: the
        # slower rewrite runs only then.
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = text.translate(_SURROGATE_ESCAPES)
    return text


def record_data(record: Any) -> dict[str, Any]:
    """Return one of SSSN's records as data ``record_json`` writes.

    A non-finite timestamp becomes "inf", "-inf", or "nan". Text stays as it
    is, so the writer escapes a lone surrogate. Other values, such as the
    payload, are written in Pydantic's JSON mode, by alias, as a store
    stores them: dates and sets become strings and lists, keys strings, a
    model takes its JSON serializers, and NaN outside a model's typed float
    fields becomes None. A value Pydantic cannot write is left to the
    writer's ``default``. An instance of a subclass, such as a custom
    store's record, is written by its own JSON dump, which skips its
    excluded fields and adds its computed ones, and then by the timestamp
    rule.
    """

    fields = type(record).model_fields
    if type(record) not in RECORD_CLASSES:
        data = record.model_dump(mode="json", by_alias=True)
        field = fields.get("timestamp")
        if field is not None:
            key = _field_key("timestamp", field)
            if key in data:
                data[key] = _timestamp(data[key])
        return data
    data = {}
    for name, field in fields.items():
        if field.exclude:
            continue
        value = getattr(record, name)
        if name == "timestamp":
            value = _timestamp(value)
        elif not isinstance(value, (str, int, type(None))):
            try:
                value = _RECORD_VALUES.dump_python(value, mode="json", by_alias=True)
            except (TypeError, ValueError):
                pass  # left to the writer's default, such as jsonable_encoder
        data[_field_key(name, field)] = value
    return data


def _field_key(name: str, field: Any) -> str:
    # The key Pydantic writes a field under by alias.
    return field.serialization_alias or field.alias or name


def _timestamp(value: Any) -> Any:
    # "inf", "-inf", or "nan", which a float field reads back, for a
    # non-finite timestamp, which JSON cannot hold as a number.
    if isinstance(value, float) and not _finite(value):
        return "nan" if value != value else "inf" if value > 0 else "-inf"
    return value


def _finite(number: float) -> bool:
    return number == number and abs(number) != float("inf")  # NaN != NaN


def _null_non_finite(value: Any) -> Any:
    """Return JSON data with each NaN or infinity in it replaced by None."""

    if isinstance(value, float):
        return value if _finite(value) else None
    if isinstance(value, dict):
        return {key: _null_non_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_null_non_finite(item) for item in value]
    return value  # text, an int, or a value left to the writer's default


def _nulling(default: Callable[[Any], Any]) -> Callable[[Any], Any]:
    # A writer's default whose NaN is null too, as jsonable_encoder leaves a
    # float as it is.
    def write(value: Any) -> Any:
        return _null_non_finite(default(value))

    return write


def _records(content: Any) -> Any:
    if isinstance(content, RECORD_CLASSES):
        return record_data(content)
    if isinstance(content, (list, tuple)):
        return [_records(item) for item in content]
    return content


def _refuse_non_finite(constant: str) -> Any:
    raise InvalidPayloadError(
        "Value holds NaN or infinity, which JSON cannot represent."
    )


def _validate_optional_segment(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_segment(value, field_name)


def _validate_segment(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "%" in value
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise ValueError(f"{field_name} must be a non-empty path segment.")


def _validate_token(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "%" in value
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise ValueError(f"{field_name} must be a non-empty token.")


def _set_model_attr(model: BaseModel, name: str, value: Any) -> None:
    object.__setattr__(model, name, value)
