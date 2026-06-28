import asyncio

import httpx

from sssn import LocalStore
from sssn.server import create_app, endpoint


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
    loaded_event = request(app, "GET", f"/events/{event.json()['id']}")
    missing_event = request(app, "GET", "/events/missing")
    sub = request(app, "POST", "/subscriptions", json={"channel": "events"})
    request(app, "POST", "/channels", json={"name": "other-events"})
    conflicting_sub = request(
        app,
        "POST",
        "/subscriptions",
        json={"id": sub.json()["id"], "channel": "other-events"},
    )
    pulled = request(
        app,
        "POST",
        f"/subscriptions/{sub.json()['id']}/pull",
    )
    loaded_sub = request(app, "GET", f"/subscriptions/{sub.json()['id']}")
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
    assert loaded_event.json()["id"] == event.json()["id"]
    assert missing_event.status_code == 404
    assert missing_event.json()["detail"]["error"]["type"] == "EventNotFoundError"
    assert conflicting_sub.status_code == 409
    assert conflicting_sub.json()["detail"]["error"]["type"] == "SubscriptionExistsError"
    assert [item["id"] for item in pulled.json()] == [event.json()["id"]]
    assert loaded_sub.json()["cursor"] == event.json()["cursor"]
    assert pulled_again.json() == []


def test_fastapi_returns_stable_errors_for_cursor_edges(tmp_path):
    app = create_app(LocalStore(tmp_path / "store"))
    request(app, "POST", "/channels", json={"name": "events"})
    sub = request(app, "POST", "/subscriptions", json={"channel": "events"})

    bad_cursor = request(
        app,
        "GET",
        "/events",
        params={"channel": "events", "after_cursor": -1},
    )
    bad_limit = request(
        app,
        "POST",
        f"/subscriptions/{sub.json()['id']}/pull",
        params={"limit": 0},
    )
    bad_batch = request(
        app,
        "POST",
        "/subscriptions",
        json={"channel": "events", "batch_size": 0},
    )
    missing_channel = request(app, "GET", "/channels/missing")

    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["detail"]["error"]["type"] == "InvalidPayloadError"
    assert "after_cursor" in bad_cursor.json()["detail"]["error"]["message"]
    assert bad_limit.status_code == 400
    assert bad_limit.json()["detail"]["error"]["type"] == "InvalidPayloadError"
    assert bad_batch.status_code == 400
    assert bad_batch.json()["detail"]["error"]["type"] == "InvalidPayloadError"
    assert missing_channel.status_code == 404
    assert missing_channel.json()["detail"]["error"]["type"] == "ChannelNotFoundError"


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
    dangling_artifact = request(
        app,
        "POST",
        "/artifacts",
        json={
            "data": "hello",
            "encoding": "text",
            "event_ids": ["missing-event"],
        },
    )
    invalid_base64 = request(
        app,
        "POST",
        "/artifacts",
        json={
            "data": "not base64!",
            "encoding": "base64",
            "channel": "state",
        },
    )
    artifact_data = request(app, "GET", f"/artifacts/{artifact.json()['id']}")
    artifact_metadata = request(
        app,
        "GET",
        f"/artifacts/{artifact.json()['id']}/metadata",
    )
    missing_artifact = request(app, "GET", "/artifacts/missing")
    missing_artifact_metadata = request(app, "GET", "/artifacts/missing/metadata")

    snapshot = request(
        app,
        "PUT",
        "/snapshots/latest",
        json={"channel": "state", "value": {"status": "ok"}},
    )
    dangling_snapshot = request(
        app,
        "PUT",
        "/snapshots/dangling",
        json={"value": {"status": "bad"}, "source_event_id": "missing-event"},
    )
    loaded = request(app, "GET", "/snapshots/latest")
    missing_snapshot = request(app, "GET", "/snapshots/missing")

    assert artifact.status_code == 200
    assert dangling_artifact.status_code == 404
    assert dangling_artifact.json()["detail"]["error"]["type"] == "EventNotFoundError"
    assert invalid_base64.status_code == 400
    assert invalid_base64.json()["detail"]["error"]["type"] == "InvalidPayloadError"
    assert artifact_data.content == b"hello"
    assert artifact_data.headers["content-type"].startswith("text/plain")
    assert artifact_metadata.json()["media_type"] == "text/plain"
    assert artifact_metadata.json()["size"] == 5
    assert missing_artifact.status_code == 404
    assert missing_artifact_metadata.status_code == 404
    assert snapshot.json()["name"] == "latest"
    assert dangling_snapshot.status_code == 404
    assert dangling_snapshot.json()["detail"]["error"]["type"] == "EventNotFoundError"
    assert loaded.json()["value"] == {"status": "ok"}
    assert missing_snapshot.status_code == 404


def test_fastapi_mounts_custom_channel_endpoint(tmp_path):
    @endpoint.get("/channels/{name}/count")
    def count_events(store: LocalStore, name: str):
        return {"count": len(store.query_events(name))}

    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "events"})
    store.append_event({"channel": "events", "payload": {"n": 1}})
    app = create_app(store, custom_endpoints=[count_events])

    response = request(app, "GET", "/channels/events/count")

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_fastapi_openapi_includes_portable_and_custom_routes(tmp_path):
    @endpoint.get("/channels/{name}/count")
    def count_events(store: LocalStore, name: str):
        return {"count": len(store.query_events(name))}

    app = create_app(LocalStore(tmp_path / "store"), custom_endpoints=[count_events])
    schema = app.openapi()

    for path in (
        "/health",
        "/channels",
        "/channels/{name}",
        "/events",
        "/subscriptions",
        "/subscriptions/{subscription_id}",
        "/subscriptions/{subscription_id}/pull",
        "/artifacts",
        "/artifacts/{artifact_id}",
        "/artifacts/{artifact_id}/metadata",
        "/events/{event_id}",
        "/snapshots/{name}",
        "/channels/{name}/count",
    ):
        assert path in schema["paths"]
    assert schema["paths"]["/channels/{name}/count"]["get"]["summary"] == "Count Events"
