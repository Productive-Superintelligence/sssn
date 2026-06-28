"""HTTP clients for SSSN servers."""

from __future__ import annotations

import base64
from typing import Any

from ..core import Artifact, Channel, Event, Snapshot, Subscription


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
        self.error_type = error_type
        self.detail = detail
        self.message = message or _detail_message(detail)
        text = f"SSSN server returned HTTP {status_code}"
        if error_type:
            text += f" ({error_type})"
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
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def create_channel(self, channel: Channel | dict[str, Any]) -> Channel:
        data = _dump_channel(channel)
        return Channel.model_validate(
            self._request("POST", "/channels", json=data).json()
        )

    def list_channels(self) -> tuple[Channel, ...]:
        data = self._request("GET", "/channels").json()
        return tuple(Channel.model_validate(item) for item in data)

    def get_channel(self, name: str) -> Channel:
        return Channel.model_validate(self._request("GET", f"/channels/{name}").json())

    def append_event(self, event: Event | dict[str, Any]) -> Event:
        data = _dump_event(event)
        return Event.model_validate(self._request("POST", "/events", json=data).json())

    def query_events(
        self,
        channel: str,
        *,
        after_cursor: int = 0,
        limit: int = 100,
        kind: str | None = None,
    ) -> tuple[Event, ...]:
        params = {"channel": channel, "after_cursor": after_cursor, "limit": limit}
        if kind is not None:
            params["kind"] = kind
        data = self._request("GET", "/events", params=params).json()
        return tuple(Event.model_validate(item) for item in data)

    def create_subscription(
        self,
        channel: str,
        *,
        consumer: str | None = None,
        batch_size: int = 100,
        filters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Subscription:
        return Subscription.model_validate(
            self._request(
                "POST",
                "/subscriptions",
                json={
                    "channel": channel,
                    "consumer": consumer,
                    "batch_size": batch_size,
                    "filters": filters or {},
                    "metadata": metadata or {},
                },
            ).json()
        )

    def pull_subscription(
        self,
        subscription_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        params = {"limit": limit} if limit is not None else None
        data = self._request(
            "POST",
            f"/subscriptions/{subscription_id}/pull",
            params=params,
        ).json()
        return tuple(Event.model_validate(item) for item in data)

    def get_subscription(self, subscription_id: str) -> Subscription:
        return Subscription.model_validate(
            self._request("GET", f"/subscriptions/{subscription_id}").json()
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
        payload = _artifact_payload(data)
        return Artifact.model_validate(
            self._request(
                "POST",
                "/artifacts",
                json={
                    "data": payload["data"],
                    "encoding": payload["encoding"],
                    "channel": channel,
                    "media_type": media_type,
                    "metadata": metadata or {},
                    "event_ids": list(event_ids),
                },
            ).json()
        )

    def read_artifact(self, artifact_id: str) -> bytes:
        return self._request("GET", f"/artifacts/{artifact_id}").content

    def put_snapshot(self, name: str, value: dict[str, Any]) -> Snapshot:
        return Snapshot.model_validate(
            self._request("PUT", f"/snapshots/{name}", json=value).json()
        )

    def get_snapshot(self, name: str) -> Snapshot:
        return Snapshot.model_validate(self._request("GET", f"/snapshots/{name}").json())

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
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def create_channel(self, channel: Channel | dict[str, Any]) -> Channel:
        data = _dump_channel(channel)
        return Channel.model_validate(
            (await self._request("POST", "/channels", json=data)).json()
        )

    async def list_channels(self) -> tuple[Channel, ...]:
        data = (await self._request("GET", "/channels")).json()
        return tuple(Channel.model_validate(item) for item in data)

    async def get_channel(self, name: str) -> Channel:
        return Channel.model_validate((await self._request("GET", f"/channels/{name}")).json())

    async def append_event(self, event: Event | dict[str, Any]) -> Event:
        data = _dump_event(event)
        return Event.model_validate((await self._request("POST", "/events", json=data)).json())

    async def query_events(
        self,
        channel: str,
        *,
        after_cursor: int = 0,
        limit: int = 100,
        kind: str | None = None,
    ) -> tuple[Event, ...]:
        params = {"channel": channel, "after_cursor": after_cursor, "limit": limit}
        if kind is not None:
            params["kind"] = kind
        data = (await self._request("GET", "/events", params=params)).json()
        return tuple(Event.model_validate(item) for item in data)

    async def create_subscription(
        self,
        channel: str,
        *,
        consumer: str | None = None,
        batch_size: int = 100,
        filters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Subscription:
        return Subscription.model_validate(
            (
                await self._request(
                    "POST",
                    "/subscriptions",
                    json={
                        "channel": channel,
                        "consumer": consumer,
                        "batch_size": batch_size,
                        "filters": filters or {},
                        "metadata": metadata or {},
                    },
                )
            ).json()
        )

    async def pull_subscription(
        self,
        subscription_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        params = {"limit": limit} if limit is not None else None
        data = (
            await self._request(
                "POST",
                f"/subscriptions/{subscription_id}/pull",
                params=params,
            )
        ).json()
        return tuple(Event.model_validate(item) for item in data)

    async def get_subscription(self, subscription_id: str) -> Subscription:
        return Subscription.model_validate(
            (await self._request("GET", f"/subscriptions/{subscription_id}")).json()
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
        payload = _artifact_payload(data)
        return Artifact.model_validate(
            (
                await self._request(
                    "POST",
                    "/artifacts",
                    json={
                        "data": payload["data"],
                        "encoding": payload["encoding"],
                        "channel": channel,
                        "media_type": media_type,
                        "metadata": metadata or {},
                        "event_ids": list(event_ids),
                    },
                )
            ).json()
        )

    async def read_artifact(self, artifact_id: str) -> bytes:
        return (await self._request("GET", f"/artifacts/{artifact_id}")).content

    async def put_snapshot(self, name: str, value: dict[str, Any]) -> Snapshot:
        return Snapshot.model_validate(
            (await self._request("PUT", f"/snapshots/{name}", json=value)).json()
        )

    async def get_snapshot(self, name: str) -> Snapshot:
        return Snapshot.model_validate(
            (await self._request("GET", f"/snapshots/{name}")).json()
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
        return channel.model_dump(mode="json", by_alias=True)
    return channel


def _dump_event(event: Event | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, Event):
        return event.model_dump(mode="json", by_alias=True)
    return event


def _artifact_payload(data: bytes | str) -> dict[str, str]:
    if isinstance(data, bytes):
        return {
            "data": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
        }
    return {"data": data, "encoding": "text"}


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
        error_type=error.get("type") if isinstance(error, dict) else None,
        message=error.get("message") if isinstance(error, dict) else None,
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
