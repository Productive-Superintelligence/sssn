from __future__ import annotations

import abc
import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from sssn.core.channel import BaseChannel, Visibility
from sssn.core.client import ChannelClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SystemState
# ---------------------------------------------------------------------------


class SystemState(str, Enum):
    INIT = "INIT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Service descriptor models
# ---------------------------------------------------------------------------


class ServiceMethod(BaseModel):
    name: str
    description: str
    parameters: Dict[str, str] = {}


class ServiceDescriptor(BaseModel):
    system_id: str
    system_name: str
    description: str
    services: List[ServiceMethod]
    channels_read: List[str]
    channels_write: List[str]


# ---------------------------------------------------------------------------
# BaseSystem
# ---------------------------------------------------------------------------


class BaseSystem(abc.ABC):
    """
    Abstract base class for all systems in the SSSN holonic network.

    A system owns channels and subsystems, runs a tick loop, and can be
    published over HTTP or launched purely in-process.

    The design pattern: atomic leaf systems do real work; composite systems
    coordinate their children and manage lifecycle.
    """

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
    ) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.state = SystemState.INIT
        self.client = ChannelClient(system_id=id)
        self._channels: List[BaseChannel] = []
        self._subsystems: List[BaseSystem] = []
        self._is_running = False
        self._setup_done = False
        self._service_descriptor = ServiceDescriptor(
            system_id=id,
            system_name=name,
            description=description,
            services=[],
            channels_read=[],
            channels_write=[],
        )

    # ------------------------------------------------------------------
    # Directory properties
    # ------------------------------------------------------------------

    @property
    def channel_directory(self) -> List[str]:
        """List of all connected channel IDs (local + remote)."""
        return list(self.client._local.keys()) + list(self.client._remote.keys())

    @property
    def system_directory(self) -> List[str]:
        """IDs of all direct subsystems."""
        return [s.id for s in self._subsystems]

    # ------------------------------------------------------------------
    # Overridable lifecycle hooks
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """
        One-time setup: create channels and subsystems.
        Called automatically by launch() / publish() before the run loop.
        Override in subclasses to build topology.
        """
        pass

    async def step(self) -> None:
        """
        Per-tick logic.  Called once per cycle by the run loop.
        Override in subclasses to implement system behaviour.
        """
        pass

    async def on_step_error(self, error: Exception) -> None:
        """
        Called when step() raises an exception.
        Default: log the error and continue running.
        Override to implement recovery, circuit-breaking, etc.
        """
        logger.error("[%s] Error in step(): %s", self.id, error)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self, tick_rate: float = 1.0) -> None:
        """
        Start the step loop.

        tick_rate: desired ticks per second.  The loop compensates for the
        time consumed by step() so that long steps do not accumulate drift.
        Minimum sleep time is 0 (i.e., the loop yields to the event loop
        after every step even when step() takes longer than the tick period).
        """
        self._is_running = True
        self.state = SystemState.RUNNING
        sleep_time = 1.0 / tick_rate
        while self._is_running:
            t0 = time.monotonic()
            try:
                await self.step()
            except Exception as e:
                await self.on_step_error(e)
            if not self._is_running:
                break
            elapsed = time.monotonic() - t0
            remaining = sleep_time - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
        self.state = SystemState.STOPPED

    def stop(self) -> None:
        """Signal the run loop to exit after the current step completes."""
        self._is_running = False

    def pause(self) -> None:
        """
        Mark the system as PAUSED for external inspection.
        Note: the run loop continues executing; actual suspension is not
        yet implemented.  Override run() if you need real pause semantics.
        """
        self.state = SystemState.PAUSED

    def resume(self) -> None:
        """Return to RUNNING state after a pause()."""
        self.state = SystemState.RUNNING

    # ------------------------------------------------------------------
    # Topology builders
    # ------------------------------------------------------------------

    def add_channel(self, channel: BaseChannel) -> None:
        """
        Register a channel with this system and connect it to the client.
        The channel is started separately by launch() / publish().
        """
        self._channels.append(channel)
        self.client.connect(channel.id, channel)

    def add_subsystem(
        self,
        system: BaseSystem,
        channels: Optional[List[str]] = None,
    ) -> None:
        """
        Register a subsystem.

        channels: optional list of channel IDs (owned by this system) that
        should also be connected to the subsystem's client so it can
        read/write them directly.
        """
        self._subsystems.append(system)
        if channels:
            for ch_id in channels:
                ch = next((c for c in self._channels if c.id == ch_id), None)
                if ch:
                    system.client.connect(ch_id, ch)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def all_channels(self) -> List[BaseChannel]:
        """All channels owned by this system."""
        return list(self._channels)

    @property
    def all_systems(self) -> List[BaseSystem]:
        """All direct subsystems."""
        return list(self._subsystems)

    def get_public_channels(self) -> List[BaseChannel]:
        """Return channels with PUBLIC visibility."""
        return [ch for ch in self._channels if ch.visibility == Visibility.PUBLIC]

    # ------------------------------------------------------------------
    # Launch and publish
    # ------------------------------------------------------------------

    async def launch(self) -> None:
        """
        Start all channels and run this system plus all subsystems in-process.

        Calls setup() once, starts every channel's background loop, then
        gathers all subsystem run() coroutines alongside this system's own
        run() loop.
        """
        if not self._setup_done:
            await self.setup()
            self._setup_done = True
        for ch in self._channels:
            await ch.start()
        tasks = [s.run() for s in self._subsystems]
        tasks.append(self.run())
        await asyncio.gather(*tasks)

    async def publish(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        server: Any = None,
    ) -> None:
        """
        Start all channels and expose PUBLIC ones over HTTP via ChannelServer.

        Calls setup() once, attaches HttpTransport to every PUBLIC channel,
        starts all channel loops, runs all systems, and serves the HTTP server.
        """
        if not self._setup_done:
            await self.setup()
            self._setup_done = True

        from sssn.infra.server import ChannelServer  # noqa: PLC0415
        from sssn.core.transport import HttpTransport  # noqa: PLC0415

        server = server or ChannelServer(host=host, port=port)

        for ch in self._channels:
            if ch.visibility == Visibility.PUBLIC:
                ch.attach_transport(HttpTransport(server=server))
            await ch.start()

        # If there is a discovery channel, register all public channels.
        disc = next(
            (ch for ch in self._channels if hasattr(ch, "register_channel")),
            None,
        )
        if disc:
            for ch in self.get_public_channels():
                await disc.register_channel(ch.info)

        tasks: List[Any] = [s.run() for s in self._subsystems]
        tasks.append(self.run())
        tasks.append(server.start())
        await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Channel convenience methods
    # ------------------------------------------------------------------

    async def read_channel(
        self,
        ch_id: str,
        **kw: Any,
    ) -> Any:
        """Read from a channel via this system's client."""
        return await self.client.read(ch_id, **kw)

    async def write_channel(
        self,
        ch_id: str,
        **kw: Any,
    ) -> Any:
        """Write to a channel via this system's client."""
        return await self.client.write(ch_id, **kw)

    async def claim_channel(
        self,
        ch_id: str,
        **kw: Any,
    ) -> Any:
        """Exclusive read (claim) from a channel."""
        return await self.client.read(ch_id, exclusive=True, **kw)

    async def acknowledge_channel(
        self,
        ch_id: str,
        message_ids: List[str],
    ) -> None:
        """Acknowledge exclusively-claimed messages."""
        return await self.client.acknowledge(ch_id, message_ids)

    async def nack_channel(
        self,
        ch_id: str,
        message_ids: List[str],
    ) -> None:
        """Nack (release) exclusively-claimed messages."""
        return await self.client.nack(ch_id, message_ids)

    async def subscribe_channel(
        self,
        ch_id: str,
        cb: Callable,
    ) -> None:
        """Subscribe a push callback to a channel."""
        return await self.client.subscribe(ch_id, cb)

    async def announce(self, discovery_channel_id: str) -> None:
        """
        Broadcast this system's service descriptor to a discovery channel.
        The descriptor is written as a non-direct (buffered) message so it
        flows through the channel's convert_fn pipeline.
        """
        await self.client.write(
            discovery_channel_id,
            data=self._service_descriptor.model_dump(),
            direct=False,
        )


# ---------------------------------------------------------------------------
# Module-level helper functions (sssn.register, sssn.system, sssn.expose)
# ---------------------------------------------------------------------------


def register(id: str, name: str, description: str = "") -> ChannelClient:
    """
    Lightweight registration: create a ChannelClient for a system that does
    not subclass BaseSystem.  Useful for simple scripts and standalone agents.

    Returns a ChannelClient pre-configured with the given system_id.
    """
    return ChannelClient(system_id=id)


def system(id: str, name: str, description: str = "") -> Callable:
    """
    Class decorator that injects SSSN plumbing into a plain Python class.

    Usage::

        @sssn.system(id="my-agent", name="My Agent")
        class MyAgent:
            @sssn.expose(description="Does something useful")
            async def do_work(self): ...

    The decorator:
      - Wraps __init__ to inject ``self.client`` and ``self._service_descriptor``.
      - Collects all methods decorated with @expose and registers them as
        ServiceMethod entries on the descriptor.
      - Attaches ``_sssn_system_id`` and ``_sssn_system_name`` class attributes.
    """

    def decorator(cls: type) -> type:
        # Collect exposed methods before patching __init__.
        methods: List[ServiceMethod] = []
        for attr_name in dir(cls):
            method = getattr(cls, attr_name, None)
            if callable(method) and hasattr(method, "_sssn_expose"):
                meta = method._sssn_expose
                methods.append(
                    ServiceMethod(
                        name=attr_name,
                        description=meta.get("description", ""),
                    )
                )

        original_init = cls.__init__

        def new_init(self_inner: Any, **kwargs: Any) -> None:
            original_init(self_inner, **kwargs)
            self_inner.client = ChannelClient(system_id=id)
            self_inner._service_descriptor = ServiceDescriptor(
                system_id=id,
                system_name=name,
                description=description,
                services=methods,
                channels_read=[],
                channels_write=[],
            )

        cls.__init__ = new_init
        cls._sssn_system_id = id
        cls._sssn_system_name = name
        return cls

    return decorator


def expose(description: str = "") -> Callable:
    """
    Method decorator that marks a method as part of a system's public service
    API.  Used together with @sssn.system to auto-populate the ServiceDescriptor.

    Usage::

        @sssn.expose(description="Returns current status")
        async def status(self) -> dict: ...
    """

    def decorator(func: Callable) -> Callable:
        func._sssn_expose = {"description": description}
        return func

    return decorator
