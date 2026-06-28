from typing import Any

from sssn import Channel, channel_resource, endpoint


@endpoint.get(
    "/channels/{name}/tail",
    scope="channel",
    description="Return the most recent events for a channel.",
    tags=("channels",),
)
def channel_tail(store, name: str, limit: int = 20):
    return store.query_events(name, limit=limit)


RAW_CHANNEL = Channel(
    name="raw",
    schema="raw_event",
    form="log",
    description="Incoming events from producers.",
    metadata={"retention": "local"},
)
ANALYSIS_CHANNEL = Channel(
    name="analysis",
    schema="analysis_event",
    form="log",
    description="Derived analysis events.",
    metadata={"derived_from": "raw"},
)


def build_channel_resources() -> dict[str, dict[str, Any]]:
    resources = [
        channel_resource(RAW_CHANNEL, custom_endpoints=[channel_tail]),
        channel_resource(ANALYSIS_CHANNEL),
    ]
    return {
        resource["name"]: {
            key: value
            for key, value in resource.items()
            if key != "name" and value not in (None, "", {}, [])
        }
        for resource in resources
    }


def build_manifest() -> dict[str, Any]:
    return {
        "package": {
            "psi_version": "0.1",
            "org": "demo",
            "name": "semantic-events",
            "version": "0.1.0",
            "kind": "channel",
            "primary": "channels.raw",
            "description": "SSSN channel package for raw and analysis events.",
        },
        "schemas": {
            "raw_event": {"entry": "demo.schemas:RawEvent"},
            "analysis_event": {"entry": "demo.schemas:AnalysisEvent"},
        },
        "channels": build_channel_resources(),
        "runs": {
            "local": {
                "channels": ["raw", "analysis"],
                "description": "Create both channels in a local store.",
            }
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(build_manifest(), indent=2))
