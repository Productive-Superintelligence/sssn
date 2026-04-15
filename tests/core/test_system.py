import asyncio

import pytest
from fastapi import FastAPI

from sssn.channels.discovery import DiscoveryChannel
from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import Visibility
from sssn.core.system import BaseSystem, SystemState
from sssn.core.transport import HttpTransport


class IdleSystem(BaseSystem):
    async def step(self) -> None:
        self.stop()


class CountingSubsystem(BaseSystem):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.step_count = 0

    async def step(self) -> None:
        self.step_count += 1
        self.stop()


class PauseMarkerSystem(BaseSystem):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.step_count = 0
        self.continued_while_paused = False

    async def step(self) -> None:
        self.step_count += 1
        if self.step_count == 1:
            self.pause()
            return
        if self.state == SystemState.PAUSED:
            self.continued_while_paused = True
            self.resume()
        if self.step_count >= 3:
            self.stop()


class LaunchSystem(BaseSystem):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.worker: CountingSubsystem | None = None
        self.events: PassthroughChannel | None = None

    async def setup(self) -> None:
        self.events = PassthroughChannel(
            id="events",
            name="Events",
            description="Parent-owned work channel",
        )
        self.add_channel(self.events)
        self.worker = CountingSubsystem(id="worker", name="Worker")
        self.add_subsystem(self.worker, channels=["events"])

    async def step(self) -> None:
        for subsystem in self.all_systems:
            subsystem.stop()
        self.stop()


class PublishSystem(BaseSystem):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.discovery: DiscoveryChannel | None = None
        self.public_feed: PassthroughChannel | None = None
        self.private_feed: PassthroughChannel | None = None

    async def setup(self) -> None:
        self.discovery = DiscoveryChannel(
            id="discovery",
            name="Discovery",
            description="Service discovery",
            visibility=Visibility.PUBLIC,
        )
        self.public_feed = PassthroughChannel(
            id="public-feed",
            name="Public Feed",
            description="Exposed over HTTP",
            visibility=Visibility.PUBLIC,
        )
        self.private_feed = PassthroughChannel(
            id="private-feed",
            name="Private Feed",
            description="Local only",
            visibility=Visibility.PRIVATE,
        )
        self.add_channel(self.discovery)
        self.add_channel(self.public_feed)
        self.add_channel(self.private_feed)

    async def step(self) -> None:
        self.stop()


class FakeServer:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.started = False

    async def start(self) -> None:
        self.started = True


def test_add_subsystem_connects_only_explicit_channels():
    parent = IdleSystem(id="parent", name="Parent")
    allowed = PassthroughChannel(id="allowed", name="Allowed", description="")
    denied = PassthroughChannel(id="denied", name="Denied", description="")
    parent.add_channel(allowed)
    parent.add_channel(denied)

    child = IdleSystem(id="child", name="Child")
    parent.add_subsystem(child, channels=["allowed"])

    assert "allowed" in child.channel_directory
    assert "denied" not in child.channel_directory


@pytest.mark.asyncio
async def test_launch_starts_channels_and_subsystems_in_process():
    system = LaunchSystem(id="launcher", name="Launcher")

    await system.launch()

    assert system._setup_done is True
    assert system.worker is not None
    assert system.worker.step_count == 1
    assert "events" in system.worker.channel_directory
    assert system.events is not None
    assert system.events._is_running is True

    await system.events.drain(timeout=0.01)


@pytest.mark.asyncio
async def test_pause_is_marker_only_and_run_loop_continues():
    system = PauseMarkerSystem(id="pause-test", name="Pause Test")

    await system.run(tick_rate=1000.0)

    assert system.continued_while_paused is True
    assert system.step_count >= 3
    assert system.state == SystemState.STOPPED


@pytest.mark.asyncio
async def test_publish_attaches_http_transport_only_to_public_channels_and_registers_discovery():
    system = PublishSystem(id="publisher", name="Publisher")
    server = FakeServer()

    await system.publish(server=server)

    assert server.started is True
    assert system.discovery is not None
    assert system.public_feed is not None
    assert system.private_feed is not None
    assert isinstance(system.discovery.transport, HttpTransport)
    assert isinstance(system.public_feed.transport, HttpTransport)
    assert system.private_feed.transport is None

    public_channels = await system.discovery.find_channels(visibility=Visibility.PUBLIC)
    public_ids = {channel.id for channel in public_channels}
    assert public_ids == {"discovery", "public-feed"}
    assert "private-feed" not in public_ids

    await asyncio.gather(
        system.discovery.drain(timeout=0.01),
        system.public_feed.drain(timeout=0.01),
        system.private_feed.drain(timeout=0.01),
    )
