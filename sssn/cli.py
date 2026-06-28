"""Small SSSN CLI."""

from __future__ import annotations

import argparse
import json

from . import Channel, Event, LocalStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sssn")
    parser.add_argument("--store", default=".sssn", help="Local store directory")
    subcommands = parser.add_subparsers(dest="command", required=True)

    channels = subcommands.add_parser("channels", help="List channels")

    create_channel = subcommands.add_parser("create-channel", help="Create a channel")
    create_channel.add_argument("name")
    create_channel.add_argument("--schema")
    create_channel.add_argument("--form", default="log")

    append = subcommands.add_parser("append", help="Append one JSON event")
    append.add_argument("channel")
    append.add_argument("payload")
    append.add_argument("--kind", default="event")
    append.add_argument("--source")

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
            Channel(name=args.name, schema=args.schema, form=args.form)
        )
        print(channel.model_dump_json(by_alias=True))
        return 0

    if args.command == "append":
        event = store.append_event(
            Event(
                channel=args.channel,
                kind=args.kind,
                source=args.source,
                payload=json.loads(args.payload),
            )
        )
        print(event.model_dump_json(by_alias=True))
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
