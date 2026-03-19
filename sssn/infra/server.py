from __future__ import annotations


class ChannelServer:
    """
    Thin wrapper around a FastAPI application and a uvicorn server.

    HttpTransport registers routes directly on ``self.app``.  Call
    ``start()`` once all routes have been registered (i.e., after all
    channels have been started with their transports attached).

    Typical usage::

        server = ChannelServer(host="0.0.0.0", port=8000)

        ch = BroadcastChannel(id="events", name="Events",
                               visibility=Visibility.PUBLIC)
        ch.attach_transport(HttpTransport(server=server))
        await ch.start()   # registers routes on server.app

        await server.start()   # blocks until the process is killed
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        try:
            from fastapi import FastAPI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "fastapi is required for ChannelServer. "
                "Install it with: pip install fastapi"
            ) from exc

        self.host = host
        self.port = port
        self.app = FastAPI(title="SSSN Channel Server")

    async def start(self) -> None:
        """
        Start the uvicorn server and block until shutdown.

        This coroutine does not return until the server process exits.
        Run it as part of an asyncio.gather() alongside your system's
        run() loop so they share the same event loop.
        """
        try:
            import uvicorn  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "uvicorn is required for ChannelServer. "
                "Install it with: pip install uvicorn"
            ) from exc

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
