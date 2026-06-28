import asyncio

import httpx
import pytest

from sssn import AsyncSSSNClient, LocalStore, SSSNClient, SSSNClientError
from sssn.server import create_app


def test_async_client_calls_fastapi_server(tmp_path):
    app = create_app(LocalStore(tmp_path / "store"))

    async def run():
        client = AsyncSSSNClient(
            "http://testserver",
            transport=httpx.ASGITransport(app=app),
        )
        channel = await client.create_channel({"name": "events"})
        event = await client.append_event({"channel": "events", "payload": {"n": 1}})
        analysis = await client.append_event(
            {"channel": "events", "kind": "analysis", "payload": {"n": 2}}
        )
        events = await client.query_events("events")
        sub = await client.create_subscription("events")
        pulled = await client.pull_subscription(sub.id)
        filtered_sub = await client.create_subscription(
            "events",
            filters={"kind": "analysis"},
        )
        filtered = await client.pull_subscription(filtered_sub.id)
        artifact = await client.write_artifact("hello", channel="events")
        artifact_data = await client.read_artifact(artifact.id)
        binary_artifact = await client.write_artifact(
            b"\xff\x00binary",
            channel="events",
        )
        binary_artifact_data = await client.read_artifact(binary_artifact.id)
        snapshot = await client.put_snapshot("latest", {"channel": "events", "value": {"n": 1}})
        loaded_snapshot = await client.get_snapshot("latest")
        channels = await client.list_channels()
        loaded_channel = await client.get_channel("events")
        return {
            "channel": channel,
            "event": event,
            "analysis": analysis,
            "events": events,
            "pulled": pulled,
            "filtered": filtered,
            "artifact_data": artifact_data,
            "binary_artifact_data": binary_artifact_data,
            "snapshot": snapshot,
            "loaded_snapshot": loaded_snapshot,
            "channels": channels,
            "loaded_channel": loaded_channel,
        }

    result = asyncio.run(run())

    assert result["channel"].name == "events"
    assert result["event"].payload == {"n": 1}
    assert result["events"][0].id == result["event"].id
    assert result["pulled"][0].id == result["event"].id
    assert [event.id for event in result["filtered"]] == [result["analysis"].id]
    assert result["artifact_data"] == b"hello"
    assert result["binary_artifact_data"] == b"\xff\x00binary"
    assert result["snapshot"].name == "latest"
    assert result["loaded_snapshot"].value == {"n": 1}
    assert result["channels"][0].name == "events"
    assert result["loaded_channel"].name == "events"


def test_sync_client_uses_portable_api_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/channels"
        return httpx.Response(
            200,
            json={"name": "events", "schema": None, "form": "log", "description": "", "metadata": {}},
        )

    client = SSSNClient("http://testserver", transport=httpx.MockTransport(handler))

    assert client.create_channel({"name": "events"}).name == "events"


def test_async_client_maps_server_errors(tmp_path):
    app = create_app(LocalStore(tmp_path / "store"))

    async def run():
        client = AsyncSSSNClient(
            "http://testserver",
            transport=httpx.ASGITransport(app=app),
        )
        await client.get_channel("missing")

    with pytest.raises(SSSNClientError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_type == "ChannelNotFoundError"
    assert exc_info.value.message == "Channel not found: missing"
