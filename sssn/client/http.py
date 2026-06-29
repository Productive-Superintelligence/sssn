"""HTTP clients for SSSN servers."""

from __future__ import annotations

import base64
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from ..core import Artifact, Channel, Event, InvalidPayloadError, Snapshot, Subscription


class SSSNClientError(RuntimeError):
    """Raised when an SSSN HTTP server returns an error."""

    def __init__(
        self,
        status_code: int,
        *,
        error_type: str | None = None,
        message: str | None = None,
        detail: Any = None,
    ) -> None:
        self.status_code = status_code
        self.error_type = _optional_token_value(error_type, "error_type")
        self.detail = detail
        self.message = _optional_text_value(message, "message") or _detail_message(detail)
        text = f"SSSN server returned HTTP {status_code}"
        if self.error_type:
            text += f" ({self.error_type})"
        if self.message:
            text += f": {self.message}"
        super().__init__(text)


class SSSNClient:
    """Synchronous HTTP client for the portable SSSN API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | None = 30.0,
        transport: Any = None,
    ) -> None:
        self.base_url = _base_url(base_url)
        self.timeout = timeout
        self.transport = transport

    def create_channel(self, channel: Channel | dict[str, Any]) -> Channel:
        data = _dump_channel(channel)
        _require_segment("channel.name", data.get("name"))
        return _model_response(
            self._request("POST", "/channels", json=data),
            Channel,
            "POST /channels",
        )

    def list_channels(self) -> tuple[Channel, ...]:
        return _model_tuple_response(
            self._request("GET", "/channels"),
            Channel,
            "GET /channels",
        )

    def get_channel(self, name: str) -> Channel:
        _require_segment("channel.name", name)
        return _model_response(
            self._request("GET", f"/channels/{name}"),
            Channel,
            "GET /channels/{name}",
        )

    def append_event(self, event: Event | dict[str, Any]) -> Event:
        data = _dump_event(event)
        _require_optional_segment("event.id", data.get("id"))
        _require_segment("event.channel", data.get("channel"))
        if "kind" in data:
            _require_token("event.kind", data["kind"])
        _require_segments("event.parent_ids", data.get("parent_ids", ()))
        return _model_response(
            self._request("POST", "/events", json=data),
            Event,
            "POST /events",
        )

    def query_events(
        self,
        channel: str,
        *,
        after_cursor: int = 0,
        limit: int = 100,
        kind: str | None = None,
    ) -> tuple[Event, ...]:
        _require_segment("channel.name", channel)
        params = {"channel": channel, "after_cursor": after_cursor, "limit": limit}
        if kind is not None:
            _require_token("event.kind", kind)
            params["kind"] = kind
        return _model_tuple_response(
            self._request("GET", "/events", params=params),
            Event,
            "GET /events",
        )

    def get_event(self, event_id: str) -> Event:
        _require_segment("event.id", event_id)
        return _model_response(
            self._request("GET", f"/events/{event_id}"),
            Event,
            "GET /events/{id}",
        )

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
        _require_segment("subscription.channel", channel)
        _require_optional_segment("subscription.id", subscription_id)
        return _model_response(
            self._request(
                "POST",
                "/subscriptions",
                json={
                    "id": subscription_id,
                    "channel": channel,
                    "consumer": consumer,
                    "batch_size": batch_size,
                    "filters": _copy_mapping(filters),
                    "metadata": _copy_mapping(metadata),
                },
            ),
            Subscription,
            "POST /subscriptions",
        )

    def pull_subscription(
        self,
        subscription_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        _require_segment("subscription.id", subscription_id)
        params = {"limit": limit} if limit is not None else None
        return _model_tuple_response(
            self._request(
                "POST",
                f"/subscriptions/{subscription_id}/pull",
                params=params,
            ),
            Event,
            "POST /subscriptions/{id}/pull",
        )

    def get_subscription(self, subscription_id: str) -> Subscription:
        _require_segment("subscription.id", subscription_id)
        return _model_response(
            self._request("GET", f"/subscriptions/{subscription_id}"),
            Subscription,
            "GET /subscriptions/{id}",
        )

    def write_artifact(
        self,
        data: bytes | str,
        *,
        channel: str | None = None,
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
        event_ids: tuple[str, ...] = (),
    ) -> Artifact:
        _require_optional_segment("artifact.channel", channel)
        _require_segments("artifact.event_ids", event_ids)
        payload = _artifact_payload(data)
        return _model_response(
            self._request(
                "POST",
                "/artifacts",
                json={
                    "data": payload["data"],
                    "encoding": payload["encoding"],
                    "channel": channel,
                    "media_type": media_type,
                    "metadata": _copy_mapping(metadata),
                    "event_ids": list(event_ids),
                },
            ),
            Artifact,
            "POST /artifacts",
        )

    def read_artifact(self, artifact_id: str) -> bytes:
        _require_segment("artifact.id", artifact_id)
        return self._request("GET", f"/artifacts/{artifact_id}").content

    def get_artifact(self, artifact_id: str) -> Artifact:
        _require_segment("artifact.id", artifact_id)
        return _model_response(
            self._request("GET", f"/artifacts/{artifact_id}/metadata"),
            Artifact,
            "GET /artifacts/{id}/metadata",
        )

    def put_snapshot(
        self,
        name: str,
        value: Any = None,
        *,
        channel: str | None = None,
        timestamp: float | None = None,
        schema: str | None = None,
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Snapshot:
        _require_segment("snapshot.name", name)
        payload = _snapshot_payload(
            value,
            channel=channel,
            timestamp=timestamp,
            schema=schema,
            source_event_id=source_event_id,
            metadata=metadata,
        )
        _require_optional_segment("snapshot.channel", payload.get("channel"))
        _require_optional_segment(
            "snapshot.source_event_id",
            payload.get("source_event_id"),
        )
        return _model_response(
            self._request(
                "PUT",
                f"/snapshots/{name}",
                json=payload,
            ),
            Snapshot,
            "PUT /snapshots/{name}",
        )

    def get_snapshot(self, name: str) -> Snapshot:
        _require_segment("snapshot.name", name)
        return _model_response(
            self._request("GET", f"/snapshots/{name}"),
            Snapshot,
            "GET /snapshots/{name}",
        )

    def _request(self, method: str, path: str, **kwargs: Any):
        import httpx

        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = client.request(method, path, **kwargs)
        _raise_for_error(response)
        return response


class AsyncSSSNClient:
    """Async HTTP client for the portable SSSN API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | None = 30.0,
        transport: Any = None,
    ) -> None:
        self.base_url = _base_url(base_url)
        self.timeout = timeout
        self.transport = transport

    async def create_channel(self, channel: Channel | dict[str, Any]) -> Channel:
        data = _dump_channel(channel)
        _require_segment("channel.name", data.get("name"))
        return _model_response(
            await self._request("POST", "/channels", json=data),
            Channel,
            "POST /channels",
        )

    async def list_channels(self) -> tuple[Channel, ...]:
        return _model_tuple_response(
            await self._request("GET", "/channels"),
            Channel,
            "GET /channels",
        )

    async def get_channel(self, name: str) -> Channel:
        _require_segment("channel.name", name)
        return _model_response(
            await self._request("GET", f"/channels/{name}"),
            Channel,
            "GET /channels/{name}",
        )

    async def append_event(self, event: Event | dict[str, Any]) -> Event:
        data = _dump_event(event)
        _require_optional_segment("event.id", data.get("id"))
        _require_segment("event.channel", data.get("channel"))
        if "kind" in data:
            _require_token("event.kind", data["kind"])
        _require_segments("event.parent_ids", data.get("parent_ids", ()))
        return _model_response(
            await self._request("POST", "/events", json=data),
            Event,
            "POST /events",
        )

    async def query_events(
        self,
        channel: str,
        *,
        after_cursor: int = 0,
        limit: int = 100,
        kind: str | None = None,
    ) -> tuple[Event, ...]:
        _require_segment("channel.name", channel)
        params = {"channel": channel, "after_cursor": after_cursor, "limit": limit}
        if kind is not None:
            _require_token("event.kind", kind)
            params["kind"] = kind
        return _model_tuple_response(
            await self._request("GET", "/events", params=params),
            Event,
            "GET /events",
        )

    async def get_event(self, event_id: str) -> Event:
        _require_segment("event.id", event_id)
        return _model_response(
            await self._request("GET", f"/events/{event_id}"),
            Event,
            "GET /events/{id}",
        )

    async def create_subscription(
        self,
        channel: str,
        *,
        subscription_id: str | None = None,
        consumer: str | None = None,
        batch_size: int = 100,
        filters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Subscription:
        _require_segment("subscription.channel", channel)
        _require_optional_segment("subscription.id", subscription_id)
        return _model_response(
            (
                await self._request(
                    "POST",
                    "/subscriptions",
                    json={
                        "id": subscription_id,
                        "channel": channel,
                        "consumer": consumer,
                        "batch_size": batch_size,
                        "filters": _copy_mapping(filters),
                        "metadata": _copy_mapping(metadata),
                    },
                )
            ),
            Subscription,
            "POST /subscriptions",
        )

    async def pull_subscription(
        self,
        subscription_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        _require_segment("subscription.id", subscription_id)
        params = {"limit": limit} if limit is not None else None
        return _model_tuple_response(
            await self._request(
                "POST",
                f"/subscriptions/{subscription_id}/pull",
                params=params,
            ),
            Event,
            "POST /subscriptions/{id}/pull",
        )

    async def get_subscription(self, subscription_id: str) -> Subscription:
        _require_segment("subscription.id", subscription_id)
        return _model_response(
            await self._request("GET", f"/subscriptions/{subscription_id}"),
            Subscription,
            "GET /subscriptions/{id}",
        )

    async def write_artifact(
        self,
        data: bytes | str,
        *,
        channel: str | None = None,
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
        event_ids: tuple[str, ...] = (),
    ) -> Artifact:
        _require_optional_segment("artifact.channel", channel)
        _require_segments("artifact.event_ids", event_ids)
        payload = _artifact_payload(data)
        return _model_response(
            (
                await self._request(
                    "POST",
                    "/artifacts",
                    json={
                        "data": payload["data"],
                        "encoding": payload["encoding"],
                        "channel": channel,
                        "media_type": media_type,
                        "metadata": _copy_mapping(metadata),
                        "event_ids": list(event_ids),
                    },
                )
            ),
            Artifact,
            "POST /artifacts",
        )

    async def read_artifact(self, artifact_id: str) -> bytes:
        _require_segment("artifact.id", artifact_id)
        return (await self._request("GET", f"/artifacts/{artifact_id}")).content

    async def get_artifact(self, artifact_id: str) -> Artifact:
        _require_segment("artifact.id", artifact_id)
        return _model_response(
            await self._request("GET", f"/artifacts/{artifact_id}/metadata"),
            Artifact,
            "GET /artifacts/{id}/metadata",
        )

    async def put_snapshot(
        self,
        name: str,
        value: Any = None,
        *,
        channel: str | None = None,
        timestamp: float | None = None,
        schema: str | None = None,
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Snapshot:
        _require_segment("snapshot.name", name)
        payload = _snapshot_payload(
            value,
            channel=channel,
            timestamp=timestamp,
            schema=schema,
            source_event_id=source_event_id,
            metadata=metadata,
        )
        _require_optional_segment("snapshot.channel", payload.get("channel"))
        _require_optional_segment(
            "snapshot.source_event_id",
            payload.get("source_event_id"),
        )
        return _model_response(
            (
                await self._request(
                    "PUT",
                    f"/snapshots/{name}",
                    json=payload,
                )
            ),
            Snapshot,
            "PUT /snapshots/{name}",
        )

    async def get_snapshot(self, name: str) -> Snapshot:
        _require_segment("snapshot.name", name)
        return _model_response(
            await self._request("GET", f"/snapshots/{name}"),
            Snapshot,
            "GET /snapshots/{name}",
        )

    async def _request(self, method: str, path: str, **kwargs: Any):
        import httpx

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
        _raise_for_error(response)
        return response


def _dump_channel(channel: Channel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(channel, Channel):
        return deepcopy(channel.model_dump(mode="json", by_alias=True))
    return deepcopy(channel)


def _dump_event(event: Event | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, Event):
        return deepcopy(event.model_dump(mode="json", by_alias=True))
    return deepcopy(event)


def _artifact_payload(data: bytes | str) -> dict[str, str]:
    if isinstance(data, bytes):
        return {
            "data": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
        }
    return {"data": data, "encoding": "text"}


def _base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be a non-empty absolute http(s) URL")
    value = base_url.strip()
    if any(ch.isspace() for ch in value):
        raise ValueError("base_url must not contain whitespace")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL")
    return value.rstrip("/")


def _require_segment(field_name: str, value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise InvalidPayloadError(f"{field_name} must be a non-empty path segment.")


def _require_token(field_name: str, value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise InvalidPayloadError(f"{field_name} must be a non-empty token.")


def _require_optional_segment(field_name: str, value: Any) -> None:
    if value is not None:
        _require_segment(field_name, value)


def _require_segments(field_name: str, values: Any) -> None:
    for value in values or ():
        _require_segment(field_name, value)


def _snapshot_payload(
    value: Any,
    *,
    channel: str | None,
    timestamp: float | None,
    schema: str | None,
    source_event_id: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(value, Snapshot):
        payload = deepcopy(
            value.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        payload.pop("name", None)
        if channel is not None:
            payload["channel"] = channel
        if timestamp is not None:
            payload["timestamp"] = timestamp
        if schema is not None:
            payload["schema"] = schema
        if source_event_id is not None:
            payload["source_event_id"] = source_event_id
        if metadata is not None:
            payload["metadata"] = deepcopy(metadata)
        return payload
    raw_keys = {"channel", "timestamp", "value", "schema", "source_event_id", "metadata"}
    if (
        isinstance(value, dict)
        and raw_keys.intersection(value)
        and channel is None
        and timestamp is None
        and schema is None
        and source_event_id is None
        and metadata is None
    ):
        return deepcopy(value)
    payload: dict[str, Any] = {"value": deepcopy(value)}
    if channel is not None:
        payload["channel"] = channel
    if timestamp is not None:
        payload["timestamp"] = timestamp
    if schema is not None:
        payload["schema"] = schema
    if source_event_id is not None:
        payload["source_event_id"] = source_event_id
    if metadata is not None:
        payload["metadata"] = deepcopy(metadata)
    return payload


def _copy_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    return deepcopy(value) if value is not None else {}


def _model_response(response: Any, model_type: Any, endpoint: str) -> Any:
    data = _response_json(response, endpoint)
    try:
        return model_type.model_validate(data)
    except Exception as exc:
        raise SSSNClientError(
            response.status_code,
            error_type="InvalidResponse",
            message=f"SSSN {endpoint} response did not match the expected schema.",
            detail=data,
        ) from exc


def _model_tuple_response(response: Any, model_type: Any, endpoint: str) -> tuple[Any, ...]:
    data = _response_json(response, endpoint)
    if not isinstance(data, list):
        raise SSSNClientError(
            response.status_code,
            error_type="InvalidResponse",
            message=f"SSSN {endpoint} response did not match the expected schema.",
            detail=data,
        )
    try:
        return tuple(model_type.model_validate(item) for item in data)
    except Exception as exc:
        raise SSSNClientError(
            response.status_code,
            error_type="InvalidResponse",
            message=f"SSSN {endpoint} response did not match the expected schema.",
            detail=data,
        ) from exc


def _response_json(response: Any, endpoint: str) -> Any:
    try:
        return response.json()
    except Exception as exc:
        raise SSSNClientError(
            response.status_code,
            error_type="InvalidResponse",
            message=f"SSSN {endpoint} response was not valid JSON.",
            detail=response.text,
        ) from exc


def _raise_for_error(response: Any) -> None:
    if response.status_code < 400:
        return
    try:
        data = response.json()
    except Exception:
        data = response.text
    error = _error_detail(data)
    raise SSSNClientError(
        response.status_code,
        error_type=_error_token_field(error, "type"),
        message=_error_text_field(error, "message"),
        detail=data,
    )


def _error_detail(data: Any) -> Any:
    if isinstance(data, dict):
        detail = data.get("detail", data)
        if isinstance(detail, dict) and "error" in detail:
            return detail["error"]
        if "error" in data:
            return data["error"]
    return data


def _detail_message(detail: Any) -> str | None:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        error = _error_detail(detail)
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return None


def _error_text_field(error: Any, field_name: str) -> str | None:
    if not isinstance(error, dict):
        return None
    value = error.get(field_name)
    return value if isinstance(value, str) else None


def _error_token_field(error: Any, field_name: str) -> str | None:
    value = _error_text_field(error, field_name)
    if value is None:
        return None
    try:
        return _token_value(value, f"error.{field_name}")
    except ValueError:
        return None


def _optional_text_value(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string.")
    return value


def _optional_token_value(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _token_value(value, label)


def _token_value(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string.")
    if (
        not value.strip()
        or value in {".", ".."}
        or any(ch.isspace() for ch in value)
        or any(ch in value for ch in "/:\\")
    ):
        raise ValueError(f"{label} must be a non-empty token.")
    return value
