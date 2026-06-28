from sssn import Channel, Snapshot
from sssn.integrations import channel_resource, snapshot_resource
from sssn.server import endpoint


def test_channel_resource_exports_metadata_and_custom_endpoints():
    @endpoint.get("/channels/events/range", scope="channel", tags=("events",))
    def event_range(store, body=None):
        return []

    resource = channel_resource(
        Channel(
            name="events",
            schema="demo.schemas:Event",
            form="log",
            description="Event log.",
            metadata={"retention": "local"},
        ),
        custom_endpoints=[event_range],
    )

    assert resource == {
        "name": "events",
        "schema": "demo.schemas:Event",
        "form": "log",
        "description": "Event log.",
        "metadata": {"retention": "local"},
        "endpoints": [
            {
                "name": "event_range",
                "method": "GET",
                "path": "/channels/events/range",
                "scope": "channel",
                "description": "",
                "tags": ["events"],
            }
        ],
    }


def test_snapshot_resource_exports_metadata_and_custom_endpoints():
    @endpoint.get(
        "/snapshots/latest",
        scope="snapshot",
        description="Read the latest state.",
        tags=("snapshots",),
    )
    def latest_state(store):
        return store.get_snapshot("latest")

    resource = snapshot_resource(
        Snapshot(
            name="latest",
            channel="analysis",
            schema="demo.schemas:Analysis",
            value={"summary": "ok"},
            source_event_id="event-1",
            metadata={"retention": "latest"},
        ),
        description="Latest analysis state.",
        custom_endpoints=[latest_state],
    )

    assert resource == {
        "name": "latest",
        "schema": "demo.schemas:Analysis",
        "channel": "analysis",
        "description": "Latest analysis state.",
        "metadata": {"retention": "latest"},
        "endpoints": [
            {
                "name": "latest_state",
                "method": "GET",
                "path": "/snapshots/latest",
                "scope": "snapshot",
                "description": "Read the latest state.",
                "tags": ["snapshots"],
            }
        ],
    }
