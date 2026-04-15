import httpx
import pytest

from sssn.channels.passthrough import PassthroughChannel
from sssn.core.channel import Visibility
from sssn.core.security import JWTChannelSecurity
from sssn.core.transport import HttpTransport
from sssn.infra.server import ChannelServer


SECRET = "transport-secret-that-is-long-enough-32b"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def jwt_http_stack():
    security = JWTChannelSecurity(secret=SECRET)
    channel = PassthroughChannel(
        id="secure-events",
        name="Secure Events",
        description="JWT-protected passthrough channel",
        visibility=Visibility.PUBLIC,
        security=security,
    )
    server = ChannelServer(host="127.0.0.1", port=0)
    channel.attach_transport(HttpTransport(server=server))
    await channel.start()

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield channel, security, client

    await channel.drain(timeout=0.01)


@pytest.mark.asyncio
async def test_http_transport_jwt_round_trip(jwt_http_stack):
    channel, security, client = jwt_http_stack

    write_token = await security.generate_token(
        "writer-1",
        "write",
        channel_ids=[channel.id],
    )
    response = await client.put(
        f"/channels/{channel.id}",
        headers=_auth_headers(write_token),
        json={"kind": "event", "value": 42},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["item_id"] != ""

    read_token = await security.generate_token(
        "reader-1",
        "read",
        channel_ids=[channel.id],
    )
    response = await client.get(
        f"/channels/{channel.id}",
        headers=_auth_headers(read_token),
        params={"limit": 10},
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["sender_id"] == "writer-1"
    assert messages[0]["content"]["data"] == {"kind": "event", "value": 42}


@pytest.mark.asyncio
async def test_http_transport_requires_bearer_token(jwt_http_stack):
    channel, _, client = jwt_http_stack

    response = await client.put(
        f"/channels/{channel.id}",
        json={"kind": "event"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Bearer token."


@pytest.mark.asyncio
async def test_http_transport_rejects_wrong_channel_scope(jwt_http_stack):
    channel, security, client = jwt_http_stack

    token = await security.generate_token(
        "writer-1",
        "write",
        channel_ids=["different-channel"],
    )
    response = await client.put(
        f"/channels/{channel.id}",
        headers=_auth_headers(token),
        json={"kind": "event"},
    )
    assert response.status_code == 403
    assert channel._store.messages == []


@pytest.mark.asyncio
async def test_http_transport_info_requires_authorized_reader(jwt_http_stack):
    channel, security, client = jwt_http_stack

    token = await security.generate_token(
        "reader-1",
        "read",
        channel_ids=[channel.id],
    )
    response = await client.get(
        f"/channels/{channel.id}/info",
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    info = response.json()
    assert info["id"] == channel.id
    assert info["name"] == channel.name
    assert info["visibility"] == Visibility.PUBLIC.value
