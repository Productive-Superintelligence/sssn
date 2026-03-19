from __future__ import annotations

import abc
import logging
import time
import uuid
from typing import Any

import jwt

logger = logging.getLogger(__name__)


class ChannelSecurity(abc.ABC):
    """Abstract base class for channel security."""

    @abc.abstractmethod
    async def authenticate(self, token: str) -> str | None:
        """Verify token and return system_id, or None if invalid."""
        ...

    @abc.abstractmethod
    async def authorize_read(self, system_id: str, channel_id: str) -> bool:
        """Return True if system_id may read from channel_id."""
        ...

    @abc.abstractmethod
    async def authorize_write(self, system_id: str, channel_id: str) -> bool:
        """Return True if system_id may write to channel_id."""
        ...

    @abc.abstractmethod
    async def authorize_admin(self, system_id: str, channel_id: str) -> bool:
        """Return True if system_id has admin access to channel_id."""
        ...

    @abc.abstractmethod
    async def generate_token(
        self,
        system_id: str,
        role: str,
        channel_ids: list[str] | None = None,
        expires_in: float = 86400,
    ) -> str:
        """Generate a credential token for system_id with the given role."""
        ...


# ---------------------------------------------------------------------------
# OpenSecurity
# ---------------------------------------------------------------------------

class OpenSecurity(ChannelSecurity):
    """
    No authentication or authorization — everyone is allowed.
    The token IS the system_id. Intended for local development only.
    """

    async def authenticate(self, token: str) -> str | None:
        return token  # token is treated as the system_id directly

    async def authorize_read(self, system_id: str, channel_id: str) -> bool:
        return True

    async def authorize_write(self, system_id: str, channel_id: str) -> bool:
        return True

    async def authorize_admin(self, system_id: str, channel_id: str) -> bool:
        return True

    async def generate_token(
        self,
        system_id: str,
        role: str,
        channel_ids: list[str] | None = None,
        expires_in: float = 86400,
    ) -> str:
        return system_id


# ---------------------------------------------------------------------------
# ACLSecurity
# ---------------------------------------------------------------------------

class ACLSecurity(ChannelSecurity):
    """
    Simple access-control lists keyed by system_id.
    Uses system_id directly as credential (no cryptographic token needed).
    Roles: "read" grants read access; "write" grants read + write access;
    "admin" grants read + write + admin access.
    """

    def __init__(
        self,
        read: list[str] | None = None,
        write: list[str] | None = None,
        admin: list[str] | None = None,
    ) -> None:
        self._read: set[str] = set(read or [])
        self._write: set[str] = set(write or [])
        self._admin: set[str] = set(admin or [])

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def grant(self, system_id: str, role: str) -> None:
        """
        Grant system_id the given role.
        role must be "read", "write", or "admin".
        Granting write also grants read; granting admin grants everything.
        """
        role = role.lower()
        if role == "admin":
            self._admin.add(system_id)
            self._write.add(system_id)
            self._read.add(system_id)
        elif role == "write":
            self._write.add(system_id)
            self._read.add(system_id)
        elif role == "read":
            self._read.add(system_id)
        else:
            raise ValueError(f"Unknown role: {role!r}. Must be 'read', 'write', or 'admin'.")

    def revoke(self, system_id: str) -> None:
        """Remove system_id from all ACL sets."""
        self._read.discard(system_id)
        self._write.discard(system_id)
        self._admin.discard(system_id)

    # ------------------------------------------------------------------
    # ChannelSecurity implementation
    # ------------------------------------------------------------------

    async def authenticate(self, token: str) -> str | None:
        # For ACLSecurity the token IS the system_id.
        return token

    async def authorize_read(self, system_id: str, channel_id: str) -> bool:
        return system_id in self._read or system_id in self._write or system_id in self._admin

    async def authorize_write(self, system_id: str, channel_id: str) -> bool:
        return system_id in self._write or system_id in self._admin

    async def authorize_admin(self, system_id: str, channel_id: str) -> bool:
        return system_id in self._admin

    async def generate_token(
        self,
        system_id: str,
        role: str,
        channel_ids: list[str] | None = None,
        expires_in: float = 86400,
    ) -> str:
        """
        Register system_id with the given role and return a token (the system_id itself).
        channel_ids is accepted for API compatibility but is ignored — ACLSecurity is
        channel-agnostic (a single ACL instance guards one channel).
        """
        self.grant(system_id, role)
        return system_id


# ---------------------------------------------------------------------------
# JWTChannelSecurity
# ---------------------------------------------------------------------------

class JWTChannelSecurity(ChannelSecurity):
    """
    JWT-based security with optional per-channel token scoping.

    Token payload:
        sub      — system_id
        role     — "read" | "write" | "admin"
        exp      — expiry (Unix epoch float)
        jti      — unique token ID
        channels — List[str] | null (null means all channels)

    authenticate() / authorize_*() return True for in-process (local) calls
    because the HTTP transport performs full token validation before calling
    into the channel. For HTTP callers, use authorize_from_token() directly.
    """

    def __init__(self, secret: str, algorithm: str = "HS256") -> None:
        self._secret = secret
        self._algorithm = algorithm

    # ------------------------------------------------------------------
    # Token generation
    # ------------------------------------------------------------------

    async def generate_token(
        self,
        system_id: str,
        role: str,
        channel_ids: list[str] | None = None,
        expires_in: float = 86400,
    ) -> str:
        payload: dict[str, Any] = {
            "sub": system_id,
            "role": role,
            "exp": time.time() + expires_in,
            "jti": uuid.uuid4().hex,
        }
        if channel_ids is not None:
            payload["channels"] = channel_ids
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    # ------------------------------------------------------------------
    # Local (in-process) auth — always allow, transport validates fully
    # ------------------------------------------------------------------

    async def authenticate(self, token: str) -> str | None:
        """Decode JWT and return sub (system_id), or None if invalid/expired."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
            return payload.get("sub")
        except jwt.PyJWTError:
            return None

    async def authorize_read(self, system_id: str, channel_id: str) -> bool:
        """
        For local (in-process) calls: always allow.
        HTTP transport uses authorize_from_token() for full validation.
        """
        return True

    async def authorize_write(self, system_id: str, channel_id: str) -> bool:
        return True

    async def authorize_admin(self, system_id: str, channel_id: str) -> bool:
        return True

    # ------------------------------------------------------------------
    # Full validation — used by HttpTransport
    # ------------------------------------------------------------------

    async def authorize_from_token(
        self, token: str, channel_id: str, operation: str
    ) -> str | None:
        """
        Full JWT validation used by the HTTP transport layer.

        Parameters
        ----------
        token:      Bearer token from the Authorization header.
        channel_id: The channel being accessed.
        operation:  "read", "write", or "admin".

        Returns the system_id on success, or None on any failure (expired,
        invalid signature, insufficient role, wrong channel scope).
        """
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError:
            logger.debug("JWT token expired.")
            return None
        except jwt.PyJWTError as exc:
            logger.debug("JWT decode error: %s", exc)
            return None

        system_id: str | None = payload.get("sub")
        role: str | None = payload.get("role")
        channels: list[str] | None = payload.get("channels")  # None → all channels

        if not system_id or not role:
            return None

        # Check channel scope
        if channels is not None and channel_id not in channels:
            return None

        # Check role sufficiency
        op = operation.lower()
        role = role.lower()

        role_order = {"read": 0, "write": 1, "admin": 2}
        required = role_order.get(op, 999)
        granted = role_order.get(role, -1)

        if granted < required:
            return None

        return system_id
