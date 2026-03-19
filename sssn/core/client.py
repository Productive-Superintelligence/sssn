from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from sssn.core.channel import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)


class ChannelClient:
    """
    Handle for channel operations from a system's perspective.

    Resolves channel IDs to either local in-process references or remote
    HTTP endpoints and dispatches accordingly.

    Local channels: direct Python method calls — zero overhead.
    Remote channels: HTTP via httpx.AsyncClient, using the stored token.

    Cursor state for remote shared reads is managed server-side and keyed
    by the authenticated system_id embedded in the request token.
    """

    def __init__(self, system_id: str) -> None:
        self.system_id = system_id
        self._local: dict[str, BaseChannel] = {}
        self._remote: dict[str, tuple[str, str]] = {}  # channel_id → (url, token)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, channel_id: str, channel: BaseChannel) -> None:
        """
        Connect a local in-process channel reference.
        Raises ValueError if channel is None.
        """
        if channel is None:
            raise ValueError(f"channel must not be None (channel_id={channel_id!r}).")
        self._local[channel_id] = channel

    def connect_remote(
        self, channel_id: str, url: str, token: str | None = None
    ) -> None:
        """
        Connect a remote channel accessible over HTTP.

        url:   Base URL of the channel endpoint, e.g.
               "http://host:8000/channels/my-channel".
               The client uses this URL directly for read/write operations.
        token: Bearer token for the Authorization header.  Empty string if
               no auth is needed (OpenSecurity).
        """
        self._remote[channel_id] = (url.rstrip("/"), token or "")

    def connect_from_config(self, config: dict[str, str]) -> None:
        """
        Bulk connect remote channels from a mapping of channel_id → url.
        No token is stored — use connect_remote() directly when a token is
        needed.
        """
        for ch_id, url in config.items():
            self.connect_remote(ch_id, url)

    # ------------------------------------------------------------------
    # Consumption interface — local dispatch
    # ------------------------------------------------------------------

    async def read(
        self,
        channel_id: str,
        limit: int = 10,
        exclusive: bool = False,
        after: str | None = None,
    ) -> list[ChannelMessage]:
        if channel_id in self._local:
            return await self._local[channel_id].read(
                reader_id=self.system_id,
                limit=limit,
                exclusive=exclusive,
                after=after,
            )
        if channel_id in self._remote:
            return await self._http_read(
                channel_id, limit=limit, exclusive=exclusive, after=after
            )
        raise KeyError(f"Channel '{channel_id}' is not connected.")

    async def write(
        self,
        channel_id: str,
        data: Any,
        direct: bool = False,
    ) -> str:
        if channel_id in self._local:
            return await self._local[channel_id].write(
                sender_id=self.system_id, data=data, direct=direct
            )
        if channel_id in self._remote:
            return await self._http_write(channel_id, data=data, direct=direct)
        raise KeyError(f"Channel '{channel_id}' is not connected.")

    async def acknowledge(
        self, channel_id: str, message_ids: list[str]
    ) -> None:
        if channel_id in self._local:
            return await self._local[channel_id].acknowledge(
                reader_id=self.system_id, message_ids=message_ids
            )
        if channel_id in self._remote:
            return await self._http_acknowledge(channel_id, message_ids)
        raise KeyError(f"Channel '{channel_id}' is not connected.")

    async def nack(
        self, channel_id: str, message_ids: list[str]
    ) -> None:
        if channel_id in self._local:
            return await self._local[channel_id].nack(
                reader_id=self.system_id, message_ids=message_ids
            )
        if channel_id in self._remote:
            return await self._http_nack(channel_id, message_ids)
        raise KeyError(f"Channel '{channel_id}' is not connected.")

    async def subscribe(
        self,
        channel_id: str,
        callback: Callable[[ChannelMessage], Any],
    ) -> None:
        """
        Register a push callback for new messages.
        Local channels only — remote channels do not support push (HTTP is
        request-response only).  See §4.9 of the architecture spec.
        """
        if channel_id in self._local:
            return await self._local[channel_id].subscribe(
                system_id=self.system_id, callback=callback
            )
        if channel_id in self._remote:
            raise TypeError(
                f"subscribe() is not supported for remote channels ('{channel_id}'). "
                "Use read() polling instead."
            )
        raise KeyError(f"Channel '{channel_id}' is not connected.")

    async def unsubscribe(self, channel_id: str) -> None:
        """Remove a previously registered push callback.  Local channels only."""
        if channel_id in self._local:
            return await self._local[channel_id].unsubscribe(
                system_id=self.system_id
            )
        # Silently ignore for remote — no subscription was registered.

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self, token: str) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _parse_messages(self, data: list[dict]) -> list[ChannelMessage]:
        from sssn.core.channel import ChannelMessage  # noqa: PLC0415

        messages: list[ChannelMessage] = []
        for item in data:
            try:
                messages.append(ChannelMessage.model_validate(item))
            except Exception as exc:
                logger.warning("ChannelClient: failed to parse message: %s", exc)
        return messages

    def _raise_for_status(self, response: Any, operation: str) -> None:
        """Raise an appropriate Python exception for 4xx/5xx responses."""
        status = response.status_code
        if status == 401:
            raise PermissionError(
                f"HTTP {status} Unauthorised during '{operation}'. Check your token."
            )
        if status == 403:
            raise PermissionError(
                f"HTTP {status} Forbidden during '{operation}'. "
                f"system_id='{self.system_id}' lacks permission."
            )
        if status == 404:
            raise KeyError(f"HTTP {status} Not Found during '{operation}'.")
        if status == 429:
            raise RuntimeError(
                f"HTTP {status} Too Many Requests during '{operation}' "
                "(channel buffer full)."
            )
        if status >= 400:
            raise RuntimeError(
                f"HTTP {status} error during '{operation}': {response.text}"
            )

    async def _http_read(
        self,
        channel_id: str,
        limit: int = 10,
        exclusive: bool = False,
        after: str | None = None,
    ) -> list[ChannelMessage]:
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "httpx is required for remote channel access. "
                "Install it with: pip install httpx"
            ) from exc

        url, token = self._remote[channel_id]
        params: dict[str, Any] = {"limit": limit, "exclusive": exclusive}
        if after is not None:
            params["after"] = after

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, params=params, headers=self._headers(token)
            )

        self._raise_for_status(response, "read")
        body = response.json()
        return self._parse_messages(body.get("messages", []))

    async def _http_write(
        self,
        channel_id: str,
        data: Any,
        direct: bool = False,
    ) -> str:
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "httpx is required for remote channel access. "
                "Install it with: pip install httpx"
            ) from exc

        url, token = self._remote[channel_id]

        # Serialise data to a JSON-compatible dict.
        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        else:
            payload = data

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                json=payload,
                params={"direct": direct},
                headers=self._headers(token),
            )

        self._raise_for_status(response, "write")
        body = response.json()
        return body.get("item_id", "")

    async def _http_acknowledge(
        self, channel_id: str, message_ids: list[str]
    ) -> None:
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "httpx is required for remote channel access. "
                "Install it with: pip install httpx"
            ) from exc

        url, token = self._remote[channel_id]
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{url}/acknowledge",
                json={"message_ids": message_ids},
                headers=self._headers(token),
            )
        self._raise_for_status(response, "acknowledge")

    async def _http_nack(
        self, channel_id: str, message_ids: list[str]
    ) -> None:
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "httpx is required for remote channel access. "
                "Install it with: pip install httpx"
            ) from exc

        url, token = self._remote[channel_id]
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{url}/nack",
                json={"message_ids": message_ids},
                headers=self._headers(token),
            )
        self._raise_for_status(response, "nack")
