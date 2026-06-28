"""Small SSSN CLI."""

from __future__ import annotations

import argparse
import base64
import binascii
import json

from . import Channel, Event, LocalStore


def _json_object(raw: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return value


def _artifact_data(raw: str, encoding: str) -> bytes:
    if encoding == "base64":
        try:
            return base64.b64decode(raw.encode("ascii"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise argparse.ArgumentTypeError("invalid base64 data") from exc
    return raw.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sssn")
    parser.add_argument("--store", default=".sssn", help="Local store directory")
    subcommands = parser.add_subparsers(dest="command", required=True)

    channels = subcommands.add_parser("channels", help="List channels")

    create_channel = subcommands.add_parser("create-channel", help="Create a channel")
    create_channel.add_argument("name")
    create_channel.add_argument("--schema")
    create_channel.add_argument("--form", default="log")
    create_channel.add_argument("--description", default="")
    create_channel.add_argument("--metadata", type=_json_object)

    get_channel = subcommands.add_parser("get-channel", help="Read one channel")
    get_channel.add_argument("name")

    append = subcommands.add_parser("append", help="Append one JSON event")
    append.add_argument("channel")
    append.add_argument("payload")
    append.add_argument("--kind", default="event")
    append.add_argument("--source")
    append.add_argument("--schema")
    append.add_argument("--timestamp", type=float)
    append.add_argument("--metadata", type=_json_object)
    append.add_argument("--correlation-id")
    append.add_argument("--parent-id", dest="parent_ids", action="append")

    query_events = subcommands.add_parser("query-events", help="Query channel events")
    query_events.add_argument("channel")
    query_events.add_argument("--after-cursor", type=int, default=0)
    query_events.add_argument("--limit", type=int, default=100)
    query_events.add_argument("--kind")

    get_event = subcommands.add_parser("get-event", help="Read one event by id")
    get_event.add_argument("id")

    create_subscription = subcommands.add_parser(
        "create-subscription",
        help="Create or reuse a channel subscription",
    )
    create_subscription.add_argument("channel")
    create_subscription.add_argument("--id")
    create_subscription.add_argument("--consumer")
    create_subscription.add_argument("--batch-size", type=int, default=100)
    create_subscription.add_argument("--kind")

    get_subscription = subcommands.add_parser(
        "get-subscription",
        help="Read subscription cursor state",
    )
    get_subscription.add_argument("id")

    pull_subscription = subcommands.add_parser(
        "pull-subscription",
        help="Pull events from a subscription",
    )
    pull_subscription.add_argument("id")
    pull_subscription.add_argument("--limit", type=int)

    write_artifact = subcommands.add_parser("write-artifact", help="Write an artifact")
    write_artifact.add_argument("data")
    write_artifact.add_argument("--encoding", choices=("text", "base64"), default="text")
    write_artifact.add_argument("--channel")
    write_artifact.add_argument("--media-type", default="application/octet-stream")
    write_artifact.add_argument("--metadata", type=_json_object)
    write_artifact.add_argument("--event-id", dest="event_ids", action="append")

    get_artifact = subcommands.add_parser(
        "get-artifact",
        help="Read artifact metadata",
    )
    get_artifact.add_argument("id")

    read_artifact = subcommands.add_parser(
        "read-artifact",
        help="Read artifact payload",
    )
    read_artifact.add_argument("id")
    read_artifact.add_argument(
        "--encoding",
        choices=("text", "base64"),
        default="text",
    )

    put_snapshot = subcommands.add_parser("put-snapshot", help="Write a snapshot")
    put_snapshot.add_argument("name")
    put_snapshot.add_argument("value")
    put_snapshot.add_argument("--channel")
    put_snapshot.add_argument("--schema")
    put_snapshot.add_argument("--source-event-id")
    put_snapshot.add_argument("--metadata", type=_json_object)

    get_snapshot = subcommands.add_parser("get-snapshot", help="Read one snapshot")
    get_snapshot.add_argument("name")

    serve = subcommands.add_parser("serve", help="Serve a local SSSN store")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7700)
    serve.add_argument("--log-level", default="info")

    args = parser.parse_args(argv)
    store = LocalStore(args.store)

    if args.command == "channels":
        for channel in store.list_channels():
            print(channel.model_dump_json(by_alias=True))
        return 0

    if args.command == "create-channel":
        channel = store.create_channel(
            Channel(
                name=args.name,
                schema=args.schema,
                form=args.form,
                description=args.description,
                metadata=args.metadata or {},
            )
        )
        print(channel.model_dump_json(by_alias=True))
        return 0

    if args.command == "get-channel":
        channel = store.get_channel(args.name)
        print(channel.model_dump_json(by_alias=True))
        return 0

    if args.command == "append":
        event_data = {
            "channel": args.channel,
            "kind": args.kind,
            "source": args.source,
            "payload": json.loads(args.payload),
            "schema": args.schema,
            "metadata": args.metadata or {},
            "correlation_id": args.correlation_id,
            "parent_ids": tuple(args.parent_ids or ()),
        }
        if args.timestamp is not None:
            event_data["timestamp"] = args.timestamp
        event = store.append_event(
            Event(**event_data)
        )
        print(event.model_dump_json(by_alias=True))
        return 0

    if args.command == "query-events":
        for event in store.query_events(
            args.channel,
            after_cursor=args.after_cursor,
            limit=args.limit,
            kind=args.kind,
        ):
            print(event.model_dump_json(by_alias=True))
        return 0

    if args.command == "get-event":
        event = store.get_event(args.id)
        print(event.model_dump_json(by_alias=True))
        return 0

    if args.command == "create-subscription":
        filters = {"kind": args.kind} if args.kind else None
        subscription = store.create_subscription(
            args.channel,
            subscription_id=args.id,
            consumer=args.consumer,
            batch_size=args.batch_size,
            filters=filters,
        )
        print(subscription.model_dump_json(by_alias=True))
        return 0

    if args.command == "get-subscription":
        subscription = store.get_subscription(args.id)
        print(subscription.model_dump_json(by_alias=True))
        return 0

    if args.command == "pull-subscription":
        for event in store.pull_subscription(args.id, limit=args.limit):
            print(event.model_dump_json(by_alias=True))
        return 0

    if args.command == "write-artifact":
        try:
            data = _artifact_data(args.data, args.encoding)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        artifact = store.write_artifact(
            data,
            channel=args.channel,
            media_type=args.media_type,
            metadata=args.metadata or {},
            event_ids=tuple(args.event_ids or ()),
        )
        print(artifact.model_dump_json(by_alias=True))
        return 0

    if args.command == "get-artifact":
        artifact = store.get_artifact(args.id)
        print(artifact.model_dump_json(by_alias=True))
        return 0

    if args.command == "read-artifact":
        data = store.read_artifact(args.id)
        if args.encoding == "base64":
            print(base64.b64encode(data).decode("ascii"))
        else:
            print(data.decode("utf-8"))
        return 0

    if args.command == "put-snapshot":
        snapshot = store.put_snapshot(
            {
                "name": args.name,
                "value": json.loads(args.value),
                "channel": args.channel,
                "schema": args.schema,
                "source_event_id": args.source_event_id,
                "metadata": args.metadata or {},
            }
        )
        print(snapshot.model_dump_json(by_alias=True))
        return 0

    if args.command == "get-snapshot":
        snapshot = store.get_snapshot(args.name)
        print(snapshot.model_dump_json(by_alias=True))
        return 0

    if args.command == "serve":
        import uvicorn

        from .server import create_app

        uvicorn.run(
            create_app(store),
            host=args.host,
            port=args.port,
            log_level=args.log_level,
        )
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
