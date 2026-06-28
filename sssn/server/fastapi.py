"""FastAPI server for SSSN stores."""

from __future__ import annotations

import base64
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core import (
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    Event,
    SSSNError,
    Snapshot,
    SnapshotNotFoundError,
    SubscriptionNotFoundError,
)
from ..stores import LocalStore


class ErrorDetail(BaseModel):
    type: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class SubscriptionRequest(BaseModel):
    channel: str
    consumer: str | None = None
    batch_size: int = 100
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactWriteRequest(BaseModel):
    data: str
    encoding: Literal["text", "base64"] = "text"
    channel: str | None = None
    media_type: str = "application/octet-stream"
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_ids: tuple[str, ...] = Field(default_factory=tuple)

    def bytes(self) -> bytes:
        if self.encoding == "base64":
            return base64.b64decode(self.data.encode("ascii"))
        return self.data.encode("utf-8")


class SnapshotWriteRequest(BaseModel):
    channel: str | None = None
    timestamp: float | None = None
    value: Any = None
    schema_ref: str | None = Field(default=None, alias="schema")
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(store: LocalStore | None = None):
    """Create a FastAPI app exposing a store's portable API."""

    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.encoders import jsonable_encoder
        from fastapi.responses import Response
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install sssn[server] to use the FastAPI server.") from exc

    local_store = store or LocalStore()
    app = FastAPI(title="SSSN Store", version="0.1.0")
    app.state.sssn_store = local_store

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/channels")
    async def create_channel(channel: Channel) -> dict[str, Any]:
        try:
            return jsonable_encoder(local_store.create_channel(channel))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/channels")
    async def list_channels() -> list[dict[str, Any]]:
        return [jsonable_encoder(channel) for channel in local_store.list_channels()]

    @app.get("/channels/{name}")
    async def get_channel(name: str) -> dict[str, Any]:
        try:
            return jsonable_encoder(local_store.get_channel(name))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/events")
    async def append_event(event: Event) -> dict[str, Any]:
        try:
            return jsonable_encoder(local_store.append_event(event))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/events")
    async def query_events(
        channel: str,
        after_cursor: int = 0,
        limit: int = Query(default=100, ge=1),
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            events = local_store.query_events(
                channel,
                after_cursor=after_cursor,
                limit=limit,
                kind=kind,
            )
            return [jsonable_encoder(event) for event in events]
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/subscriptions")
    async def create_subscription(request: SubscriptionRequest) -> dict[str, Any]:
        try:
            return jsonable_encoder(
                local_store.create_subscription(
                    request.channel,
                    consumer=request.consumer,
                    batch_size=request.batch_size,
                    filters=request.filters,
                    metadata=request.metadata,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/subscriptions/{subscription_id}/pull")
    async def pull_subscription(
        subscription_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return [
                jsonable_encoder(event)
                for event in local_store.pull_subscription(subscription_id, limit=limit)
            ]
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/artifacts")
    async def write_artifact(request: ArtifactWriteRequest) -> dict[str, Any]:
        try:
            return jsonable_encoder(
                local_store.write_artifact(
                    request.bytes(),
                    channel=request.channel,
                    media_type=request.media_type,
                    metadata=request.metadata,
                    event_ids=request.event_ids,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/artifacts/{artifact_id}")
    async def read_artifact(artifact_id: str):
        try:
            data = local_store.read_artifact(artifact_id)
            return Response(content=data, media_type="application/octet-stream")
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.put("/snapshots/{name}")
    async def put_snapshot(name: str, snapshot: SnapshotWriteRequest) -> dict[str, Any]:
        try:
            data = snapshot.model_dump(by_alias=True, exclude_none=True)
            value = Snapshot(name=name, **data)
            return jsonable_encoder(local_store.put_snapshot(value))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/snapshots/{name}")
    async def get_snapshot(name: str) -> dict[str, Any]:
        try:
            return jsonable_encoder(local_store.get_snapshot(name))
        except Exception as exc:
            raise _http_error(exc) from exc

    return app


def _http_error(exc: Exception):
    try:
        from fastapi import HTTPException
    except ImportError as import_exc:  # pragma: no cover
        raise RuntimeError("Install sssn[server] to use the FastAPI server.") from import_exc

    status_code = 500
    if isinstance(
        exc,
        (
            ChannelNotFoundError,
            ArtifactNotFoundError,
            SnapshotNotFoundError,
            SubscriptionNotFoundError,
        ),
    ):
        status_code = 404
    elif isinstance(exc, ChannelExistsError):
        status_code = 409
    elif isinstance(exc, SSSNError):
        status_code = 400
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error=ErrorDetail(type=type(exc).__name__, message=str(exc))
        ).model_dump(mode="json"),
    )
