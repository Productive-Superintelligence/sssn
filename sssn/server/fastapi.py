"""FastAPI server for SSSN stores."""

from __future__ import annotations

import base64
import binascii
import inspect
import re
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core import (
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    Event,
    InvalidPayloadError,
    SSSNError,
    Snapshot,
    SnapshotNotFoundError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from ..stores import LocalStore
from .endpoints import StoreEndpointSpec, endpoint_spec


class ErrorDetail(BaseModel):
    type: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class SubscriptionRequest(BaseModel):
    id: str | None = None
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
            try:
                return base64.b64decode(self.data.encode("ascii"), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise InvalidPayloadError("Invalid base64 artifact data.") from exc
        return self.data.encode("utf-8")


class SnapshotWriteRequest(BaseModel):
    channel: str | None = None
    timestamp: float | None = None
    value: Any = None
    schema_ref: str | None = Field(default=None, alias="schema")
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(
    store: LocalStore | None = None,
    *,
    custom_endpoints: Sequence[Callable[..., Any]] = (),
):
    """Create a FastAPI app exposing a store's portable API."""

    try:
        from fastapi import FastAPI, HTTPException
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
        limit: int = 100,
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
                    subscription_id=request.id,
                    consumer=request.consumer,
                    batch_size=request.batch_size,
                    filters=request.filters,
                    metadata=request.metadata,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/subscriptions/{subscription_id}")
    async def get_subscription(subscription_id: str) -> dict[str, Any]:
        try:
            return jsonable_encoder(local_store.get_subscription(subscription_id))
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
            artifact = local_store.get_artifact(artifact_id)
            data = local_store.read_artifact(artifact_id)
            return Response(content=data, media_type=artifact.media_type)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/artifacts/{artifact_id}/metadata")
    async def get_artifact(artifact_id: str) -> dict[str, Any]:
        try:
            return jsonable_encoder(local_store.get_artifact(artifact_id))
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

    for fn in custom_endpoints:
        spec = endpoint_spec(fn)
        if spec is not None:
            _mount_custom_endpoint(app, local_store, spec, fn)

    return app


def _mount_custom_endpoint(
    app: Any,
    store: LocalStore,
    spec: StoreEndpointSpec,
    fn: Callable[..., Any],
) -> None:
    from fastapi import Request
    from fastapi.encoders import jsonable_encoder

    async def route(request: Request):
        try:
            body = None
            if request.method not in {"GET", "DELETE"}:
                try:
                    body = await request.json()
                except Exception:
                    body = None
            result = fn(**_custom_kwargs(fn, store=store, body=body, path=request.path_params))
            if inspect.isawaitable(result):
                result = await result
            return jsonable_encoder(result)
        except Exception as exc:
            raise _http_error(exc) from exc

    route.__name__ = _route_name(spec.name)
    route.__doc__ = spec.description
    route.__annotations__ = {"request": Request}
    app.add_api_route(
        spec.path,
        route,
        methods=[spec.method],
        summary=spec.name.replace("_", " ").title(),
        description=spec.description,
        tags=list(spec.tags),
    )


def _custom_kwargs(
    fn: Callable[..., Any],
    *,
    store: LocalStore,
    body: Any,
    path: dict[str, Any],
) -> dict[str, Any]:
    signature = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "store":
            kwargs[name] = store
        elif name == "body":
            kwargs[name] = body
        elif name in path:
            kwargs[name] = path[name]
        elif parameter.default is inspect.Parameter.empty:
            raise TypeError(f"Cannot bind custom endpoint parameter: {name}")
    return kwargs


def _route_name(name: str) -> str:
    value = re.sub(r"\W+", "_", name).strip("_")
    if not value:
        return "sssn_endpoint"
    if value[0].isdigit():
        return f"endpoint_{value}"
    return value


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
    elif isinstance(exc, (ChannelExistsError, SubscriptionExistsError)):
        status_code = 409
    elif isinstance(exc, SSSNError):
        status_code = 400
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error=ErrorDetail(type=type(exc).__name__, message=str(exc))
        ).model_dump(mode="json"),
    )
