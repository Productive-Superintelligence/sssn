"""Regression tests for the store, client, and server fixes of SSSN 0.2.1.

Each section names the bug it covers. Tests that take ``any_store`` run on a
``LocalStore``, a ``RemoteStore``, and an ``AsyncRemoteStore``, since the
stores should behave alike.
"""

import asyncio
import inspect
import pickle
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import sssn.stores.local as local_module
from sssn import (
    ArtifactNotFoundError,
    AsyncRemoteStore,
    ChannelExistsError,
    ChannelNotFoundError,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    LocalStore,
    NetworkError,
    RemoteStore,
    RemoteStoreError,
    SnapshotNotFoundError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
    create_app,
)

STORE_ERRORS = (
    ArtifactNotFoundError,
    ChannelExistsError,
    ChannelNotFoundError,
    EventExistsError,
    EventNotFoundError,
    InvalidPayloadError,
    SnapshotNotFoundError,
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
