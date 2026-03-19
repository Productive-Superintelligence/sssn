from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sssn.core.channel import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ChannelTransport(abc.ABC):
    """
    Pluggable transport layer for a channel.

    A transport exposes a channel's read/write interface over some protocol.
    The channel itself is protocol-agnostic — the transport is a thin adapter.
    """

    @abc.abstractmethod
    async def start(self, channel: BaseChannel) -> None:
        """Attach this transport to `channel` and begin serving."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """Detach and clean up."""
        ...


# ---------------------------------------------------------------------------
# InProcessTransport
# ---------------------------------------------------------------------------


class InProcessTransport(ChannelTransport):
    """
    Default transport: direct in-process Python calls, zero overhead.
    start() and stop() are no-ops — the channel is already accessible
    as a Python object.
    """

    async def start(self, channel: BaseChannel) -> None:
        pass

    async def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# HttpTransport
# ---------------------------------------------------------------------------

_BEARER_PREFIX = "Bearer "


class HttpTransport(ChannelTransport):
    """
    REST transport via FastAPI.

    Routes registered on the shared ChannelServer's FastAPI application:

      GET  /channels/{ch_id}                → read()
      PUT  /channels/{ch_id}                → write()
      POST /channels/{ch_id}/acknowledge    → acknowledge()
      POST /channels/{ch_id}/nack           → nack()
      GET  /channels/{ch_id}/info           → channel metadata

    Authentication
    --------------
    - The Authorization header must carry a Bearer token.
    - For OpenSecurity / ACLSecurity: the token IS the system_id; full
      read/write/admin checks are delegated to the channel's security object.
    - For JWTChannelSecurity: authorize_from_token() is used to perform full
      JWT validation (expiry, role, channel scope) and extract the system_id.
    - On authentication failure the endpoint returns HTTP 401.
    - On authorisation failure (authenticate() succeeds but the operation is
      denied by the channel) the channel raises PermissionError → HTTP 403.

    The transport does NOT start a server itself — it registers routes on the
    provided ChannelServer.  Call ChannelServer.start() separately.
    """

    def __init__(self, server: Any) -> None:
        # server is a ChannelServer instance (avoiding circular import).
        self._server = server
        self._channel: BaseChannel | None = None

    async def start(self, channel: BaseChannel) -> None:
        self._channel = channel
        self._register_routes(channel)

    async def stop(self) -> None:
        # Routes are registered on the shared app; teardown is managed by
        # the ChannelServer.  Nothing to do here.
        pass

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_routes(self, channel: BaseChannel) -> None:
        try:
            from fastapi import APIRouter, HTTPException, Request  # noqa: PLC0415
            from fastapi.responses import JSONResponse  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "fastapi is required for HttpTransport. "
                "Install it with: pip install fastapi"
            ) from exc

        router = APIRouter()
        ch_id = channel.id
        base = f"/channels/{ch_id}"

        # ---- helpers ----

        async def _authenticate(request: Request) -> str:
            """Extract Bearer token and resolve to a system_id, or raise HTTP 401."""
            auth_header: str = request.headers.get("Authorization", "")
            if not auth_header.startswith(_BEARER_PREFIX):
                raise HTTPException(status_code=401, detail="Missing Bearer token.")
            token = auth_header[len(_BEARER_PREFIX):]

            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            if isinstance(channel.security, JWTChannelSecurity):
                # Full JWT validation (expiry + role + channel scope) via the
                # authorize_from_token() path.  We do a preliminary authenticate()
                # here just to extract the system_id; the actual operation-level
                # check is done by authorize_from_token() in the route handlers.
                system_id = await channel.security.authenticate(token)
            else:
                # OpenSecurity / ACLSecurity: token IS the system_id.
                system_id = await channel.security.authenticate(token)

            if system_id is None:
                raise HTTPException(status_code=401, detail="Invalid or expired token.")
            return system_id

        async def _jwt_authorize(
            request: Request, operation: str
        ) -> str:
            """
            For JWTChannelSecurity: do full token validation and return system_id.
            Raises HTTP 401/403 on failure.
            """
            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            auth_header: str = request.headers.get("Authorization", "")
            if not auth_header.startswith(_BEARER_PREFIX):
                raise HTTPException(status_code=401, detail="Missing Bearer token.")
            token = auth_header[len(_BEARER_PREFIX):]

            if isinstance(channel.security, JWTChannelSecurity):
                system_id = await channel.security.authorize_from_token(
                    token, ch_id, operation
                )
                if system_id is None:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Token does not permit '{operation}' on channel '{ch_id}'.",
                    )
                return system_id
            else:
                # For non-JWT security the normal authenticate → authorize path
                # is used inside the channel methods themselves.
                system_id = await channel.security.authenticate(token)
                if system_id is None:
                    raise HTTPException(status_code=401, detail="Invalid token.")
                return system_id

        def _serialize_messages(msgs: list[ChannelMessage]) -> list[dict]:
            return [m.model_dump() for m in msgs]

        # ---- GET /channels/{ch_id} — read ----

        @router.get(base)
        async def http_read(
            request: Request,
            limit: int = 10,
            exclusive: bool = False,
            after: str | None = None,
        ):
            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            if isinstance(channel.security, JWTChannelSecurity):
                system_id = await _jwt_authorize(request, "read")
            else:
                system_id = await _authenticate(request)

            try:
                msgs = await channel.read(
                    reader_id=system_id,
                    limit=limit,
                    exclusive=exclusive,
                    after=after,
                )
                return {"messages": _serialize_messages(msgs)}
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except Exception as exc:
                logger.error("[%s] HTTP read error: %s", ch_id, exc)
                raise HTTPException(status_code=500, detail="Internal error.")

        # ---- PUT /channels/{ch_id} — write ----

        @router.put(base)
        async def http_write(request: Request, direct: bool = False):
            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            if isinstance(channel.security, JWTChannelSecurity):
                system_id = await _jwt_authorize(request, "write")
            else:
                system_id = await _authenticate(request)

            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body.")

            try:
                if direct:
                    # Reconstruct ChannelMessage from the request body.
                    from sssn.core.channel import ChannelMessage  # noqa: PLC0415

                    msg = ChannelMessage.model_validate(body)
                    item_id = await channel.write(
                        sender_id=system_id, data=msg, direct=True
                    )
                else:
                    item_id = await channel.write(
                        sender_id=system_id, data=body, direct=False
                    )
                return {"status": "accepted", "item_id": item_id}
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except RuntimeError as exc:
                raise HTTPException(status_code=429, detail=str(exc))
            except Exception as exc:
                logger.error("[%s] HTTP write error: %s", ch_id, exc)
                raise HTTPException(status_code=500, detail="Internal error.")

        # ---- POST /channels/{ch_id}/acknowledge ----

        @router.post(f"{base}/acknowledge")
        async def http_acknowledge(request: Request):
            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            if isinstance(channel.security, JWTChannelSecurity):
                system_id = await _jwt_authorize(request, "read")
            else:
                system_id = await _authenticate(request)

            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body.")

            message_ids: list[str] = body.get("message_ids", [])
            if not isinstance(message_ids, list):
                raise HTTPException(
                    status_code=400, detail="'message_ids' must be a list."
                )

            await channel.acknowledge(reader_id=system_id, message_ids=message_ids)
            return {"status": "ok", "acknowledged": len(message_ids)}

        # ---- POST /channels/{ch_id}/nack ----

        @router.post(f"{base}/nack")
        async def http_nack(request: Request):
            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            if isinstance(channel.security, JWTChannelSecurity):
                system_id = await _jwt_authorize(request, "read")
            else:
                system_id = await _authenticate(request)

            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body.")

            message_ids: list[str] = body.get("message_ids", [])
            if not isinstance(message_ids, list):
                raise HTTPException(
                    status_code=400, detail="'message_ids' must be a list."
                )

            await channel.nack(reader_id=system_id, message_ids=message_ids)
            return {"status": "ok", "nacked": len(message_ids)}

        # ---- GET /channels/{ch_id}/info ----

        @router.get(f"{base}/info")
        async def http_info(request: Request):
            from sssn.core.security import JWTChannelSecurity  # noqa: PLC0415

            if isinstance(channel.security, JWTChannelSecurity):
                system_id = await _jwt_authorize(request, "read")
            else:
                system_id = await _authenticate(request)

            return channel.info.model_dump()

        # Register the router on the shared app.
        self._server.app.include_router(router)
        logger.debug(
            "HttpTransport: registered routes for channel '%s'.", ch_id
        )
