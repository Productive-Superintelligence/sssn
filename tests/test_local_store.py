import pytest

from sssn import (
    ArtifactNotFoundError,
    Channel,
    ChannelExistsError,
    ChannelNotFoundError,
    Event,
    InvalidPayloadError,
    LocalStore,
    Snapshot,
    SnapshotNotFoundError,
    SubscriptionNotFoundError,
)


def test_store_initializes_deterministic_layout(tmp_path):
    store = LocalStore(tmp_path / "store")

    assert store.db_path == (tmp_path / "store" / "sssn.sqlite").resolve()
    assert store.artifacts_dir == (tmp_path / "store" / "artifacts").resolve()
    assert store.db_path.exists()
    assert store.artifacts_dir.is_dir()


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

    assert [event.id for event in events] == [parent.id, child.id]
    assert raw == (parent,)
    assert child.parent_ids == (parent.id,)
    assert parent.metadata == {"a": "b"}
    with pytest.raises(ChannelNotFoundError):
        store.append_event({"channel": "missing", "payload": {}})
    with pytest.raises(InvalidPayloadError, match="Invalid event"):
        store.append_event({"payload": {}})


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
    sub = store.create_subscription("events", consumer="worker", batch_size=1)

    assert [event.id for event in store.pull_subscription(sub.id)] == [first.id]
    assert [event.id for event in store.pull_subscription(sub.id)] == [second.id]
    assert store.pull_subscription(sub.id) == ()
    with pytest.raises(SubscriptionNotFoundError):
        store.pull_subscription("missing")


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
    artifact = store.write_artifact(
        b"hello",
        channel="artifacts",
        media_type="text/plain",
        metadata={"name": "greeting"},
    )

    assert artifact.size == 5
    assert artifact.sha256 is not None
    assert store.read_artifact(artifact.id) == b"hello"
    with pytest.raises(ArtifactNotFoundError):
        store.read_artifact("missing")


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
    with pytest.raises(SnapshotNotFoundError):
        store.get_snapshot("missing")
