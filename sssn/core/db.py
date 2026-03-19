from __future__ import annotations

import abc
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports for optional heavy dependencies.
# aiosqlite and ChannelMessage are imported at runtime to keep the module
# importable even if aiosqlite is not installed (FileDBClient still works).
# ---------------------------------------------------------------------------


def _import_aiosqlite():
    try:
        import aiosqlite  # noqa: PLC0415
        return aiosqlite
    except ImportError as exc:
        raise ImportError(
            "aiosqlite is required for SqliteDBClient. "
            "Install it with: pip install aiosqlite"
        ) from exc


# We import ChannelMessage inside methods using TYPE_CHECKING guard to avoid
# a circular import — channel.py imports db.py.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sssn.core.channel import ChannelMessage


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ChannelDBClient(abc.ABC):
    """
    Abstract persistence backend for a channel.

    Async, message-aware, time-indexed.  Each concrete implementation maps
    ChannelMessage objects to the underlying storage system.
    """

    @abc.abstractmethod
    async def initialize(self, channel_metadata: dict[str, Any]) -> bool:
        """
        Set up storage for this channel (create tables, directories, etc.).
        Called once in on_start(). Idempotent — safe to call again.
        """
        ...

    @abc.abstractmethod
    async def save(self, message: ChannelMessage) -> bool:
        """Persist a single message. Returns True on success."""
        ...

    @abc.abstractmethod
    async def save_batch(self, messages: list[ChannelMessage]) -> bool:
        """Persist a batch of messages. Returns True if all succeeded."""
        ...

    @abc.abstractmethod
    async def get(self, message_id: str) -> ChannelMessage | None:
        """Retrieve a message by ID, or None if not found."""
        ...

    @abc.abstractmethod
    async def get_range(self, start_time: float, end_time: float) -> list[ChannelMessage]:
        """Retrieve all messages with timestamp in [start_time, end_time]."""
        ...

    @abc.abstractmethod
    async def get_latest(self, limit: int) -> list[ChannelMessage]:
        """Retrieve the most recent `limit` messages, newest first."""
        ...

    @abc.abstractmethod
    async def delete(self, message_ids: list[str]) -> bool:
        """Delete messages by ID. Returns True if all deletions succeeded."""
        ...


# ---------------------------------------------------------------------------
# Shared serialization helpers
# ---------------------------------------------------------------------------


def _msg_to_row(message: ChannelMessage) -> tuple:
    """Flatten a ChannelMessage into a DB row tuple."""
    content_type = type(message.content).__name__
    content_data = message.content.model_dump_json()
    metadata = json.dumps(message.metadata)
    return (
        message.id,
        message.timestamp,
        message.sender_id,
        content_type,
        content_data,
        metadata,
        message.correlation_id,
        message.reply_to,
        message.recipient_id,
    )


def _row_to_msg(row: tuple | dict) -> ChannelMessage:
    """Reconstruct a ChannelMessage from a DB row."""
    from sssn.core.channel import ChannelMessage, GenericContent  # noqa: PLC0415

    if isinstance(row, dict):
        r = row
    else:
        keys = [
            "id", "timestamp", "sender_id", "content_type", "content_data",
            "metadata", "correlation_id", "reply_to", "recipient_id",
        ]
        r = dict(zip(keys, row))

    # Deserialize content: always reconstruct as GenericContent carrying the
    # stored data so the message is always parseable even when the original
    # typed subclass is unavailable.
    raw_content: dict[str, Any] = json.loads(r["content_data"])
    content = GenericContent(data=raw_content)

    metadata: dict[str, Any] = json.loads(r["metadata"]) if r["metadata"] else {}

    return ChannelMessage(
        id=r["id"],
        timestamp=r["timestamp"],
        sender_id=r["sender_id"],
        content=content,
        metadata=metadata,
        correlation_id=r.get("correlation_id"),
        reply_to=r.get("reply_to"),
        recipient_id=r.get("recipient_id"),
    )


# ---------------------------------------------------------------------------
# SqliteDBClient
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id             TEXT    PRIMARY KEY,
    timestamp      REAL    NOT NULL,
    sender_id      TEXT    NOT NULL,
    content_type   TEXT    NOT NULL,
    content_data   TEXT    NOT NULL,
    metadata       TEXT    NOT NULL DEFAULT '{}',
    correlation_id TEXT,
    reply_to       TEXT,
    recipient_id   TEXT
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp);
"""

_INSERT = """
INSERT OR IGNORE INTO messages
    (id, timestamp, sender_id, content_type, content_data,
     metadata, correlation_id, reply_to, recipient_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


class SqliteDBClient(ChannelDBClient):
    """
    SQLite-backed channel persistence via aiosqlite.

    Schema
    ------
    messages(id TEXT PK, timestamp REAL, sender_id TEXT,
             content_type TEXT, content_data TEXT, metadata TEXT,
             correlation_id TEXT, reply_to TEXT, recipient_id TEXT)

    The content_data column stores the Pydantic model as JSON.
    An index on timestamp supports efficient time-range queries.
    """

    def __init__(self, db_path: str | os.PathLike) -> None:
        self._db_path = str(db_path)
        self._conn = None  # aiosqlite.Connection, set in initialize()

    async def initialize(self, channel_metadata: dict[str, Any]) -> bool:
        aiosqlite = _import_aiosqlite()
        # Ensure parent directory exists.
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.execute(_CREATE_INDEX)
        await self._conn.commit()
        logger.debug("SqliteDBClient initialised at %s", self._db_path)
        return True

    def _require_conn(self):
        if self._conn is None:
            raise RuntimeError(
                "SqliteDBClient.initialize() must be called before any DB operations."
            )

    async def save(self, message: ChannelMessage) -> bool:
        self._require_conn()
        try:
            await self._conn.execute(_INSERT, _msg_to_row(message))
            await self._conn.commit()
            return True
        except Exception as exc:
            logger.error("SqliteDBClient.save failed: %s", exc)
            return False

    async def save_batch(self, messages: list[ChannelMessage]) -> bool:
        self._require_conn()
        try:
            await self._conn.executemany(_INSERT, [_msg_to_row(m) for m in messages])
            await self._conn.commit()
            return True
        except Exception as exc:
            logger.error("SqliteDBClient.save_batch failed: %s", exc)
            return False

    async def get(self, message_id: str) -> ChannelMessage | None:
        self._require_conn()
        async with self._conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_msg(dict(row))

    async def get_range(self, start_time: float, end_time: float) -> list[ChannelMessage]:
        self._require_conn()
        async with self._conn.execute(
            "SELECT * FROM messages WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
            (start_time, end_time),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_msg(dict(r)) for r in rows]

    async def get_latest(self, limit: int) -> list[ChannelMessage]:
        self._require_conn()
        async with self._conn.execute(
            "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_msg(dict(r)) for r in rows]

    async def delete(self, message_ids: list[str]) -> bool:
        self._require_conn()
        if not message_ids:
            return True
        placeholders = ",".join("?" * len(message_ids))
        try:
            await self._conn.execute(
                f"DELETE FROM messages WHERE id IN ({placeholders})", message_ids
            )
            await self._conn.commit()
            return True
        except Exception as exc:
            logger.error("SqliteDBClient.delete failed: %s", exc)
            return False

    async def close(self) -> None:
        """Close the underlying connection. Call from on_stop() if desired."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# FileDBClient
# ---------------------------------------------------------------------------


class FileDBClient(ChannelDBClient):
    """
    File-system–backed channel persistence.

    Each message is stored as a JSON file named ``{message_id}.json`` in a
    channel-specific subdirectory.  get_latest() loads all files and sorts
    by timestamp — suitable for small channels and prototyping.
    """

    def __init__(self, base_dir: str | os.PathLike) -> None:
        self._base_dir = Path(base_dir)
        self._channel_dir: Path | None = None

    async def initialize(self, channel_metadata: dict[str, Any]) -> bool:
        channel_id: str = channel_metadata.get("id", "unknown")
        self._channel_dir = self._base_dir / channel_id
        self._channel_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("FileDBClient initialised at %s", self._channel_dir)
        return True

    def _require_dir(self) -> Path:
        if self._channel_dir is None:
            raise RuntimeError(
                "FileDBClient.initialize() must be called before any DB operations."
            )
        return self._channel_dir

    def _path_for(self, message_id: str) -> Path:
        # Sanitise: replace path separators to avoid directory traversal.
        safe_id = message_id.replace("/", "_").replace("\\", "_")
        return self._require_dir() / f"{safe_id}.json"

    def _serialise(self, message: ChannelMessage) -> dict[str, Any]:
        from sssn.core.channel import ChannelMessage  # noqa: PLC0415 (avoid circular at import)

        return {
            "id": message.id,
            "timestamp": message.timestamp,
            "sender_id": message.sender_id,
            "content_type": type(message.content).__name__,
            "content_data": json.loads(message.content.model_dump_json()),
            "metadata": message.metadata,
            "correlation_id": message.correlation_id,
            "reply_to": message.reply_to,
            "recipient_id": message.recipient_id,
        }

    def _deserialise(self, data: dict[str, Any]) -> ChannelMessage:
        from sssn.core.channel import GenericContent  # noqa: PLC0415

        content = GenericContent(data=data.get("content_data", {}))
        return _row_to_msg({
            "id": data["id"],
            "timestamp": data["timestamp"],
            "sender_id": data["sender_id"],
            "content_type": data.get("content_type", ""),
            "content_data": json.dumps(data.get("content_data", {})),
            "metadata": json.dumps(data.get("metadata", {})),
            "correlation_id": data.get("correlation_id"),
            "reply_to": data.get("reply_to"),
            "recipient_id": data.get("recipient_id"),
        })

    async def save(self, message: ChannelMessage) -> bool:
        path = self._path_for(message.id)
        try:
            path.write_text(json.dumps(self._serialise(message), indent=2), encoding="utf-8")
            return True
        except Exception as exc:
            logger.error("FileDBClient.save failed for %s: %s", message.id, exc)
            return False

    async def save_batch(self, messages: list[ChannelMessage]) -> bool:
        ok = True
        for m in messages:
            if not await self.save(m):
                ok = False
        return ok

    async def get(self, message_id: str) -> ChannelMessage | None:
        path = self._path_for(message_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._deserialise(data)
        except Exception as exc:
            logger.error("FileDBClient.get failed for %s: %s", message_id, exc)
            return None

    def _load_all(self) -> list[ChannelMessage]:
        dir_path = self._require_dir()
        messages: list[ChannelMessage] = []
        for p in dir_path.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                messages.append(self._deserialise(data))
            except Exception as exc:
                logger.warning("FileDBClient: failed to load %s: %s", p, exc)
        return messages

    async def get_range(self, start_time: float, end_time: float) -> list[ChannelMessage]:
        all_msgs = self._load_all()
        return sorted(
            [m for m in all_msgs if start_time <= m.timestamp <= end_time],
            key=lambda m: m.timestamp,
        )

    async def get_latest(self, limit: int) -> list[ChannelMessage]:
        all_msgs = self._load_all()
        all_msgs.sort(key=lambda m: m.timestamp, reverse=True)
        return all_msgs[:limit]

    async def delete(self, message_ids: list[str]) -> bool:
        ok = True
        for mid in message_ids:
            path = self._path_for(mid)
            try:
                if path.exists():
                    path.unlink()
            except Exception as exc:
                logger.error("FileDBClient.delete failed for %s: %s", mid, exc)
                ok = False
        return ok
