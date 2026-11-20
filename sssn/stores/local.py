"""SQLite/filesystem local SSSN store."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from lllm.protocol.validation import copy_boundary_value

from ..core import (
    Artifact,
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    EventExistsError,
    EventNotFoundError,
    Event,
    InvalidPayloadError,
    Snapshot,
    SnapshotNotFoundError,
    StoreBusyError,
    Subscription,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from ..core.models import json_value

ModelT = TypeVar("ModelT", bound=BaseModel)


class LocalStore:
    """Boring local SQLite/filesystem backend."""

    # Seconds a call waits for another connection's lock: SQLite's default.
    _busy_timeout = 5.0

    def __init__(self, root: str | Path = ".lllm/network") -> None:
        self.root = Path(_path_value(root, "store root")).expanduser().resolve()
        self.artifacts_dir = self.root / "artifacts"
        self.db_path = self.root / "network.sqlite"
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_channel(self, channel: Channel | dict[str, Any]) -> Channel:
        if isinstance(channel, Mapping) and "metadata" in channel:
            channel = {
                **channel,
                "metadata": _optional_mapping("channel.metadata", channel["metadata"]),
            }
        value = _model(Channel, channel, "channel")
        metadata_json = _json(value.metadata)
        try:
            with self._connect() as db:
                db.execute(
                    """
                    insert into channels(name, schema_ref, form, description, metadata)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        value.name,
                        value.schema,
                        value.form,
                        value.description,
                        metadata_json,
                    ),
                )
                # Return the stored form, the one readers get.
                stored = _find_channel(db, value.name)
        except sqlite3.IntegrityError as exc:
            raise ChannelExistsError(f"Channel already exists: {value.name}") from exc
        return stored

    def list_channels(self) -> tuple[Channel, ...]:
        with self._connect() as db:
            rows = db.execute(
                "select name, schema_ref, form, description, metadata from channels order by name"
            ).fetchall()
        return tuple(_channel(row) for row in rows)

    def get_channel(self, name: str) -> Channel:
        _require_segment("channel.name", name)
        with self._connect() as db:
            channel = _find_channel(db, name)
        if channel is None:
            raise ChannelNotFoundError(f"Channel not found: {name}")
        return channel

    def append_event(self, event: Event | dict[str, Any]) -> Event:
        if isinstance(event, Mapping) and "metadata" in event:
            event = {
                **event,
                "metadata": _optional_mapping("event.metadata", event["metadata"]),
            }
        value = _model(Event, event, "event")
        _require_finite("event.timestamp", value.timestamp)
        self.get_channel(value.channel)
        self._require_events(value.parent_ids)
        payload_json = _json(value.payload)
        metadata_json = _json(value.metadata)
        try:
            with self._connect() as db:
                db.execute(
                    """
                    insert into events(
                      id, channel, timestamp, source, kind, payload, schema_ref,
                      metadata, correlation_id, parent_ids
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        value.id,
                        value.channel,
                        value.timestamp,
                        value.source,
                        value.kind,
                        payload_json,
                        value.schema,
                        metadata_json,
                        value.correlation_id,
                        _json(list(value.parent_ids)),
                    ),
                )
                # Return the stored form, the one readers get, with its cursor.
                stored = _find_event(db, value.id)
        except sqlite3.IntegrityError as exc:
            if self._event_cursor(value.id):
                raise EventExistsError(f"Event already exists: {value.id}") from exc
            raise
        return stored

    def query_events(
        self,
        channel: str,
        *,
        after_cursor: int = 0,
        limit: int = 100,
        kind: str | None = None,
    ) -> tuple[Event, ...]:
        after_cursor = _non_negative_int("after_cursor", after_cursor)
        limit = _positive_int("limit", limit)
        self.get_channel(channel)
        if kind is not None:
            _require_token("event.kind", kind)
        with self._connect() as db:
            return _query_events(
                db, channel, after_cursor=after_cursor, limit=limit, kind=kind
            )

    def get_event(self, event_id: str) -> Event:
        _require_segment("event.id", event_id)
        with self._connect() as db:
            event = _find_event(db, event_id)
        if event is None:
            raise EventNotFoundError(f"Event not found: {event_id}")
        return event

    def create_subscription(
        self,
        channel: str,
        *,
        subscription_id: str | None = None,
        consumer: str | None = None,
        batch_size: int = 100,
        filters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Subscription:
        batch_size = _positive_int("batch_size", batch_size)
        self.get_channel(channel)
        subscription_filters = _optional_mapping("subscription.filters", filters)
        subscription_metadata = _optional_mapping("subscription.metadata", metadata)
        payload: dict[str, Any] = {
            "channel": channel,
            "consumer": consumer,
            "batch_size": batch_size,
            "filters": subscription_filters,
            "metadata": subscription_metadata,
        }
        if subscription_id is not None:
            payload["id"] = subscription_id
        sub = _model(Subscription, payload, "subscription")
        kind = _subscription_kind(sub.filters)
        filters_json = _json(sub.filters)
        metadata_json = _json(sub.metadata)
        # Look the id up and insert in one write transaction, so two workers
        # creating the same subscription at once both get it.
        with self._connect(write=True) as db:
            existing = (
                _find_subscription(db, sub.id) if subscription_id is not None else None
            )
            if existing is not None:
                # An existing subscription comes back unchanged, so a worker can
                # create it every time it starts, unless it delivers other
                # events than asked for: another channel, or another kind
                # filter when filters are given. batch_size, consumer, and
                # metadata are not compared.
                existing_kind = _subscription_kind(existing.filters)
                if existing.channel != sub.channel or (
                    filters is not None and existing_kind != kind
                ):
                    raise SubscriptionExistsError(
                        f"Subscription already exists for other events: {sub.id} "
                        f"reads channel {existing.channel!r} with kind filter "
                        f"{existing_kind!r}."
                    )
                return existing
            db.execute(
                """
                insert into subscriptions(id, channel, cursor, consumer, batch_size, filters, metadata)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sub.id,
                    sub.channel,
                    sub.cursor,
                    sub.consumer,
                    sub.batch_size,
                    filters_json,
                    metadata_json,
                ),
            )
            # Return the stored form, the one readers get.
            return _find_subscription(db, sub.id)

    def pull_subscription(
        self,
        subscription_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        if limit is not None:
            limit = _positive_int("limit", limit)
        _require_segment("subscription.id", subscription_id)
        # One write transaction reads the events and moves the cursor past
        # them, so two pulls of one subscription never get the same events.
        with self._connect(write=True) as db:
            sub = _find_subscription(db, subscription_id)
            if sub is None:
                raise SubscriptionNotFoundError(
                    f"Subscription not found: {subscription_id}"
                )
            events = _query_events(
                db,
                sub.channel,
                after_cursor=sub.cursor,
                limit=limit if limit is not None else sub.batch_size,
                kind=_subscription_kind(sub.filters),
            )
            if events:
                db.execute(
                    "update subscriptions set cursor = ? where id = ?",
                    (events[-1].cursor, subscription_id),
                )
        return events

    def get_subscription(self, subscription_id: str) -> Subscription:
        _require_segment("subscription.id", subscription_id)
        with self._connect() as db:
            sub = _find_subscription(db, subscription_id)
        if sub is None:
            raise SubscriptionNotFoundError(f"Subscription not found: {subscription_id}")
        return sub

    def write_artifact(
        self,
        data: bytes | bytearray | memoryview | str,
        *,
        channel: str | None = None,
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
        event_ids: tuple[str, ...] = (),
    ) -> Artifact:
        payload = _artifact_bytes(data)
        artifact_metadata = _optional_mapping("artifact.metadata", metadata)
        artifact_event_ids = _segment_tuple("artifact.event_ids", event_ids)
        if channel is not None:
            self.get_channel(channel)
        self._require_events(artifact_event_ids)
        sha = hashlib.sha256(payload).hexdigest()
        artifact = Artifact(
            channel=channel,
            path=f"artifacts/{sha}",
            media_type=media_type,
            size=len(payload),
            sha256=sha,
            metadata=artifact_metadata,
            event_ids=artifact_event_ids,
        )
        # Encode the metadata before writing the file, so metadata that
        # cannot be stored leaves no file behind.
        metadata_json = _json(artifact.metadata)
        self._write_payload(self._artifact_payload_path(artifact.path), payload)
        with self._connect() as db:
            db.execute(
                """
                insert into artifacts(id, channel, path, media_type, size, sha256, metadata, event_ids)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.channel,
                    artifact.path,
                    artifact.media_type,
                    artifact.size,
                    artifact.sha256,
                    metadata_json,
                    _json(list(artifact.event_ids)),
                ),
            )
            # Return the stored form, the one readers get.
            return _find_artifact(db, artifact.id)

    def read_artifact(self, artifact_id: str) -> bytes:
        _require_segment("artifact.id", artifact_id)
        with self._connect() as db:
            row = db.execute(
                "select path from artifacts where id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        path = self._artifact_payload_path(row["path"])
        if not path.is_file():
            raise ArtifactNotFoundError(f"Artifact payload not found: {artifact_id}")
        return path.read_bytes()

    def get_artifact(self, artifact_id: str) -> Artifact:
        _require_segment("artifact.id", artifact_id)
        with self._connect() as db:
            artifact = _find_artifact(db, artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        return artifact

    def put_snapshot(
        self,
        snapshot: Snapshot | Mapping[str, Any] | str | None = None,
        value: Any = None,
        *,
        name: str | None = None,
        channel: str | None = None,
        timestamp: float | None = None,
        schema: str | None = None,
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Snapshot:
        """Write a snapshot given as a model, a dict, or a name and value.

        ``put_snapshot(snapshot)`` takes a ``Snapshot`` or a dict of snapshot
        fields; ``put_snapshot(name, value, ...)`` stores ``value`` exactly as
        given, unless it is a ``Snapshot`` whose fields are used under that
        name. ``snapshot=`` and ``name=`` also work as keywords. Field
        arguments that are not ``None`` override, and ``None`` fields are unset.
        The remote clients take the same arguments.
        """
        snapshot = _snapshot_fields(
            snapshot,
            value,
            name=name,
            channel=channel,
            timestamp=timestamp,
            schema=schema,
            source_event_id=source_event_id,
            metadata=metadata,
        )
        if isinstance(snapshot, Mapping) and "metadata" in snapshot:
            snapshot = {
                **snapshot,
                "metadata": _optional_mapping(
                    "snapshot.metadata",
                    snapshot["metadata"],
                ),
            }
        record = _model(Snapshot, snapshot, "snapshot")
        _require_finite("snapshot.timestamp", record.timestamp)
        if record.channel is not None:
            self.get_channel(record.channel)
        if record.source_event_id is not None:
            self._require_events((record.source_event_id,))
        value_json = _json(record.value)
        metadata_json = _json(record.metadata)
        with self._connect() as db:
            db.execute(
                """
                insert into snapshots(name, channel, timestamp, value, schema_ref, source_event_id, metadata)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(name) do update set
                  channel = excluded.channel,
                  timestamp = excluded.timestamp,
                  value = excluded.value,
                  schema_ref = excluded.schema_ref,
                  source_event_id = excluded.source_event_id,
                  metadata = excluded.metadata
                """,
                (
                    record.name,
                    record.channel,
                    record.timestamp,
                    value_json,
                    record.schema,
                    record.source_event_id,
                    metadata_json,
                ),
            )
            # Return the stored form, the one readers get.
            return _find_snapshot(db, record.name)

    def get_snapshot(self, name: str) -> Snapshot:
        _require_segment("snapshot.name", name)
        with self._connect() as db:
            snapshot = _find_snapshot(db, name)
        if snapshot is None:
            raise SnapshotNotFoundError(f"Snapshot not found: {name}")
        return snapshot

    def _event_cursor(self, event_id: str) -> int:
        with self._connect() as db:
            row = db.execute("select rowid from events where id = ?", (event_id,)).fetchone()
        if row is None:
            return 0
        return int(row["rowid"])

    def _require_events(self, event_ids: tuple[str, ...]) -> None:
        for event_id in event_ids:
            self.get_event(event_id)

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Open a connection for one transaction, committed when the block ends.

        With ``write=True`` the transaction takes the write lock before its
        first read, so no other connection can write between what the block
        reads and what it writes. A lock that another connection holds past
        the busy timeout raises ``StoreBusyError``. The connection is closed
        afterwards.
        """
        db = sqlite3.connect(self.db_path, timeout=self._busy_timeout)
        db.row_factory = sqlite3.Row
        try:
            with db:
                if write:
                    db.execute("begin immediate")
                yield db
        except sqlite3.OperationalError as exc:
            if not _is_locked(exc):
                raise
            raise StoreBusyError(
                f"Store is busy: another connection kept {self.db_path} locked "
                f"for more than {self._busy_timeout:g} seconds. Try again."
            ) from exc
        finally:
            db.close()

    def _write_payload(self, path: Path, payload: bytes) -> None:
        """Put an artifact's bytes in ``path``, the file named by their SHA-256.

        Equal bytes share one file, so a file that exists with the right size
        already holds them and is left alone. Otherwise the bytes go to a
        temporary file that replaces ``path`` in one step, so a reader never
        sees a file that is half written.
        """
        try:
            if path.stat().st_size == len(payload):
                return
        except FileNotFoundError:
            pass
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "xb") as file:
                file.write(payload)
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _artifact_payload_path(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if not _is_relative_to(target, self.artifacts_dir):
            raise ArtifactNotFoundError("Artifact payload path is outside artifact storage.")
        return target

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                create table if not exists channels (
                  name text primary key,
                  schema_ref text,
                  form text not null,
                  description text not null,
                  metadata text not null
                );
                create table if not exists events (
                  id text primary key,
                  channel text not null,
                  timestamp real not null,
                  source text,
                  kind text not null,
                  payload text,
                  schema_ref text,
                  metadata text not null,
                  correlation_id text,
                  parent_ids text not null
                );
                create table if not exists subscriptions (
                  id text primary key,
                  channel text not null,
                  cursor integer not null,
                  consumer text,
                  batch_size integer not null,
                  filters text not null,
                  metadata text not null
                );
                create table if not exists artifacts (
                  id text primary key,
                  channel text,
                  path text not null,
                  media_type text not null,
                  size integer not null,
                  sha256 text,
                  metadata text not null,
                  event_ids text not null
                );
                create table if not exists snapshots (
                  name text primary key,
                  channel text,
                  timestamp real not null,
                  value text,
                  schema_ref text,
                  source_event_id text,
                  metadata text not null
                );
                """
            )


def _channel(row: sqlite3.Row) -> Channel:
    return Channel(
        name=row["name"],
        schema=row["schema_ref"],
        form=row["form"],
        description=row["description"],
        metadata=_loads(row["metadata"]),
    )


def _event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        cursor=row["rowid"],
        channel=row["channel"],
        timestamp=row["timestamp"],
        source=row["source"],
        kind=row["kind"],
        payload=_loads(row["payload"]),
        schema=row["schema_ref"],
        metadata=_loads(row["metadata"]),
        correlation_id=row["correlation_id"],
        parent_ids=tuple(_loads(row["parent_ids"])),
    )


def _find_channel(db: sqlite3.Connection, name: str) -> Channel | None:
    row = db.execute(
        "select name, schema_ref, form, description, metadata from channels where name = ?",
        (name,),
    ).fetchone()
    return None if row is None else _channel(row)


def _find_event(db: sqlite3.Connection, event_id: str) -> Event | None:
    row = db.execute(
        """
        select rowid, id, channel, timestamp, source, kind, payload, schema_ref,
               metadata, correlation_id, parent_ids
        from events
        where id = ?
        """,
        (event_id,),
    ).fetchone()
    return None if row is None else _event(row)


def _find_artifact(db: sqlite3.Connection, artifact_id: str) -> Artifact | None:
    row = db.execute(
        """
        select id, channel, path, media_type, size, sha256, metadata, event_ids
        from artifacts where id = ?
        """,
        (artifact_id,),
    ).fetchone()
    return None if row is None else _artifact(row)


def _find_snapshot(db: sqlite3.Connection, name: str) -> Snapshot | None:
    row = db.execute(
        """
        select name, channel, timestamp, value, schema_ref, source_event_id, metadata
        from snapshots where name = ?
        """,
        (name,),
    ).fetchone()
    if row is None:
        return None
    return Snapshot(
        name=row["name"],
        channel=row["channel"],
        timestamp=row["timestamp"],
        value=_loads(row["value"]),
        schema=row["schema_ref"],
        source_event_id=row["source_event_id"],
        metadata=_loads(row["metadata"]),
    )


def _query_events(
    db: sqlite3.Connection,
    channel: str,
    *,
    after_cursor: int,
    limit: int,
    kind: str | None,
) -> tuple[Event, ...]:
    sql = """
        select rowid, id, channel, timestamp, source, kind, payload, schema_ref,
               metadata, correlation_id, parent_ids
        from events
        where channel = ? and rowid > ?
    """
    args: list[Any] = [channel, after_cursor]
    if kind is not None:
        sql += " and kind = ?"
        args.append(kind)
    sql += " order by rowid limit ?"
    args.append(limit)
    return tuple(_event(row) for row in db.execute(sql, tuple(args)).fetchall())


def _find_subscription(
    db: sqlite3.Connection, subscription_id: str
) -> Subscription | None:
    row = db.execute(
        """
        select id, channel, cursor, consumer, batch_size, filters, metadata
        from subscriptions where id = ?
        """,
        (subscription_id,),
    ).fetchone()
    if row is None:
        return None
    return Subscription(
        id=row["id"],
        channel=row["channel"],
        cursor=row["cursor"],
        consumer=row["consumer"],
        batch_size=row["batch_size"],
        filters=_loads(row["filters"]),
        metadata=_loads(row["metadata"]),
    )


def _artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        channel=row["channel"],
        path=row["path"],
        media_type=row["media_type"],
        size=row["size"],
        sha256=row["sha256"],
        metadata=_loads(row["metadata"]),
        event_ids=tuple(_loads(row["event_ids"])),
    )


def _model(model_type: type[ModelT], value: ModelT | dict[str, Any], label: str) -> ModelT:
    if isinstance(value, model_type):
        return value.model_copy(deep=True)
    try:
        return model_type.model_validate(copy_boundary_value(value))
    except ValidationError as exc:
        raise InvalidPayloadError(f"Invalid {label}: {exc}") from exc


def _snapshot_fields(
    snapshot: Any,
    value: Any,
    *,
    name: str | None,
    channel: str | None,
    timestamp: float | None,
    schema: str | None,
    source_event_id: str | None,
    metadata: Any,
) -> Snapshot | dict[str, Any]:
    if snapshot is not None and not isinstance(snapshot, (Snapshot, Mapping)):
        if name is not None:
            raise TypeError("put_snapshot() got multiple values for argument 'name'")
        snapshot, name = None, snapshot
    overrides = {
        key: item
        for key, item in (
            ("name", name),
            ("channel", channel),
            ("timestamp", timestamp),
            ("schema", schema),
            ("source_event_id", source_event_id),
            ("metadata", metadata),
        )
        if item is not None
    }
    if snapshot is None:
        if isinstance(value, Snapshot):
            fields = _snapshot_values(value)
            del fields["name"]
        else:
            fields = {"value": value}
    else:
        if value is not None:
            overrides["value"] = value
        if isinstance(snapshot, Snapshot):
            if not overrides:
                return snapshot
            fields = _snapshot_values(snapshot)
        else:
            fields = snapshot
    return {
        key: item
        for key, item in {**fields, **overrides}.items()
        if item is not None
    }


def _snapshot_values(snapshot: Snapshot) -> dict[str, Any]:
    """A snapshot's fields, keyed as put_snapshot takes them, values not dumped.

    A model in ``value`` or ``metadata`` stays a model, so it is stored in its
    own JSON form, as when the snapshot itself is stored.
    """

    return {
        field.alias or name: getattr(snapshot, name)
        for name, field in Snapshot.model_fields.items()
    }


def _path_value(value: Any, label: str) -> str:
    try:
        text = os.fspath(value)
    except TypeError as exc:
        raise ValueError(f"{label} must be a non-empty path string") from exc
    if not isinstance(text, str) or not text or text != text.strip():
        raise ValueError(f"{label} must be a non-empty path string")
    return text


def _artifact_bytes(value: Any) -> bytes:
    # Text is stored as its UTF-8 bytes, as the remote stores send it.
    if isinstance(value, str):
        try:
            return value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise InvalidPayloadError(
                "artifact data text cannot be encoded as UTF-8."
            ) from exc
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise InvalidPayloadError(
        "artifact data must be bytes, bytearray, memoryview, or str."
    )


def _require_finite(name: str, value: float) -> None:
    # Only writes check this: a store written by sssn 0.2.0 can hold an
    # infinite timestamp, and reading it must keep working.
    if not math.isfinite(value):
        raise InvalidPayloadError(f"{name} must be a finite number.")


def _non_negative_int(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidPayloadError(f"{name} must be an integer.")
    if value < 0:
        raise InvalidPayloadError(f"{name} must be greater than or equal to 0.")
    return value


def _positive_int(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidPayloadError(f"{name} must be an integer.")
    if value < 1:
        raise InvalidPayloadError(f"{name} must be greater than 0.")
    return value


def _require_segment(field_name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "%" in value
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise InvalidPayloadError(f"{field_name} must be a non-empty path segment.")


def _require_token(field_name: str, value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "%" in value
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise InvalidPayloadError(f"{field_name} must be a non-empty token.")


def _segment_tuple(field_name: str, values: Any) -> tuple[str, ...]:
    if (
        values is None
        or isinstance(values, (str, bytes, bytearray))
        or isinstance(values, Mapping)
        or not isinstance(values, Iterable)
    ):
        raise InvalidPayloadError(f"{field_name} must be a list of path segments.")
    result: list[str] = []
    for value in values:
        _require_segment(field_name, value)
        result.append(value)
    return tuple(result)


def _optional_mapping(field_name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise InvalidPayloadError(f"{field_name} must be an object.")
    return copy_boundary_value(value)


def _is_relative_to(path: Path, base_dir: Path) -> bool:
    try:
        path.relative_to(base_dir)
    except ValueError:
        return False
    return True


def _subscription_kind(filters: dict[str, Any]) -> str | None:
    unsupported = sorted(set(filters) - {"kind"})
    if unsupported:
        names = ", ".join(unsupported)
        raise InvalidPayloadError(
            f"subscription filters only support 'kind'; unsupported: {names}"
        )
    value = filters.get("kind")
    if value is None:
        return None
    _require_token("subscription filter 'kind'", value)
    return value


def _is_locked(exc: sqlite3.OperationalError) -> bool:
    # SQLITE_BUSY or SQLITE_LOCKED. Python 3.10 has no error names, but both
    # messages say "locked", as in "database is locked".
    name = getattr(exc, "sqlite_errorname", None) or ""
    return name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")) or "locked" in str(exc)


def _json(value: Any) -> str:
    data = json_value(value)
    try:
        return json.dumps(data, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidPayloadError(f"Value is not JSON serializable: {exc}") from exc


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)
