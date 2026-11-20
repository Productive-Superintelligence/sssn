"""Regression tests for the store, client, and server fixes of SSSN 0.2.1.

Each section names the bug it covers. Tests that take ``any_store`` run on a
``LocalStore``, a ``RemoteStore``, and an ``AsyncRemoteStore``, since the
stores should behave alike.
"""

import asyncio
import inspect
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import sssn.stores.local as local_module
from sssn import AsyncRemoteStore, LocalStore, RemoteStore, create_app


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
