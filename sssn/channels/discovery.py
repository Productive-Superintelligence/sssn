from __future__ import annotations

import time
import uuid
from typing import List, Optional

from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import ChannelInfo, ChannelMessage, MessageContent, Visibility


# ---------------------------------------------------------------------------
# Registration content types
# ---------------------------------------------------------------------------


class ChannelRegistration(MessageContent):
    """
    Registration record for a single channel.

    info        — ChannelInfo serialised as a plain dict (model_dump()).
    expires_at  — Unix epoch float after which the record is considered stale.
    """

    info: dict
    expires_at: float


class SystemRegistration(MessageContent):
    """
    Registration record for a system and its service descriptor.

    descriptor  — ServiceDescriptor serialised as a plain dict (model_dump()).
    expires_at  — Unix epoch float after which the record is considered stale.
    """

    descriptor: dict
    expires_at: float


# ---------------------------------------------------------------------------
# DiscoveryChannel
# ---------------------------------------------------------------------------


class DiscoveryChannel(PassthroughChannel):
    """
    A self-contained service registry implemented as a PassthroughChannel.

    Systems publish themselves (or their channels) by calling
    register_channel() / register_system().  Registrations have a TTL and
    are evicted by on_maintain() when they expire.

    Query methods (find_channels, find_systems, get_channel, get_system)
    work entirely in-memory and filter on the live message store, so there
    is no separate index to maintain.

    Typical usage::

        disc = DiscoveryChannel(
            id="discovery",
            name="Service Discovery",
            visibility=Visibility.PUBLIC,
            registration_ttl=3600.0,
        )
        await disc.start()

        # Publish a channel
        await disc.register_channel(my_channel.info)

        # Find all public channels
        public = await disc.find_channels(visibility=Visibility.PUBLIC)

        # Find systems with a specific capability
        agents = await disc.find_systems(capability="process_image")
    """

    def __init__(self, registration_ttl: float = 3600.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registration_ttl = registration_ttl

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    async def register_channel(
        self,
        info: ChannelInfo,
        ttl: Optional[float] = None,
    ) -> None:
        """
        Register or refresh a channel in the discovery store.

        A ChannelRegistration message is written directly into the store.
        Any previous registration for the same channel remains until it
        expires (on_maintain() will evict it).
        """
        expires_at = time.time() + (ttl if ttl is not None else self.registration_ttl)
        reg = ChannelRegistration(info=info.model_dump(), expires_at=expires_at)
        msg = ChannelMessage(
            id=f"channel-{info.id}-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            sender_id="_discovery",
            content=reg,
        )
        await self.write(sender_id="_discovery", data=msg, direct=True)

    async def register_system(
        self,
        descriptor,  # ServiceDescriptor (imported lazily to avoid circulars)
        ttl: Optional[float] = None,
    ) -> None:
        """
        Register or refresh a system's service descriptor in the discovery store.

        descriptor should be a ServiceDescriptor instance (from sssn.core.system).
        """
        expires_at = time.time() + (ttl if ttl is not None else self.registration_ttl)
        reg = SystemRegistration(
            descriptor=descriptor.model_dump(), expires_at=expires_at
        )
        msg = ChannelMessage(
            id=f"system-{descriptor.system_id}-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            sender_id="_discovery",
            content=reg,
        )
        await self.write(sender_id="_discovery", data=msg, direct=True)

    # ------------------------------------------------------------------
    # Internal helpers — live record views
    # ------------------------------------------------------------------

    def _live_channel_regs(self) -> List[ChannelRegistration]:
        """Return all non-expired ChannelRegistration records."""
        now = time.time()
        return [
            m.content
            for m in self._store.messages
            if isinstance(m.content, ChannelRegistration)
            and m.content.expires_at > now
        ]

    def _live_system_regs(self) -> List[SystemRegistration]:
        """Return all non-expired SystemRegistration records."""
        now = time.time()
        return [
            m.content
            for m in self._store.messages
            if isinstance(m.content, SystemRegistration)
            and m.content.expires_at > now
        ]

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    async def find_channels(
        self,
        visibility: Optional[Visibility] = None,
    ) -> List[ChannelInfo]:
        """
        Return ChannelInfo for all live channel registrations.

        visibility: if provided, filter to channels with that Visibility value.
        """
        regs = self._live_channel_regs()
        infos = [ChannelInfo(**r.info) for r in regs]
        if visibility is not None:
            infos = [i for i in infos if i.visibility == visibility]
        return infos

    async def find_systems(
        self,
        capability: Optional[str] = None,
    ) -> List[dict]:
        """
        Return raw ServiceDescriptor dicts for all live system registrations.

        capability: if provided, filter to systems that expose a service
        method with that exact name.
        """
        regs = self._live_system_regs()
        descs = [r.descriptor for r in regs]
        if capability is not None:
            descs = [
                d for d in descs
                if any(m["name"] == capability for m in d.get("services", []))
            ]
        return descs

    async def get_channel(self, channel_id: str) -> Optional[ChannelInfo]:
        """Return ChannelInfo for a specific channel ID, or None if not found."""
        for reg in self._live_channel_regs():
            info = ChannelInfo(**reg.info)
            if info.id == channel_id:
                return info
        return None

    async def get_system(self, system_id: str) -> Optional[dict]:
        """Return raw descriptor dict for a specific system ID, or None."""
        for reg in self._live_system_regs():
            if reg.descriptor.get("system_id") == system_id:
                return reg.descriptor
        return None

    # ------------------------------------------------------------------
    # Maintenance — evict expired registrations
    # ------------------------------------------------------------------

    async def on_maintain(self) -> None:
        """
        Periodic housekeeping: remove messages whose registration TTL has
        elapsed in addition to the standard retention policy from super().
        """
        await super().on_maintain()
        now = time.time()
        expired_ids = [
            m.id
            for m in self._store.messages
            if isinstance(m.content, (ChannelRegistration, SystemRegistration))
            and m.content.expires_at <= now
        ]
        if expired_ids:
            self._store.remove(expired_ids)
