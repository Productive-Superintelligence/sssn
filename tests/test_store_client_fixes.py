"""Regression tests for store, client, and server bugs found in the docs rewrite.

Each section names the bug it covers. Tests that take ``any_store`` run on a
``LocalStore``, a ``RemoteStore``, and an ``AsyncRemoteStore``, since the
stores should behave alike.
"""

import asyncio
import base64
import hashlib
import inspect
import json
import math
import os
import pickle
import sqlite3
import sys
import threading
from collections import deque
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, field_serializer

from lllm import as_tactic

import sssn
import sssn.core as sssn_core
import sssn.stores.local as local_module
from sssn import (
    ArtifactNotFoundError,
    AsyncRemoteStore,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    ChannelResolver,
    Event,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    LocalStore,
    NetworkError,
    RemoteStore,
    RemoteStoreError,
    Snapshot,
    SnapshotNotFoundError,
    StoreBusyError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
    TacticProcessor,
    channel_resource,
    create_app,
    endpoint,
)

STORE_ERRORS = (
    ArtifactNotFoundError,
    ChannelExistsError,
    ChannelNotFoundError,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    SnapshotNotFoundError,
    StoreBusyError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)


def request(app, method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def sync_transport(app) -> httpx.MockTransport:
    """Route the synchronous RemoteStore into an in-process ASGI app."""

    test_client = TestClient(app)

    def handler(outgoing: httpx.Request) -> httpx.Response:
        response = test_client.request(
            outgoing.method,
            outgoing.url.raw_path.decode("ascii"),
            content=outgoing.content,
            headers={"content-type": outgoing.headers.get("content-type", "")},
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": response.headers.get("content-type", "")},
        )

    return httpx.MockTransport(handler)


class Blocking:
    """Call any store's methods synchronously, awaiting coroutine results."""

    def __init__(self, store):
        self._store = store

    def __getattr__(self, name):
        method = getattr(self._store, name)

        def call(*args, **kwargs):
            result = method(*args, **kwargs)
            return asyncio.run(result) if inspect.isawaitable(result) else result

        return call


def make_store(kind: str, root: Path) -> Blocking:
    store = LocalStore(root)
    if kind == "local":
        return Blocking(store)
    app = create_app(store)
    if kind == "remote":
        return Blocking(RemoteStore("http://testserver", transport=sync_transport(app)))
    return Blocking(
        AsyncRemoteStore("http://testserver", transport=httpx.ASGITransport(app=app))
    )


@pytest.fixture(params=["local", "remote", "async"])
def any_store(request, tmp_path):
    return make_store(request.param, tmp_path / "store")


@pytest.fixture(params=["remote", "async"])
def remote_store(request, tmp_path):
    return make_store(request.param, tmp_path / "store")


# 1: pull_subscription reads and moves the cursor in one transaction


def test_concurrent_pulls_of_one_subscription_get_different_events(
    tmp_path, monkeypatch
):
    root = tmp_path / "store"
    first, second = LocalStore(root), LocalStore(root)
    first.create_channel({"name": "jobs"})
    for n in range(6):
        first.append_event({"channel": "jobs", "payload": n})
    first.create_subscription("jobs", subscription_id="workers")

    # Each pull waits inside its read until the other pull reads too (or a
    # second passes), so the two pulls overlap as much as the store allows.
    barrier = threading.Barrier(2, timeout=1.0)
    read_event = local_module._event

    def overlapping_read(row):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return read_event(row)

    monkeypatch.setattr(local_module, "_event", overlapping_read)
    pulled = {}

    def pull(store):
        pulled[store] = store.pull_subscription("workers", limit=3)

    threads = [threading.Thread(target=pull, args=(store,)) for store in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    payloads = [event.payload for batch in pulled.values() for event in batch]
    assert sorted(payloads) == [0, 1, 2, 3, 4, 5]
    assert second.get_subscription("workers").cursor == 6


def test_many_workers_pulling_one_subscription_get_each_event_once(tmp_path):
    root = tmp_path / "store"
    LocalStore(root).create_channel({"name": "jobs"})
    for n in range(40):
        LocalStore(root).append_event({"channel": "jobs", "payload": n})
    LocalStore(root).create_subscription("jobs", subscription_id="workers")
    seen, errors = [], []

    def work():
        store = LocalStore(root)
        try:
            while batch := store.pull_subscription("workers", limit=2):
                seen.extend(event.payload for event in batch)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(seen) == list(range(40))


# 2: remote stores percent-encode the names in URL paths


@pytest.mark.parametrize("name", ["what?", "a#b", "café", "q&a=1+[x]"])
def test_remote_stores_reach_resources_named_with_url_characters(
    remote_store, name
):
    channel = remote_store.create_channel({"name": name})
    event = remote_store.append_event({"id": f"{name}-1", "channel": name})
    remote_store.create_subscription(name, subscription_id=f"{name}-sub")
    snapshot = remote_store.put_snapshot(f"{name}-snap", {"n": 1}, channel=name)

    assert remote_store.get_channel(name) == channel
    assert remote_store.get_event(f"{name}-1") == event
    assert remote_store.query_events(name) == (event,)
    assert remote_store.get_subscription(f"{name}-sub").channel == name
    assert remote_store.pull_subscription(f"{name}-sub") == (event,)
    assert remote_store.get_snapshot(f"{name}-snap") == snapshot


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_stores_percent_encode_each_path_segment(client_cls):
    paths = []

    def handler(outgoing: httpx.Request) -> httpx.Response:
        paths.append((outgoing.method, outgoing.url.raw_path.decode("ascii")))
        return httpx.Response(404, json={"detail": "Not Found"})

    transport = httpx.MockTransport(handler)
    store = Blocking(client_cls("http://testserver/base", transport=transport))
    name = "a?b#c"
    for method, arguments in [
        (store.get_channel, (name,)),
        (store.get_event, (name,)),
        (store.get_subscription, (name,)),
        (store.pull_subscription, (name,)),
        (store.get_artifact, (name,)),
        (store.read_artifact, (name,)),
        (store.get_snapshot, (name,)),
        (store.put_snapshot, (name, 1)),
    ]:
        with pytest.raises(RemoteStoreError):
            method(*arguments)

    assert paths == [
        ("GET", "/base/channels/a%3Fb%23c"),
        ("GET", "/base/events/a%3Fb%23c"),
        ("GET", "/base/subscriptions/a%3Fb%23c"),
        ("POST", "/base/subscriptions/a%3Fb%23c/pull"),
        ("GET", "/base/artifacts/a%3Fb%23c/metadata"),
        ("GET", "/base/artifacts/a%3Fb%23c"),
        ("GET", "/base/snapshots/a%3Fb%23c"),
        ("PUT", "/base/snapshots/a%3Fb%23c"),
    ]


# 3: remote stores send headers, such as a bearer token


def answer_with_no_channels(seen):
    def handler(outgoing: httpx.Request) -> httpx.Response:
        seen.append(outgoing.headers)
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_stores_send_the_headers_they_are_given(client_cls):
    seen = []
    headers = {"Authorization": "Bearer s3cret", "X-Team": "ops"}
    store = client_cls(
        "http://testserver",
        headers=headers,
        transport=answer_with_no_channels(seen),
    )
    headers["X-Team"] = "changed"  # the store keeps its own copy

    Blocking(store).list_channels()
    Blocking(store).query_events("events")

    assert store.headers == {"Authorization": "Bearer s3cret", "X-Team": "ops"}
    assert [(sent["authorization"], sent["x-team"]) for sent in seen] == [
        ("Bearer s3cret", "ops"),
        ("Bearer s3cret", "ops"),
    ]


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_stores_take_an_httpx_auth(client_cls):
    seen = []
    store = client_cls(
        "http://testserver",
        auth=httpx.BasicAuth("ada", "pw"),
        transport=answer_with_no_channels(seen),
    )

    Blocking(store).list_channels()

    assert seen[0]["authorization"] == "Basic " + base64.b64encode(b"ada:pw").decode()


def test_remote_store_reaches_a_store_behind_a_token_check(tmp_path):
    app = create_app(LocalStore(tmp_path / "store"))

    @app.middleware("http")
    async def require_token(request, call_next):
        if request.headers.get("authorization") != "Bearer s3cret":
            return JSONResponse({"detail": "Invalid token."}, status_code=401)
        return await call_next(request)

    transport = httpx.ASGITransport(app=app)
    token = {"Authorization": "Bearer s3cret"}
    allowed = Blocking(
        AsyncRemoteStore("http://testserver", headers=token, transport=transport)
    )
    anonymous = Blocking(AsyncRemoteStore("http://testserver", transport=transport))

    allowed.create_channel({"name": "events"})
    with pytest.raises(RemoteStoreError) as exc_info:
        anonymous.list_channels()

    assert [channel.name for channel in allowed.list_channels()] == ["events"]
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "Invalid token."


def test_channel_resolver_clients_take_headers_and_auth():
    resolver = ChannelResolver()
    ref = "lllm://demo/events/channels/raw"
    resolver.bind(ref, url="http://store.internal:7700")
    token = {"Authorization": "Bearer s3cret"}
    auth = httpx.BasicAuth("ada", "pw")

    client = resolver.client(ref, headers=token, auth=auth)
    async_client = resolver.async_client(ref, headers=token, auth=auth)

    for store in (client, async_client):
        assert store.headers == token
        assert store.auth is auth


# 4: remote stores raise the same error classes as LocalStore


def test_remote_store_error_is_a_network_error():
    assert issubclass(RemoteStoreError, NetworkError)


def test_every_store_raises_the_same_error_classes(any_store):
    any_store.create_channel({"name": "events"})
    any_store.create_channel({"name": "other"})
    any_store.append_event({"id": "e1", "channel": "events"})
    any_store.create_subscription("events", subscription_id="worker")
    orphan = {"channel": "events", "parent_ids": ["missing"]}
    calls = [
        (ChannelNotFoundError, any_store.get_channel, "missing"),
        (ChannelNotFoundError, any_store.query_events, "missing"),
        (ChannelExistsError, any_store.create_channel, {"name": "events"}),
        (EventExistsError, any_store.append_event, {"id": "e1", "channel": "events"}),
        (EventNotFoundError, any_store.get_event, "missing"),
        (EventNotFoundError, any_store.append_event, orphan),
        (SubscriptionNotFoundError, any_store.get_subscription, "missing"),
        (SubscriptionNotFoundError, any_store.pull_subscription, "missing"),
        (ArtifactNotFoundError, any_store.get_artifact, "missing"),
        (ArtifactNotFoundError, any_store.read_artifact, "missing"),
        (SnapshotNotFoundError, any_store.get_snapshot, "missing"),
        (InvalidPayloadError, any_store.create_channel, {"name": "x", "form": "?"}),
    ]
    for error, method, argument in calls:
        with pytest.raises(error):
            method(argument)
    with pytest.raises(SubscriptionExistsError):
        any_store.create_subscription("other", subscription_id="worker")
    with pytest.raises(InvalidPayloadError):
        any_store.query_events("events", limit=0)


def test_remote_store_errors_keep_the_remote_store_error_fields(remote_store):
    with pytest.raises(ChannelNotFoundError) as exc_info:
        remote_store.get_channel("missing")

    error = exc_info.value
    assert isinstance(error, RemoteStoreError)
    assert type(error).__name__ == "RemoteStoreError"
    assert error.status_code == 404
    assert error.error_type == "ChannelNotFoundError"
    assert error.message == "Channel not found: missing"
    assert str(error) == (
        "SSSN server returned HTTP 404 (ChannelNotFoundError): "
        "Channel not found: missing"
    )


def error_response(status_code, error_type, message="boom"):
    body = {"detail": {"error": {"type": error_type, "message": message}}}

    def handler(outgoing: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("error", STORE_ERRORS)
def test_remote_store_errors_are_instances_of_the_reported_store_error(error):
    transport = error_response(400, error.__name__)
    store = RemoteStore("http://testserver", transport=transport)

    with pytest.raises(error) as exc_info:
        store.get_channel("events")

    assert isinstance(exc_info.value, RemoteStoreError)
    assert exc_info.value.error_type == error.__name__
    others = [other for other in STORE_ERRORS if other is not error]
    assert not isinstance(exc_info.value, tuple(others))


def test_unknown_remote_error_types_raise_a_plain_remote_store_error():
    store = RemoteStore("http://testserver", transport=error_response(500, "KeyError"))

    with pytest.raises(RemoteStoreError) as exc_info:
        store.get_channel("events")

    assert type(exc_info.value) is RemoteStoreError
    assert not isinstance(exc_info.value, STORE_ERRORS)
    assert exc_info.value.error_type == "KeyError"


def test_remote_store_errors_survive_pickling():
    transport = error_response(404, "ChannelNotFoundError", "Channel not found: x")
    with pytest.raises(ChannelNotFoundError) as exc_info:
        RemoteStore("http://testserver", transport=transport).get_channel("x")
    error = exc_info.value

    copy = pickle.loads(pickle.dumps(error))

    assert isinstance(copy, ChannelNotFoundError)
    assert isinstance(copy, RemoteStoreError)
    assert str(copy) == str(error)
    assert (copy.status_code, copy.error_type, copy.message, copy.detail) == (
        error.status_code,
        error.error_type,
        error.message,
        error.detail,
    )


def test_store_server_passes_on_the_errors_of_a_remote_store_it_serves(tmp_path):
    backend = create_app(LocalStore(tmp_path / "backend"))
    remote = RemoteStore("http://backend", transport=sync_transport(backend))
    proxy = create_app(remote)
    request(proxy, "POST", "/channels", json={"name": "events"})

    missing = request(proxy, "GET", "/channels/missing")
    taken = request(proxy, "POST", "/channels", json={"name": "events"})

    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == {
        "type": "ChannelNotFoundError",
        "message": "Channel not found: missing",
    }
    assert taken.status_code == 409
    assert taken.json()["detail"]["error"] == {
        "type": "ChannelExistsError",
        "message": "Channel already exists: events",
    }


@pytest.mark.parametrize(
    ("response", "status_code"),
    [
        (httpx.Response(401, json={"detail": "Invalid token."}), 401),
        (httpx.Response(503, text="unavailable"), 500),
        (httpx.Response(200, text="not json"), 500),
    ],
)
def test_store_server_reports_other_remote_store_failures_as_before(
    response, status_code
):
    transport = httpx.MockTransport(lambda outgoing: response)
    proxy = create_app(RemoteStore("http://backend", transport=transport))

    answer = request(proxy, "GET", "/channels/events")

    assert answer.status_code == status_code
    assert answer.json()["detail"]["error"]["type"] == "RemoteStoreError"


# 5: RemoteStoreError.message comes from a plain FastAPI detail


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_error_message_comes_from_a_plain_detail(client_cls):
    def unauthorized(outgoing: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid token."})

    transport = httpx.MockTransport(unauthorized)
    store = Blocking(client_cls("http://testserver", transport=transport))

    with pytest.raises(RemoteStoreError) as exc_info:
        store.list_channels()

    assert exc_info.value.status_code == 401
    assert exc_info.value.error_type is None
    assert exc_info.value.message == "Invalid token."
    assert exc_info.value.detail == {"detail": "Invalid token."}
    assert str(exc_info.value) == "SSSN server returned HTTP 401: Invalid token."


def test_remote_store_error_reads_a_plain_detail_it_is_given():
    error = RemoteStoreError(403, detail={"detail": "Not allowed."})

    assert error.message == "Not allowed."


# 6: every store takes the same artifact data; text is stored as UTF-8


@pytest.mark.parametrize(
    ("data", "stored"),
    [
        (b"\xff\x00raw", b"\xff\x00raw"),
        (bytearray(b"\xff\x00raw"), b"\xff\x00raw"),
        (memoryview(b"\xff\x00raw"), b"\xff\x00raw"),
        ("caf\u00e9\n", "caf\u00e9\n".encode("utf-8")),
    ],
)
def test_write_artifact_takes_the_same_data_on_every_store(any_store, data, stored):
    artifact = any_store.write_artifact(data, media_type="text/plain")

    assert artifact.size == len(stored)
    assert artifact.sha256 == hashlib.sha256(stored).hexdigest()
    assert any_store.read_artifact(artifact.id) == stored


@pytest.mark.parametrize("data", [None, 123, ["x"], {"data": "x"}, "\ud800"])
def test_write_artifact_rejects_other_data_on_every_store(any_store, data):
    with pytest.raises(InvalidPayloadError, match="artifact data"):
        any_store.write_artifact(data)


def test_write_artifact_has_the_same_signature_on_every_store():
    signature = inspect.signature(LocalStore.write_artifact)

    assert inspect.signature(RemoteStore.write_artifact) == signature
    assert inspect.signature(AsyncRemoteStore.write_artifact) == signature


# 7: the store server runs blocking store calls off the event loop


def get_twice_at_once(app, path):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await asyncio.gather(client.get(path), client.get(path))

    return asyncio.run(run())


def test_store_server_serves_requests_while_a_store_call_blocks(tmp_path):
    # Each get_channel waits until another request is inside the store too,
    # which can happen only if a blocked call leaves the event loop free.
    meeting = threading.Barrier(2, timeout=2)

    class Rendezvous(LocalStore):
        def get_channel(self, name):
            meeting.wait()
            return super().get_channel(name)

    store = Rendezvous(tmp_path / "store")
    store.create_channel({"name": "events"})

    responses = get_twice_at_once(create_app(store), "/channels/events")

    assert [response.status_code for response in responses] == [200, 200]


def test_store_server_runs_sync_custom_endpoints_off_the_event_loop(tmp_path):
    meeting = threading.Barrier(2, timeout=2)

    @endpoint.get("/meet")
    def meet(store):
        meeting.wait()
        return {"met": True}

    app = create_app(LocalStore(tmp_path / "store"), custom_endpoints=[meet])

    responses = get_twice_at_once(app, "/meet")

    assert [response.json() for response in responses] == [{"met": True}] * 2


def test_store_server_serves_an_async_store(tmp_path):
    backend = LocalStore(tmp_path / "backend")
    async_store = AsyncRemoteStore(
        "http://backend", transport=httpx.ASGITransport(app=create_app(backend))
    )
    app = create_app(async_store)

    created = request(app, "POST", "/channels", json={"name": "events"})
    request(app, "POST", "/events", json={"channel": "events", "payload": 1})
    request(app, "POST", "/subscriptions", json={"channel": "events", "id": "w"})
    pulled = request(app, "POST", "/subscriptions/w/pull")
    artifact = request(app, "POST", "/artifacts", json={"data": "hi"}).json()
    data = request(app, "GET", f"/artifacts/{artifact['id']}")
    snapshot = request(app, "PUT", "/snapshots/latest", json={"value": 2})
    missing = request(app, "GET", "/channels/missing")

    assert created.json()["name"] == "events"
    assert [event["payload"] for event in pulled.json()] == [1]
    assert data.content == b"hi"
    assert snapshot.json()["value"] == 2
    assert missing.status_code == 404
    assert [channel.name for channel in backend.list_channels()] == ["events"]


# 8: create_app checks custom endpoints when it builds the app


def test_create_app_rejects_a_function_without_an_endpoint_decorator(tmp_path):
    def channel_tail(store, name: str):
        return []

    with pytest.raises(ValueError, match=r"channel_tail.*@endpoint\.get"):
        create_app(LocalStore(tmp_path / "store"), custom_endpoints=[channel_tail])
    with pytest.raises(ValueError, match=r"channel_tail.*@endpoint\.get"):
        channel_resource(Channel(name="events"), custom_endpoints=[channel_tail])


def test_create_app_rejects_handler_parameters_it_cannot_bind(tmp_path):
    @endpoint.get("/channels/{name}/tail")
    def channel_tail(store, name: str, limit: int):
        return []

    @endpoint.get("/things/{thing_id}")
    def positional(thing_id, /):
        return thing_id

    store = LocalStore(tmp_path / "store")
    with pytest.raises(ValueError, match=r"channel_tail.*'limit'.*name"):
        create_app(store, custom_endpoints=[channel_tail])
    with pytest.raises(ValueError, match=r"positional.*'thing_id'"):
        create_app(store, custom_endpoints=[positional])


def test_custom_endpoints_bind_every_parameter_they_can(tmp_path):
    @endpoint.post("/items/{item_id:int}/notes")
    def note(store, item_id, body=None, params=None, limit=5, *args, **kwargs):
        return {
            "item_id": item_id,
            "body": body,
            "params": params,
            "limit": limit,
            "args": list(args),
            "kwargs": kwargs,
        }

    app = create_app(LocalStore(tmp_path / "store"), custom_endpoints=[note])
    response = request(app, "POST", "/items/7/notes?x=1", json={"text": "hi"})

    assert response.status_code == 200
    assert response.json() == {
        "item_id": 7,
        "body": {"text": "hi"},
        "params": {"x": "1"},
        "limit": 5,
        "args": [],
        "kwargs": {},
    }


# 9: NaN and infinity raise InvalidPayloadError instead of becoming null

NON_FINITE = [math.nan, math.inf, -math.inf]


class Reading(BaseModel):
    sensor: str
    celsius: float


@pytest.mark.parametrize("number", NON_FINITE)
def test_non_finite_numbers_raise_invalid_payload_error_on_every_store(
    any_store, number
):
    any_store.create_channel({"name": "readings"})
    reading = Reading(sensor="boiler", celsius=number)
    events = [
        {"channel": "readings", "payload": {"celsius": number}},
        {"channel": "readings", "payload": [1, [number]]},
        {"channel": "readings", "payload": reading},
        Event(channel="readings", payload={"celsius": number}),
        {"channel": "readings", "metadata": {"celsius": number}},
        {"channel": "readings", "timestamp": number},
    ]
    for event in events:
        with pytest.raises(InvalidPayloadError):
            any_store.append_event(event)
    snapshots = [
        (("latest", {"celsius": number}), {}),
        (("latest", reading), {}),
        (("latest", 1), {"timestamp": number}),
        (({"name": "latest", "value": 1, "timestamp": number},), {}),
        (("latest", 1), {"metadata": {"celsius": number}}),
    ]
    for args, kwargs in snapshots:
        with pytest.raises(InvalidPayloadError):
            any_store.put_snapshot(*args, **kwargs)
    with pytest.raises(InvalidPayloadError):
        any_store.create_channel({"name": "other", "metadata": {"n": number}})
    with pytest.raises(InvalidPayloadError):
        any_store.create_subscription("readings", metadata={"n": number})
    with pytest.raises(InvalidPayloadError):
        any_store.write_artifact(b"raw", metadata={"n": number})

    assert any_store.query_events("readings") == ()
    with pytest.raises(SnapshotNotFoundError):
        any_store.get_snapshot("latest")
    assert [channel.name for channel in any_store.list_channels()] == ["readings"]




@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/events", '{"channel": "readings", "payload": {"c": NaN}}'),
        ("POST", "/events", '{"channel": "readings", "timestamp": Infinity}'),
        ("PUT", "/snapshots/latest", '{"value": [-Infinity]}'),
        ("PUT", "/snapshots/latest", '{"value": 1, "timestamp": NaN}'),
    ],
)
def test_store_server_rejects_non_finite_numbers_in_bodies(
    tmp_path, method, path, body
):
    # Python's json module, which the server parses bodies with, reads the
    # NaN and Infinity that some clients write.
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "readings"})
    app = create_app(store)

    response = request(
        app, method, path, content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["type"] == "InvalidPayloadError"
    assert store.query_events("readings") == ()


# 10: a SQLite lock timeout raises StoreBusyError, a NetworkError


@contextmanager
def locked(store, mode):
    """Hold a lock on the store's database from another connection."""

    holder = sqlite3.connect(store.db_path, isolation_level=None)
    holder.execute(f"begin {mode}")
    try:
        yield
    finally:
        holder.rollback()
        holder.close()


def busy_store(root) -> LocalStore:
    store = LocalStore(root)
    store.create_channel({"name": "events"})
    store._busy_timeout = 0.05  # SQLite waits 5 seconds by default
    return store


def test_store_busy_error_is_exported_like_other_network_errors():
    assert issubclass(StoreBusyError, NetworkError)
    assert sssn.StoreBusyError is sssn_core.StoreBusyError
    assert "StoreBusyError" in sssn.__all__
    assert "StoreBusyError" in sssn_core.__all__


def test_a_locked_store_raises_store_busy_error(tmp_path):
    store = busy_store(tmp_path / "store")
    store.create_subscription("events", subscription_id="worker")

    with locked(store, "immediate"):  # another writer holds the write lock
        with pytest.raises(StoreBusyError, match="busy") as exc_info:
            store.append_event({"channel": "events"})
        with pytest.raises(StoreBusyError):
            store.pull_subscription("worker")
        assert store.get_channel("events").name == "events"  # reads still work
    with locked(store, "exclusive"):  # another writer is committing
        with pytest.raises(StoreBusyError):
            store.get_channel("events")

    assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)
    assert store.append_event({"channel": "events"}).cursor == 1


def test_store_server_answers_503_for_a_locked_store(tmp_path):
    store = busy_store(tmp_path / "store")
    app = create_app(store)

    with locked(store, "exclusive"):
        responses = [
            request(app, "GET", "/channels"),
            request(app, "GET", "/channels/events"),
            request(app, "POST", "/events", json={"channel": "events"}),
        ]

    for response in responses:
        assert response.status_code == 503
        assert response.json()["detail"]["error"]["type"] == "StoreBusyError"


@pytest.mark.parametrize("kind", ["remote", "async"])
def test_remote_stores_raise_store_busy_error_for_a_locked_store(tmp_path, kind):
    store = busy_store(tmp_path / "store")
    app = create_app(store)
    if kind == "remote":
        client = RemoteStore("http://testserver", transport=sync_transport(app))
    else:
        transport = httpx.ASGITransport(app=app)
        client = AsyncRemoteStore("http://testserver", transport=transport)

    with locked(store, "exclusive"):
        with pytest.raises(StoreBusyError) as exc_info:
            Blocking(client).list_channels()

    assert exc_info.value.status_code == 503


# 11: create_subscription with a taken id and other settings raises


def billing_subscription(store):
    store.create_channel({"name": "orders"})
    store.create_channel({"name": "refunds"})
    store.create_subscription(
        "orders",
        subscription_id="billing",
        consumer="billing",
        batch_size=10,
        filters={"kind": "placed"},
        metadata={"team": "finance"},
    )
    store.append_event({"channel": "orders", "kind": "placed"})
    store.pull_subscription("billing")
    return store.get_subscription("billing")


def test_create_subscription_raises_for_other_events_than_it_delivers(any_store):
    billing_subscription(any_store)

    for channel, filters in [
        ("refunds", {"kind": "placed"}),
        ("orders", {"kind": "paid"}),
        ("orders", {}),
        ("orders", {"kind": None}),
    ]:
        with pytest.raises(SubscriptionExistsError, match="billing"):
            any_store.create_subscription(
                channel, subscription_id="billing", filters=filters
            )


def test_create_subscription_resumes_whatever_else_differs(any_store):
    existing = billing_subscription(any_store)

    # Leaving filters out keeps the subscription's filter, and batch_size,
    # consumer, and metadata are not compared: the subscription comes back
    # unchanged, cursor included, as in sssn 0.2.0.
    for kwargs in [
        {},
        {"filters": {"kind": "placed"}},
        {"batch_size": 50, "consumer": "other", "metadata": {"x": 1}},
    ]:
        again = any_store.create_subscription(
            "orders", subscription_id="billing", **kwargs
        )
        assert again == existing
    assert existing.cursor == 1


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_create_subscription_leaves_out_filters_it_was_not_given(client_cls):
    bodies = []

    def handler(outgoing: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(outgoing.content))
        return httpx.Response(200, json={"id": "w", "channel": "events"})

    store = Blocking(
        client_cls("http://testserver", transport=httpx.MockTransport(handler))
    )
    store.create_subscription("events", subscription_id="w")
    store.create_subscription("events", subscription_id="w", filters={})

    # A server that predates the omitted-filters rule reads a missing
    # filters as {}, so leaving it out works there too.
    assert "filters" not in bodies[0]
    assert bodies[1]["filters"] == {}


def test_create_subscription_treats_a_none_kind_as_no_filter(any_store):
    any_store.create_channel({"name": "orders"})
    created = any_store.create_subscription("orders", subscription_id="all")

    assert any_store.create_subscription(
        "orders", subscription_id="all", filters={"kind": None}
    ) == created


def test_concurrent_creates_of_one_subscription_both_get_it(tmp_path, monkeypatch):
    root = tmp_path / "store"
    first, second = LocalStore(root), LocalStore(root)
    first.create_channel({"name": "jobs"})

    # Each create waits inside its lookup until the other looks too (or a
    # second passes), so both look before either inserts if they can.
    barrier = threading.Barrier(2, timeout=1.0)
    find = local_module._find_subscription

    def overlapping_find(db, subscription_id):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return find(db, subscription_id)

    monkeypatch.setattr(local_module, "_find_subscription", overlapping_find)
    created, errors = [], []

    def create(store):
        try:
            created.append(store.create_subscription("jobs", subscription_id="w"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(store,)) for store in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(created) == 2 and created[0] == created[1]


# 12: remote stores without httpx name the client extra

CLIENT_EXTRA = r'pip install "sssn\[client\]"'


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_stores_without_httpx_name_the_client_extra(client_cls, monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)

    with pytest.raises(ImportError, match=CLIENT_EXTRA):
        client_cls("http://testserver")


@pytest.mark.parametrize("client_cls", [RemoteStore, AsyncRemoteStore])
def test_remote_store_calls_without_httpx_name_the_client_extra(
    client_cls, monkeypatch
):
    store = Blocking(client_cls("http://testserver"))
    monkeypatch.setitem(sys.modules, "httpx", None)

    with pytest.raises(ImportError, match=CLIENT_EXTRA):
        store.list_channels()


# 13: a write returns the record as stored, the same that readers get


class Order(BaseModel):
    id: str
    total: float


def test_append_event_returns_the_event_as_stored(any_store):
    any_store.create_channel({"name": "orders"})

    event = any_store.append_event(
        {
            "channel": "orders",
            "payload": {"z": Order(id="A-1", total=9.5), "a": {3}},
            "metadata": {"tags": ("new", "eu"), "day": date(2026, 11, 18)},
        }
    )

    assert event == any_store.get_event(event.id)
    assert event.payload == {"a": [3], "z": {"id": "A-1", "total": 9.5}}
    assert list(event.payload) == ["a", "z"]
    assert event.metadata == {"day": "2026-11-18", "tags": ["new", "eu"]}
    model_event = any_store.append_event(
        {"channel": "orders", "payload": Order(id="A-2", total=1.0)}
    )
    assert model_event.payload == {"id": "A-2", "total": 1.0}
    assert model_event == any_store.get_event(model_event.id)


def test_every_write_returns_the_record_as_stored(any_store):
    unsorted = {"z": (1,), "a": date(2026, 1, 1)}
    stored = {"a": "2026-01-01", "z": [1]}

    channel = any_store.create_channel({"name": "orders", "metadata": unsorted})
    subscription = any_store.create_subscription(
        "orders", subscription_id="billing", metadata=unsorted
    )
    artifact = any_store.write_artifact(b"raw", metadata=unsorted)
    snapshot = any_store.put_snapshot(
        "latest", {"z": Order(id="A-1", total=9.5)}, metadata=unsorted
    )

    assert channel == any_store.get_channel("orders")
    assert subscription == any_store.get_subscription("billing")
    assert artifact == any_store.get_artifact(artifact.id)
    assert snapshot == any_store.get_snapshot("latest")
    for record in (channel, subscription, artifact, snapshot):
        assert record.metadata == stored
        assert list(record.metadata) == ["a", "z"]
    assert snapshot.value == {"z": {"id": "A-1", "total": 9.5}}


# Review 1: artifact bytes are written atomically, and only once


def test_rewriting_stored_bytes_never_truncates_a_read(tmp_path):
    store = LocalStore(tmp_path / "store")
    payload = os.urandom(4 * 1024 * 1024)
    artifact = store.write_artifact(payload)
    stop = threading.Event()
    short_reads, errors = [], []

    def write():
        try:
            while not stop.is_set():
                store.write_artifact(payload)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    def read():
        try:
            for _ in range(30):
                data = store.read_artifact(artifact.id)
                if data != payload:
                    short_reads.append(len(data))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    writers = [threading.Thread(target=write) for _ in range(2)]
    readers = [threading.Thread(target=read) for _ in range(2)]
    for thread in writers + readers:
        thread.start()
    for thread in readers:
        thread.join()
    stop.set()
    for thread in writers:
        thread.join()

    assert errors == []
    assert short_reads == []


def test_write_artifact_replaces_a_damaged_file_in_one_step(tmp_path):
    store = LocalStore(tmp_path / "store")
    artifact = store.write_artifact(b"complete payload")
    payload_file = store.root / artifact.path
    payload_file.write_bytes(b"compl")  # a file cut short by an old crash

    store.write_artifact(b"complete payload")

    assert store.read_artifact(artifact.id) == b"complete payload"
    assert sorted(path.name for path in store.artifacts_dir.iterdir()) == [
        payload_file.name
    ]


# Review 3: json_value checks the JSON form, whatever holds the NaN


class NullWhenNaN(BaseModel):
    """A model whose JSON form writes NaN as null, on purpose."""

    reading: float

    @field_serializer("reading", when_used="json")
    def _null_for_nan(self, value):
        return None if math.isnan(value) else value


@pytest.mark.parametrize(
    "payload",
    [(1.0, math.nan), {math.nan}, deque([math.nan]), iter([1.0, math.nan])],
    ids=["tuple", "set", "deque", "iterator"],
)
def test_nan_in_any_container_raises_on_every_store(any_store, payload):
    any_store.create_channel({"name": "readings"})

    with pytest.raises(InvalidPayloadError, match="NaN"):
        any_store.append_event({"channel": "readings", "payload": payload})

    assert any_store.query_events("readings") == ()


def test_a_model_may_write_nan_as_null_on_every_store(any_store):
    any_store.create_channel({"name": "readings"})

    event = any_store.append_event(
        {"channel": "readings", "payload": NullWhenNaN(reading=math.nan)}
    )

    assert event.payload == {"reading": None}
    assert any_store.get_event(event.id).payload == {"reading": None}


def test_iterator_payloads_are_stored_whole_on_every_store(any_store):
    any_store.create_channel({"name": "readings"})

    event = any_store.append_event({"channel": "readings", "payload": iter([1, 2])})

    assert event.payload == [1, 2]


# Review 2: remote stores send a model's free-form fields in their JSON form


class Measurement(BaseModel):
    """A payload whose JSON form differs from its Python form."""

    model_config = ConfigDict(ser_json_bytes="base64", ser_json_timedelta="float")

    raw: bytes
    took: timedelta
    label: str

    @field_serializer("label", when_used="json")
    def _upper(self, value):
        return value.upper()


def test_payload_models_are_stored_in_their_json_form_on_every_store(any_store):
    measurement = Measurement(
        raw=b"\xff\x00", took=timedelta(seconds=1.5), label="ok"
    )
    stored = measurement.model_dump(mode="json")
    tagged = {"m": measurement}

    channel = any_store.create_channel(Channel(name="m", metadata=tagged))
    from_model = any_store.append_event(
        Event(channel="m", payload=measurement, metadata=tagged)
    )
    from_dict = any_store.append_event({"channel": "m", "payload": measurement})
    snapshot = any_store.put_snapshot(
        Snapshot(name="s", value=measurement, metadata=tagged)
    )
    named = any_store.put_snapshot("n", Snapshot(name="x", value=measurement))

    assert stored == {"raw": "_wA=", "took": 1.5, "label": "OK"}
    assert channel.metadata == {"m": stored}
    assert (from_model.payload, from_model.metadata) == (stored, {"m": stored})
    assert from_dict.payload == stored
    assert (snapshot.value, snapshot.metadata) == (stored, {"m": stored})
    assert named.value == stored


# Review 4: a processor output holding NaN fails like other unstorable output


@pytest.mark.parametrize(
    "output", [{"score": math.nan}, [1.0, math.nan]], ids=["dict", "list"]
)
def test_processor_outputs_holding_nan_are_failures(tmp_path, output):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "inbox"})
    store.create_channel({"name": "scores"})
    store.append_event({"channel": "inbox", "payload": {"text": "hi"}})

    def score(payload: dict) -> Any:
        return output

    raising = TacticProcessor(as_tactic(score), store, source="inbox", sink="scores")
    with pytest.raises(InvalidPayloadError, match="NaN"):
        raising.process()
    # Not acknowledged, and nothing written as null.
    assert store.get_subscription(raising.consumer).cursor == 0
    assert store.query_events("scores") == ()

    recording = TacticProcessor(
        as_tactic(score), store, source="inbox", sink="scores", errors="record"
    )
    [error] = recording.process()
    assert (error.kind, error.payload["type"]) == ("error", "InvalidPayloadError")
    assert store.query_events("scores") == (error,)


# Review 5: timestamps must be finite to be written, not to be read


def test_rows_with_an_infinite_timestamp_stay_readable(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "legacy"})
    first = store.append_event({"channel": "legacy", "payload": 1})
    store.append_event({"channel": "legacy", "payload": 2})
    store.put_snapshot("latest", 1)
    store.create_subscription("legacy", subscription_id="reader")
    # sssn 0.2.0 stored infinite timestamps, and SQLite keeps them.
    db = sqlite3.connect(store.db_path)
    with db:
        db.execute("update events set timestamp = 9e999 where id = ?", (first.id,))
        db.execute("update snapshots set timestamp = -9e999")
    db.close()

    assert store.get_event(first.id).timestamp == math.inf
    assert [event.payload for event in store.query_events("legacy")] == [1, 2]
    assert [event.payload for event in store.pull_subscription("reader")] == [1, 2]
    assert store.get_subscription("reader").cursor == 2
    assert store.get_snapshot("latest").timestamp == -math.inf
    assert Event(channel="legacy", timestamp=math.inf).timestamp == math.inf
