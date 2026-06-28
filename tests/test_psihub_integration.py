from sssn import Channel
from sssn.integrations import channel_resource
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
