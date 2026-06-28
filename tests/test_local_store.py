import sqlite3

import pytest

from sssn import (
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    Event,
    EventNotFoundError,
    InvalidPayloadError,
    LocalStore,
    Snapshot,
    SnapshotNotFoundError,
    SubscriptionExistsError,
    SubscriptionNotFoundError,
)


def test_store_initializes_deterministic_layout(tmp_path):
    store = LocalStore(tmp_path / "store")

    assert store.db_path == (tmp_path / "store" / "sssn.sqlite").resolve()
    assert store.artifacts_dir == (tmp_path / "store" / "artifacts").resolve()
    assert store.db_path.exists()
    assert store.artifacts_dir.is_dir()


def test_store_reopens_persisted_resources(tmp_path):
    root = tmp_path / "store"
    store = LocalStore(root)
    channel = store.create_channel({"name": "events", "schema": "demo.schemas:Event"})
    event = store.append_event({"channel": "events", "payload": {"status": "ok"}})
    subscription = store.create_subscription(
        "events",
        subscription_id="worker",
        consumer="analyzer",
    )
    artifact = store.write_artifact(
        b"payload",
        channel="events",
        media_type="text/plain",
        event_ids=(event.id,),
    )
    snapshot = store.put_snapshot(
        {"name": "latest", "channel": "events", "value": {"status": "ok"}}
    )

    reopened = LocalStore(root)

    assert reopened.list_channels() == (channel,)
    assert reopened.get_event(event.id) == event
    assert reopened.get_subscription(subscription.id) == subscription
    assert reopened.get_artifact(artifact.id) == artifact
    assert reopened.read_artifact(artifact.id) == b"payload"
    assert reopened.get_snapshot(snapshot.name) == snapshot


def test_channel_create_list_get_and_errors(tmp_path):
    store = LocalStore(tmp_path / "store")
    channel = store.create_channel(
        Channel(name="events", schema="demo.schemas:Event", form="log")
    )

    assert channel.name == "events"
    assert store.get_channel("events").schema == "demo.schemas:Event"
    assert store.list_channels() == (channel,)
    with pytest.raises(ChannelExistsError):
        store.create_channel({"name": "events"})
    with pytest.raises(ChannelNotFoundError):
        store.get_channel("missing")


def test_event_append_and_query_with_metadata(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "events", "schema": "demo.schemas:Event"})
    parent = store.append_event(
        Event(
            channel="events",
            source="test",
            kind="raw",
            payload={"value": 1},
            schema="demo.schemas:Event",
            metadata={"a": "b"},
            correlation_id="corr-1",
        )
    )
    child = store.append_event(
        {
            "channel": "events",
            "source": "test",
            "kind": "analysis",
            "payload": {"value": 2},
            "parent_ids": [parent.id],
        }
    )

    events = store.query_events("events")
    raw = store.query_events("events", kind="raw")
    after_parent = store.query_events("events", after_cursor=parent.cursor or 0)

    assert [event.id for event in events] == [parent.id, child.id]
    assert raw == (parent,)
    assert parent.cursor == 1
    assert child.cursor == 2
    assert store.get_event(parent.id) == parent
    assert [event.id for event in after_parent] == [child.id]
    assert child.parent_ids == (parent.id,)
    assert parent.metadata == {"a": "b"}
    with pytest.raises(ChannelNotFoundError):
        store.append_event({"channel": "missing", "payload": {}})
    with pytest.raises(EventNotFoundError):
        store.append_event(
            {"channel": "events", "payload": {}, "parent_ids": ["missing"]}
        )
    with pytest.raises(InvalidPayloadError, match="Invalid event"):
        store.append_event({"payload": {}})
    with pytest.raises(EventNotFoundError):
        store.get_event("missing")


def test_query_events_validates_cursor_and_limit(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "events"})
    store.append_event({"channel": "events", "payload": {"n": 1}})

    with pytest.raises(InvalidPayloadError, match="after_cursor"):
        store.query_events("events", after_cursor=-1)
    with pytest.raises(InvalidPayloadError, match="limit"):
        store.query_events("events", limit=0)


def test_subscription_pull_advances_cursor(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "events"})
    first = store.append_event({"channel": "events", "payload": {"n": 1}})
    second = store.append_event({"channel": "events", "payload": {"n": 2}})
    sub = store.create_subscription(
        "events",
        subscription_id="worker-events",
        consumer="worker",
        batch_size=1,
    )

    assert [event.id for event in store.pull_subscription(sub.id)] == [first.id]
    reused = store.create_subscription("events", subscription_id="worker-events")
    assert reused.id == sub.id
    assert reused.cursor == first.cursor
    store.create_channel({"name": "other-events"})
    with pytest.raises(SubscriptionExistsError):
        store.create_subscription("other-events", subscription_id="worker-events")
    assert [event.id for event in store.pull_subscription(sub.id)] == [second.id]
    assert store.get_subscription(sub.id).cursor == second.cursor
    assert store.pull_subscription(sub.id) == ()
    with pytest.raises(SubscriptionNotFoundError):
        store.pull_subscription("missing")


def test_subscription_pull_applies_kind_filter(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "events"})
    store.append_event({"channel": "events", "kind": "raw", "payload": {"n": 1}})
    analysis = store.append_event(
        {"channel": "events", "kind": "analysis", "payload": {"n": 2}}
    )
    store.append_event({"channel": "events", "kind": "raw", "payload": {"n": 3}})
    sub = store.create_subscription("events", filters={"kind": "analysis"})

    assert [event.id for event in store.pull_subscription(sub.id)] == [analysis.id]
    assert store.pull_subscription(sub.id) == ()
    with pytest.raises(InvalidPayloadError, match="kind"):
        store.create_subscription("events", filters={"kind": 123})
    with pytest.raises(InvalidPayloadError, match="unsupported"):
        store.create_subscription("events", filters={"source": "sensor"})


def test_subscription_validates_batch_size_and_pull_limit(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "events"})
    sub = store.create_subscription("events")

    with pytest.raises(InvalidPayloadError, match="batch_size"):
        store.create_subscription("events", batch_size=0)
    with pytest.raises(InvalidPayloadError, match="filters"):
        store.create_subscription("events", filters=[])
    with pytest.raises(InvalidPayloadError, match="limit"):
        store.pull_subscription(sub.id, limit=0)


def test_artifact_write_read_and_missing(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "artifacts", "form": "artifact-index"})
    event = store.append_event(
        {"channel": "artifacts", "payload": {"name": "greeting"}}
    )
    artifact = store.write_artifact(
        b"hello",
        channel="artifacts",
        media_type="text/plain",
        metadata={"name": "greeting"},
        event_ids=(event.id,),
    )

    assert artifact.size == 5
    assert artifact.sha256 is not None
    assert artifact.event_ids == (event.id,)
    assert store.get_artifact(artifact.id) == artifact
    assert store.read_artifact(artifact.id) == b"hello"
    with pytest.raises(ArtifactNotFoundError):
        store.read_artifact("missing")
    with pytest.raises(ArtifactNotFoundError):
        store.get_artifact("missing")
    with pytest.raises(EventNotFoundError):
        store.write_artifact(b"bad-link", event_ids=("missing",))


def test_artifact_read_rejects_payload_paths_outside_store(tmp_path):
    store = LocalStore(tmp_path / "store")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    with sqlite3.connect(store.db_path) as db:
        db.execute(
            """
            insert into artifacts(id, channel, path, media_type, size, sha256, metadata, event_ids)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "escaped",
                None,
                "../outside.txt",
                "text/plain",
                outside.stat().st_size,
                None,
                "{}",
                "[]",
            ),
        )

    with pytest.raises(ArtifactNotFoundError, match="outside artifact storage"):
        store.read_artifact("escaped")


def test_snapshot_put_get_and_missing(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "state", "form": "latest-state"})
    event = store.append_event({"channel": "state", "payload": {"status": "ok"}})
    snapshot = store.put_snapshot(
        Snapshot(
            name="latest",
            channel="state",
            value={"status": "ok"},
            source_event_id=event.id,
        )
    )

    assert store.get_snapshot("latest") == snapshot
    updated = store.put_snapshot({"name": "latest", "value": {"status": "new"}})
    assert store.get_snapshot("latest").value == updated.value
    with pytest.raises(EventNotFoundError):
        store.put_snapshot(
            {"name": "dangling", "value": {"status": "bad"}, "source_event_id": "missing"}
        )
    with pytest.raises(SnapshotNotFoundError):
        store.get_snapshot("missing")
