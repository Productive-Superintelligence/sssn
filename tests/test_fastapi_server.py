import asyncio

import httpx

from sssn import LocalStore
from sssn.server import create_app


def request(app, method, path, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_fastapi_channel_event_subscription_flow(tmp_path):
    app = create_app(LocalStore(tmp_path / "store"))

    health = request(app, "GET", "/health")
    created = request(
        app,
        "POST",
        "/channels",
        json={"name": "events", "schema": "demo.schemas:Event", "form": "log"},
    )
    duplicate = request(app, "POST", "/channels", json={"name": "events"})
    listed = request(app, "GET", "/channels")
    event = request(
        app,
        "POST",
        "/events",
        json={"channel": "events", "kind": "raw", "payload": {"n": 1}},
    )
    queried = request(app, "GET", "/events", params={"channel": "events"})
    sub = request(app, "POST", "/subscriptions", json={"channel": "events"})
    pulled = request(
        app,
        "POST",
        f"/subscriptions/{sub.json()['id']}/pull",
    )
    pulled_again = request(
        app,
        "POST",
        f"/subscriptions/{sub.json()['id']}/pull",
    )

    assert health.json() == {"ok": True}
    assert created.status_code == 200
    assert created.json()["name"] == "events"
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"]["type"] == "ChannelExistsError"
    assert listed.json()[0]["name"] == "events"
    assert event.json()["payload"] == {"n": 1}
    assert queried.json()[0]["id"] == event.json()["id"]
    assert [item["id"] for item in pulled.json()] == [event.json()["id"]]
    assert pulled_again.json() == []


def test_fastapi_artifact_and_snapshot_flow(tmp_path):
    app = create_app(LocalStore(tmp_path / "store"))
    request(app, "POST", "/channels", json={"name": "state", "form": "latest-state"})

    artifact = request(
        app,
        "POST",
        "/artifacts",
        json={
            "data": "hello",
            "encoding": "text",
            "channel": "state",
            "media_type": "text/plain",
        },
    )
    artifact_data = request(app, "GET", f"/artifacts/{artifact.json()['id']}")
    missing_artifact = request(app, "GET", "/artifacts/missing")

    snapshot = request(
        app,
        "PUT",
        "/snapshots/latest",
        json={"channel": "state", "value": {"status": "ok"}},
    )
    loaded = request(app, "GET", "/snapshots/latest")
    missing_snapshot = request(app, "GET", "/snapshots/missing")

    assert artifact.status_code == 200
    assert artifact_data.content == b"hello"
    assert artifact_data.headers["content-type"] == "application/octet-stream"
    assert missing_artifact.status_code == 404
    assert snapshot.json()["name"] == "latest"
    assert loaded.json()["value"] == {"status": "ok"}
    assert missing_snapshot.status_code == 404
