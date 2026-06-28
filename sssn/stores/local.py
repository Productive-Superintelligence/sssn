"""SQLite/filesystem local SSSN store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from ..core import (
    Artifact,
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    Event,
    InvalidPayloadError,
    Snapshot,
    SnapshotNotFoundError,
    Subscription,
    SubscriptionNotFoundError,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class LocalStore:
    """Boring local SQLite/filesystem backend."""

    def __init__(self, root: str | Path = ".sssn") -> None:
        self.root = Path(root).expanduser().resolve()
        self.artifacts_dir = self.root / "artifacts"
        self.db_path = self.root / "sssn.sqlite"
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_channel(self, channel: Channel | dict[str, Any]) -> Channel:
        value = _model(Channel, channel, "channel")
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
                        _json(value.metadata),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ChannelExistsError(f"Channel already exists: {value.name}") from exc
        return value

    def list_channels(self) -> tuple[Channel, ...]:
        with self._connect() as db:
            rows = db.execute(
                "select name, schema_ref, form, description, metadata from channels order by name"
            ).fetchall()
        return tuple(_channel(row) for row in rows)

    def get_channel(self, name: str) -> Channel:
        with self._connect() as db:
            row = db.execute(
                "select name, schema_ref, form, description, metadata from channels where name = ?",
                (name,),
            ).fetchone()
        if row is None:
            raise ChannelNotFoundError(f"Channel not found: {name}")
        return _channel(row)

    def append_event(self, event: Event | dict[str, Any]) -> Event:
        value = _model(Event, event, "event")
        self.get_channel(value.channel)
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
                    _json(value.payload),
                    value.schema,
                    _json(value.metadata),
                    value.correlation_id,
                    _json(list(value.parent_ids)),
                ),
            )
        return value

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
        with self._connect() as db:
            rows = db.execute(sql, tuple(args)).fetchall()
        return tuple(_event(row) for row in rows)

    def create_subscription(
        self,
        channel: str,
        *,
        consumer: str | None = None,
        batch_size: int = 100,
        filters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Subscription:
        batch_size = _positive_int("batch_size", batch_size)
        self.get_channel(channel)
        sub = _model(
            Subscription,
            {
                "channel": channel,
                "consumer": consumer,
                "batch_size": batch_size,
                "filters": filters if filters is not None else {},
                "metadata": metadata if metadata is not None else {},
            },
            "subscription",
        )
        _subscription_kind(sub.filters)
        with self._connect() as db:
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
                    _json(sub.filters),
                    _json(sub.metadata),
                ),
            )
        return sub

    def pull_subscription(
        self,
        subscription_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        if limit is not None:
            limit = _positive_int("limit", limit)
        sub = self.get_subscription(subscription_id)
        events = self.query_events(
            sub.channel,
            after_cursor=sub.cursor,
            limit=limit if limit is not None else sub.batch_size,
            kind=_subscription_kind(sub.filters),
        )
        if events:
            last_cursor = self._event_cursor(events[-1].id)
            with self._connect() as db:
                db.execute(
                    "update subscriptions set cursor = ? where id = ?",
                    (last_cursor, subscription_id),
                )
        return events

    def get_subscription(self, subscription_id: str) -> Subscription:
        with self._connect() as db:
            row = db.execute(
                """
                select id, channel, cursor, consumer, batch_size, filters, metadata
                from subscriptions where id = ?
                """,
                (subscription_id,),
            ).fetchone()
        if row is None:
            raise SubscriptionNotFoundError(f"Subscription not found: {subscription_id}")
        return Subscription(
            id=row["id"],
            channel=row["channel"],
            cursor=row["cursor"],
            consumer=row["consumer"],
            batch_size=row["batch_size"],
            filters=_loads(row["filters"]),
            metadata=_loads(row["metadata"]),
        )

    def write_artifact(
        self,
        data: bytes,
        *,
        channel: str | None = None,
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
        event_ids: tuple[str, ...] = (),
    ) -> Artifact:
        if channel is not None:
            self.get_channel(channel)
        sha = hashlib.sha256(data).hexdigest()
        artifact = Artifact(
            channel=channel,
            path=f"artifacts/{sha}",
            media_type=media_type,
            size=len(data),
            sha256=sha,
            metadata=metadata or {},
            event_ids=event_ids,
        )
        path = self.root / artifact.path
        path.write_bytes(data)
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
                    _json(artifact.metadata),
                    _json(list(artifact.event_ids)),
                ),
            )
        return artifact

    def read_artifact(self, artifact_id: str) -> bytes:
        with self._connect() as db:
            row = db.execute(
                "select path from artifacts where id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        path = self.root / row["path"]
        if not path.is_file():
            raise ArtifactNotFoundError(f"Artifact payload not found: {artifact_id}")
        return path.read_bytes()

    def put_snapshot(self, snapshot: Snapshot | dict[str, Any]) -> Snapshot:
        value = _model(Snapshot, snapshot, "snapshot")
        if value.channel is not None:
            self.get_channel(value.channel)
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
                    value.name,
                    value.channel,
                    value.timestamp,
                    _json(value.value),
                    value.schema,
                    value.source_event_id,
                    _json(value.metadata),
                ),
            )
        return value

    def get_snapshot(self, name: str) -> Snapshot:
        with self._connect() as db:
            row = db.execute(
                """
                select name, channel, timestamp, value, schema_ref, source_event_id, metadata
                from snapshots where name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            raise SnapshotNotFoundError(f"Snapshot not found: {name}")
        return Snapshot(
            name=row["name"],
            channel=row["channel"],
            timestamp=row["timestamp"],
            value=_loads(row["value"]),
            schema=row["schema_ref"],
            source_event_id=row["source_event_id"],
            metadata=_loads(row["metadata"]),
        )

    def _event_cursor(self, event_id: str) -> int:
        with self._connect() as db:
            row = db.execute("select rowid from events where id = ?", (event_id,)).fetchone()
        if row is None:
            return 0
        return int(row["rowid"])

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

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


def _model(model_type: type[ModelT], value: ModelT | dict[str, Any], label: str) -> ModelT:
    if isinstance(value, model_type):
        return value
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise InvalidPayloadError(f"Invalid {label}: {exc}") from exc


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


def _subscription_kind(filters: dict[str, Any]) -> str | None:
    value = filters.get("kind")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidPayloadError("subscription filter 'kind' must be a non-empty string.")
    return value


def _json(value: Any) -> str:
    try:
        return json.dumps(TypeAdapter(Any).dump_python(value, mode="json"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise InvalidPayloadError(f"Value is not JSON serializable: {exc}") from exc


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)
