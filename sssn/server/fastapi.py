"""FastAPI server for SSSN stores."""

from __future__ import annotations

import base64
import binascii
import inspect
import math
import re
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictStr, model_validator

from lllm.protocol.validation import copy_boundary_value

from ..core import (
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    Event,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    NetworkError,
    SnapshotNotFoundError,
    StoreBusyError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)
from ..client.http import RemoteStoreError
from ..core.models import RECORD_CLASSES, record_data, record_json
from ..stores import LocalStore
from .endpoints import (
    StoreEndpointSpec,
    endpoint_path_key,
    endpoint_route_key,
    endpoint_spec,
    endpoint_specs,
)


_CUSTOM_ROUTE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
# The most events one request returns: a larger limit is refused, and a
# larger batch_size is capped.
_MAX_LIMIT = 10_000
# The name in a route parameter, as in {name} or {name:int}.
_PATH_PARAMETER_RE = re.compile(r"\{([^{}:]+)")
_NOT_FOUND_ERRORS = (
    ChannelNotFoundError,
    EventNotFoundError,
    ArtifactNotFoundError,
    SnapshotNotFoundError,
    SubscriptionNotFoundError,
)
_CONFLICT_ERRORS = (ChannelExistsError, EventExistsError, SubscriptionExistsError)
_STORE_ERRORS = (
    *_NOT_FOUND_ERRORS,
    *_CONFLICT_ERRORS,
    InvalidPayloadError,
    StoreBusyError,
)


class ErrorDetail(BaseModel):
    type: StrictStr
    message: StrictStr

    @model_validator(mode="after")
    def _validate_type(self) -> "ErrorDetail":
        _validate_token(self.type, "error.type")
        return self


class ErrorResponse(BaseModel):
    error: ErrorDetail


class SubscriptionRequest(BaseModel):
    id: StrictStr | None = None
    channel: StrictStr
    consumer: StrictStr | None = None
    batch_size: int = 100
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.filters = copy_boundary_value(self.filters)
        self.metadata = copy_boundary_value(self.metadata)


class ArtifactWriteRequest(BaseModel):
    data: StrictStr
    encoding: Literal["text", "base64"] = "text"
    channel: StrictStr | None = None
    media_type: StrictStr = "application/octet-stream"
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_ids: tuple[StrictStr, ...] = Field(default_factory=tuple)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = copy_boundary_value(self.metadata)

    def bytes(self) -> bytes:
        if self.encoding == "base64":
            try:
                return base64.b64decode(self.data.encode("ascii"), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise InvalidPayloadError("Invalid base64 artifact data.") from exc
        return self.data.encode("utf-8")


class SnapshotWriteRequest(BaseModel):
    channel: StrictStr | None = None
    timestamp: float | None = Field(default=None, allow_inf_nan=False)
    value: Any = None
    schema_ref: StrictStr | None = Field(default=None, alias="schema")
    source_event_id: StrictStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.value = copy_boundary_value(self.value)
        self.metadata = copy_boundary_value(self.metadata)


def create_app(
    store: Any = None,
    *,
    custom_endpoints: Sequence[Callable[..., Any]] = (),
):
    """Create a FastAPI app exposing a store's portable API.

    ``store`` is any store, synchronous or async: a ``LocalStore`` (without
    one, the app opens ``LocalStore()``), an ``AsyncRemoteStore`` in front of
    another server, or another object with the store methods. Synchronous
    store methods and custom endpoint handlers run in a thread pool,
    possibly at the same time, so they must be thread-safe; async ones are
    awaited on the event loop.
    """

    try:
        from fastapi import FastAPI, Query
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install sssn[server] to use the FastAPI server.") from exc

    from .. import __version__

    # Read once: a generator would be used up by the first pass.
    custom_endpoints = tuple(custom_endpoints)
    local_store = LocalStore() if store is None else store
    app = FastAPI(title="SSSN Store", version=__version__)
    app.state.sssn_store = local_store
    # LLLM 0.3's lllm.network kept the store here; code written against it
    # still finds it.
    app.state.network_store = local_store

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Any, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={
                "detail": _error_payload(
                    "InvalidPayloadError",
                    _validation_error_message(exc),
                )
            },
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/channels")
    async def create_channel(channel: Channel) -> dict[str, Any]:
        try:
            return _records_response(await _call(local_store.create_channel, channel))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/channels")
    async def list_channels() -> list[dict[str, Any]]:
        try:
            return _records_response(await _call(local_store.list_channels))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/channels/{name}")
    async def get_channel(name: str) -> dict[str, Any]:
        try:
            return _records_response(await _call(local_store.get_channel, name))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/events")
    async def append_event(event: Event) -> dict[str, Any]:
        try:
            # Event is also the model of stored events, which may hold an
            # infinite timestamp from sssn 0.2.0, so the check is here.
            if not math.isfinite(event.timestamp):
                raise InvalidPayloadError("event.timestamp must be a finite number.")
            return _records_response(await _call(local_store.append_event, event))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/events")
    async def query_events(
        channel: str,
        after_cursor: int = 0,
        limit: int = Query(100, le=_MAX_LIMIT),
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            events = await _call(
                local_store.query_events,
                channel,
                after_cursor=after_cursor,
                limit=limit,
                kind=kind,
            )
            return _records_response(events)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/events/{event_id}")
    async def get_event(event_id: str) -> dict[str, Any]:
        try:
            return _records_response(await _call(local_store.get_event, event_id))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/subscriptions")
    async def create_subscription(request: SubscriptionRequest) -> dict[str, Any]:
        try:
            return _records_response(
                await _call(
                    local_store.create_subscription,
                    request.channel,
                    subscription_id=request.id,
                    consumer=request.consumer,
                    # Capped, not refused: an existing subscription comes
                    # back unchanged, since batch_size is not compared.
                    batch_size=min(request.batch_size, _MAX_LIMIT),
                    filters=request.filters,
                    metadata=request.metadata,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/subscriptions/{subscription_id}")
    async def get_subscription(subscription_id: str) -> dict[str, Any]:
        try:
            return _records_response(
                await _call(local_store.get_subscription, subscription_id)
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/subscriptions/{subscription_id}/pull")
    async def pull_subscription(
        subscription_id: str,
        limit: int | None = Query(None, le=_MAX_LIMIT),
    ) -> list[dict[str, Any]]:
        try:
            if limit is None:
                # The subscription's batch_size, which a LocalStore, the CLI,
                # or an older server may have set above the cap.
                subscription = await _call(local_store.get_subscription, subscription_id)
                limit = min(subscription.batch_size, _MAX_LIMIT)
            events = await _call(
                local_store.pull_subscription, subscription_id, limit=limit
            )
            return _records_response(events)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.post("/artifacts")
    async def write_artifact(request: ArtifactWriteRequest) -> dict[str, Any]:
        try:
            return _records_response(
                await _call(
                    local_store.write_artifact,
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
            artifact = await _call(local_store.get_artifact, artifact_id)
            data = await _call(local_store.read_artifact, artifact_id)
            return Response(content=data, media_type=artifact.media_type)
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/artifacts/{artifact_id}/metadata")
    async def get_artifact(artifact_id: str) -> dict[str, Any]:
        try:
            return _records_response(await _call(local_store.get_artifact, artifact_id))
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.put("/snapshots/{name}")
    async def put_snapshot(name: str, snapshot: SnapshotWriteRequest) -> dict[str, Any]:
        try:
            # A dict, so the store reports invalid fields, such as a NaN
            # timestamp, as InvalidPayloadError.
            data = snapshot.model_dump(by_alias=True, exclude_none=True)
            snapshot_fields = {**data, "name": name}
            return _records_response(
                await _call(local_store.put_snapshot, snapshot_fields)
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @app.get("/snapshots/{name}")
    async def get_snapshot(name: str) -> dict[str, Any]:
        try:
            return _records_response(await _call(local_store.get_snapshot, name))
        except Exception as exc:
            raise _http_error(exc) from exc

    for fn in custom_endpoints:
        # Manifest metadata skips an undecorated function; serving cannot.
        if endpoint_spec(fn) is None:
            name = getattr(fn, "__qualname__", None) or repr(fn)
            raise ValueError(
                f"custom endpoint {name} has no route: decorate it with "
                "@endpoint.get(path), or post, put, patch, or delete"
            )
    reserved_routes = _reserved_routes(app)
    seen_custom_routes: dict[tuple[str, str], StoreEndpointSpec] = {}
    for fn, spec in endpoint_specs(custom_endpoints):
        _validate_custom_route(
            spec,
            reserved_routes=reserved_routes,
            seen_custom_routes=seen_custom_routes,
        )
        _mount_custom_endpoint(app, local_store, spec, fn)

    return app


def _records_response(records: Any) -> Any:
    """Answer with records a store returned, as strict JSON that cannot fail
    on what the store holds (see ``record_json``)."""

    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import Response

    # jsonable_encoder writes anything else, such as a custom store's dates.
    text = record_json(records, default=jsonable_encoder)
    return Response(content=text, media_type="application/json")


async def _call(function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Call a store method or an endpoint handler without blocking the loop.

    A coroutine function is awaited. Anything else, such as a ``LocalStore``
    method that waits on SQLite, runs in a worker thread, so the server
    keeps answering other requests meanwhile; an awaitable it returns is
    awaited too.
    """

    if inspect.iscoroutinefunction(function):
        return await function(*args, **kwargs)
    from starlette.concurrency import run_in_threadpool

    result = await run_in_threadpool(function, *args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def _mount_custom_endpoint(
    app: Any,
    store: Any,
    spec: StoreEndpointSpec,
    fn: Callable[..., Any],
) -> None:
    from fastapi import Request
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import Response

    parameters = _custom_parameters(fn, spec)
    records = {record_class: record_data for record_class in RECORD_CLASSES}

    async def route(request: Request):
        try:
            body = None
            if request.method not in {"GET", "DELETE"}:
                try:
                    body = await request.json()
                except Exception:
                    body = None
            kwargs: dict[str, Any] = {}
            for name in parameters:
                if name == "store":
                    kwargs[name] = store
                elif name == "body":
                    kwargs[name] = body
                elif name in request.path_params:
                    # This route's path parameters, and an enclosing mount's.
                    kwargs[name] = request.path_params[name]
                elif name == "params":
                    kwargs[name] = dict(request.query_params)
            result = await _call(fn, **kwargs)
            # Encoded as 0.2.0 encoded a result, except SSSN's records, which
            # follow the record rules, and then written by the same strict
            # writer as the records: a NaN left is null. jsonable_encoder
            # leaves text alone, so the writer still escapes a lone surrogate.
            data = jsonable_encoder(result, custom_encoder=records)
            text = record_json(data, default=jsonable_encoder)
            return Response(content=text, media_type="application/json")
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


def _custom_parameters(
    fn: Callable[..., Any],
    spec: StoreEndpointSpec,
) -> tuple[str, ...]:
    """Name the handler parameters to pass, checked when the app is built.

    At each request ``store`` gets the store, ``body`` the JSON body, a
    parameter named like a path parameter gets it (also one from the path of
    an enclosing mount), and ``params`` the query parameters; any other keeps
    its default. A parameter without a default that nothing here can fill
    raises ``ValueError`` rather than failing every request; one that only a
    mount's path fills needs a default, since the mount is not known yet.
    """

    path_names = set(_PATH_PARAMETER_RE.findall(spec.path))
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"custom endpoint {spec.name!r} has a handler without a signature"
        ) from exc
    names: list[str] = []
    for parameter in parameters:
        name, has_default = parameter.name, parameter.default is not parameter.empty
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        if parameter.kind is parameter.POSITIONAL_ONLY:
            if has_default:
                continue
            raise ValueError(
                f"custom endpoint {spec.name!r} cannot bind parameter {name!r}: "
                "handler parameters are passed by name, so they cannot be "
                "positional-only"
            )
        if not has_default and name not in {"store", "body", "params", *path_names}:
            raise ValueError(
                f"custom endpoint {spec.name!r} cannot bind parameter {name!r}: "
                "a handler receives store, body, params, and the path parameters "
                f"of {spec.path!r} by name; give {name!r} a default (one filled "
                "from the path of an enclosing mount needs a default too)"
            )
        names.append(name)
    return tuple(names)


def _route_name(name: str) -> str:
    value = re.sub(r"\W+", "_", name).strip("_")
    if not value:
        return "sssn_endpoint"
    if value[0].isdigit():
        return f"endpoint_{value}"
    return value


def _reserved_routes(app: Any) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path_format", None) or getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not isinstance(path, str) or not methods:
            continue
        for method in methods:
            method_name = str(method).upper()
            if method_name in _CUSTOM_ROUTE_METHODS:
                routes.add((method_name, endpoint_path_key(path)))
    return routes


def _validate_custom_route(
    spec: StoreEndpointSpec,
    *,
    reserved_routes: set[tuple[str, str]],
    seen_custom_routes: dict[tuple[str, str], StoreEndpointSpec],
) -> None:
    key = endpoint_route_key(spec)
    if key in reserved_routes:
        raise ValueError(
            "custom endpoint route conflicts with reserved SSSN service route: "
            f"{spec.method} {spec.path}"
        )
    if key in seen_custom_routes:
        raise ValueError(
            "duplicate custom endpoint route: "
            f"{spec.method} {spec.path!r}"
        )
    seen_custom_routes[key] = spec


def _http_error(exc: Exception):
    try:
        from fastapi import HTTPException
    except ImportError as import_exc:  # pragma: no cover
        raise RuntimeError("Install sssn[server] to use the FastAPI server.") from import_exc

    error_type, message = type(exc).__name__, str(exc)
    status_code = 500
    if isinstance(exc, _NOT_FOUND_ERRORS):
        status_code = 404
    elif isinstance(exc, _CONFLICT_ERRORS):
        status_code = 409
    elif isinstance(exc, StoreBusyError):
        status_code = 503
    elif isinstance(exc, RemoteStoreError):
        # The server behind a RemoteStore chose the status: pass on a client
        # error as it is; anything else is this server's failure.
        status_code = exc.status_code if 400 <= exc.status_code < 500 else 500
    elif isinstance(exc, NetworkError):
        status_code = 400
    if isinstance(exc, RemoteStoreError) and isinstance(exc, _STORE_ERRORS):
        # A store error from the server behind a RemoteStore: report it the
        # way that server did, so clients of this one see the same error.
        error_type = exc.error_type or error_type
        message = exc.message or message
    return HTTPException(
        status_code=status_code,
        detail=_error_payload(error_type, message),
    )


def _error_payload(error_type: str, message: str) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorDetail(type=error_type, message=message)
    ).model_dump(mode="json")


def _validation_error_message(exc: Exception) -> str:
    errors = exc.errors() if hasattr(exc, "errors") else []
    messages: list[str] = []
    for error in errors:
        location = ".".join(
            str(part) for part in error.get("loc", ()) if part != "body"
        )
        message = str(error.get("msg") or "Invalid request payload.")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages) if messages else "Invalid request payload."


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
