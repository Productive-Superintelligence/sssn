from __future__ import annotations

from sssn.core.channel import BaseChannel


class PeriodicSourceChannel(BaseChannel):
    """
    A channel whose data originates from a periodic pull loop.

    PeriodicSourceChannel inherits directly from BaseChannel and therefore
    uses the full background loop (on_pull → on_process → on_maintain)
    started by BaseChannel.start().

    Pattern
    -------
    Subclass PeriodicSourceChannel and implement two abstract methods:

    pull_fn()
        Called every ``period`` seconds inside the background loop.
        Use it to fetch data from an external source (API, sensor, file,
        database, etc.) and push raw items into the channel via write().

        Example::

            async def pull_fn(self) -> None:
                data = await my_api.fetch_latest()
                await self.write(sender_id="sensor-1", data=data)

    convert_fn(sender_id, raw_data)
        Transform a raw item from pull_fn (or an external write()) into a
        ChannelMessage.  Return None to silently discard the item.

        Example::

            async def convert_fn(self, sender_id: str, raw_data: Any):
                return ChannelMessage(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    sender_id=sender_id,
                    content=MyContent(**raw_data),
                )

    Lifecycle
    ---------
    ``start()`` creates the background asyncio Task (inherited from
    BaseChannel).  ``stop()`` sets ``_is_running = False``; the loop exits
    after the current iteration.  Use ``drain()`` for graceful shutdown that
    waits for the raw buffer to clear.

    Configuration
    -------------
    period (seconds)
        Controls how often pull_fn() is called.  Set via __init__ kwarg.
        Default: 60.0.

    maintenance_interval_seconds
        How often on_maintain() runs for retention enforcement.
        Default: 60.0.

    Typical usage::

        class TemperatureSensor(PeriodicSourceChannel):
            async def pull_fn(self) -> None:
                reading = await sensor_api.read()
                await self.write("sensor", reading)

            async def convert_fn(self, sender_id, raw_data):
                return ChannelMessage(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    sender_id=sender_id,
                    content=GenericContent(data=raw_data),
                )

        channel = TemperatureSensor(
            id="temp-sensor",
            name="Temperature Sensor",
            period=5.0,        # pull every 5 seconds
        )
        await channel.start()
    """
    # No additional state or overrides: the full BaseChannel loop is used
    # as-is.  The two abstract methods (pull_fn / convert_fn) must be
    # implemented by concrete subclasses.
