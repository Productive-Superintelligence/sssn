from pathlib import Path

import pytest

from sssn import (
    AsyncSSSNClient,
    LocalStore,
    SSSNClient,
    SSSNRef,
    SSSNRefError,
    SSSNResolver,
)


CHANNEL_REF = "psi://demo/combo/channels/events"
SNAPSHOT_REF = "psi://demo/combo/snapshots/latest"
TACTIC_REF = "psi://demo/combo/tactics/analyze"
SERVICE_REF = "psi://demo/combo/services/api"


def test_resolver_loads_sssn_refs_from_shared_local_config(tmp_path):
    resolver = SSSNResolver.from_text(
        f"""
[refs."{CHANNEL_REF}"]
store = ".sssn"

[refs."{SNAPSHOT_REF}"]
store = ".sssn"
retention = "latest"

[refs."{TACTIC_REF}"]
url = "http://lllm/tactics/analyze"

[refs."{SERVICE_REF}"]
url = "http://sssn"

[stores.default]
path = ".sssn"
""".lstrip(),
        root=tmp_path,
    )

    assert resolver.refs() == (CHANNEL_REF, SNAPSHOT_REF)
    assert resolver.stores() == {"default": {"path": ".sssn"}}
    assert resolver.store("default") == {"path": ".sssn"}

    channel = resolver.resolve(CHANNEL_REF)
    snapshot = resolver.resolve(SNAPSHOT_REF)

    assert channel.resource_kind == "channels"
    assert channel.name == "events"
    assert channel.store == ".sssn"
    assert channel.metadata == {}
    assert snapshot.resource_kind == "snapshots"
    assert snapshot.name == "latest"
    assert snapshot.metadata == {"retention": "latest"}
    assert resolver.store_path(CHANNEL_REF) == (tmp_path / ".sssn").resolve()

    store = resolver.local_store(CHANNEL_REF)

    assert isinstance(store, LocalStore)
    assert store.root == (tmp_path / ".sssn").resolve()


def test_resolver_uses_config_file_parent_as_relative_root(tmp_path):
    config = tmp_path / "workspace" / ".psi" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f"""
[refs."{CHANNEL_REF}"]
store = "data/sssn"
""".lstrip(),
        encoding="utf-8",
    )

    resolver = SSSNResolver.from_config(config)

    assert resolver.store_path(CHANNEL_REF) == (
        tmp_path / "workspace" / "data" / "sssn"
    ).resolve()


def test_resolver_creates_clients_for_http_channel_refs():
    resolver = SSSNResolver()
    transport = object()
    resolver.bind(CHANNEL_REF, url="http://testserver/api")

    client = resolver.client(CHANNEL_REF, timeout=3.0, transport=transport)
    async_client = resolver.async_client(CHANNEL_REF, timeout=5.0, transport=transport)

    assert isinstance(client, SSSNClient)
    assert client.base_url == "http://testserver/api"
    assert client.timeout == 3.0
    assert client.transport is transport
    assert isinstance(async_client, AsyncSSSNClient)
    assert async_client.base_url == "http://testserver/api"
    assert async_client.timeout == 5.0
    assert async_client.transport is transport

    with pytest.raises(SSSNRefError, match="local store"):
        resolver.store_path(CHANNEL_REF)


def test_resolver_rejects_clients_for_store_only_refs(tmp_path):
    resolver = SSSNResolver(root=tmp_path)
    resolver.bind(CHANNEL_REF, store=".sssn")

    with pytest.raises(SSSNRefError, match="HTTP URL"):
        resolver.client(CHANNEL_REF)

    with pytest.raises(SSSNRefError, match="HTTP URL"):
        resolver.async_client(CHANNEL_REF)


def test_resolver_rejects_invalid_refs_and_ignores_other_layers(tmp_path):
    resolver = SSSNResolver.from_text(
        f"""
[refs."{TACTIC_REF}"]
url = "http://lllm/tactics/analyze"

[refs."{SERVICE_REF}"]
url = "http://sssn"
""".lstrip(),
        root=tmp_path,
    )

    assert resolver.refs() == ()

    for ref in (
        None,
        123,
        b"psi://demo/combo/channels/events",
        "",
        "   ",
    ):
        with pytest.raises(SSSNRefError, match="non-empty string"):
            SSSNRef.parse(ref)  # type: ignore[arg-type]
        with pytest.raises(SSSNRefError, match="non-empty string"):
            SSSNResolver().bind(ref, store=".sssn")  # type: ignore[arg-type]

    for ref in (
        "not-a-ref",
        "psi://demo/combo/widgets/events",
        "psi://demo/combo/channels/events?env=dev",
        "psi://demo/combo/channels//events",
        "psi://demo/../channels/events",
        "psi://demo/combo/channels/..",
        "psi://demo org/combo/channels/events",
        "psi://demo/combo pkg/channels/events",
        "psi://demo/combo/chan nels/events",
        "psi://demo/combo/channels/event name",
    ):
        with pytest.raises(SSSNRefError):
            SSSNResolver().bind(ref, store=".sssn")
        with pytest.raises(SSSNRefError):
            SSSNResolver().resolve(ref)


def test_resolver_requires_exactly_one_concrete_target(tmp_path):
    with pytest.raises(SSSNRefError, match="one concrete target"):
        SSSNResolver.from_text(
            f"""
[refs."{CHANNEL_REF}"]
""".lstrip(),
            root=tmp_path / "missing-target",
        )

    with pytest.raises(SSSNRefError, match="only one concrete target"):
        SSSNResolver.from_text(
            f"""
[refs."{CHANNEL_REF}"]
url = "http://sssn"
store = ".sssn"
""".lstrip(),
            root=tmp_path / "many-targets",
        )

    for index, target_line in enumerate(
        (
            "url = 123",
            'url = ""',
            'url = "   "',
            "store = false",
            'store = ""',
            'store = "   "',
            'path = ["x"]',
            'path = ""',
            'path = "   "',
        ),
        start=1,
    ):
        with pytest.raises(SSSNRefError, match="non-empty string"):
            SSSNResolver.from_text(
                f"""
[refs."{CHANNEL_REF}"]
{target_line}
""".lstrip(),
                root=tmp_path / f"bad-target-{index}",
            )


def test_resolver_returns_isolated_metadata_and_store_tables(tmp_path):
    resolver = SSSNResolver.from_text(
        f"""
[refs."{CHANNEL_REF}"]
store = ".sssn"

[refs."{CHANNEL_REF}".metadata]
owner = "demo"

[stores.default]
path = ".sssn"

[stores.default.metadata]
owner = "demo"
""".lstrip(),
        root=tmp_path,
    )

    binding = resolver.resolve(CHANNEL_REF)
    binding.metadata["metadata"]["owner"] = "changed"
    assert resolver.resolve(CHANNEL_REF).metadata == {"metadata": {"owner": "demo"}}

    stores = resolver.stores()
    stores["default"]["metadata"]["owner"] = "changed"
    assert resolver.stores() == {
        "default": {"path": ".sssn", "metadata": {"owner": "demo"}}
    }


def test_resolver_rejects_invalid_store_tables(tmp_path):
    with pytest.raises(SSSNRefError, match=r"\[stores\.default\]"):
        SSSNResolver.from_text(
            """
[stores]
default = ".sssn"
""".lstrip(),
            root=tmp_path / "bad-stores",
        )

    for index, text in enumerate(
        (
            """
[stores."bad/name"]
path = ".sssn"
""",
            """
[stores."bad store"]
path = ".sssn"
""",
            """
[stores.default]
path = 123
""",
            """
[stores.default]
path = ""
""",
        ),
        start=1,
    ):
        with pytest.raises(SSSNRefError):
            SSSNResolver.from_text(text.lstrip(), root=tmp_path / f"bad-store-{index}")


def test_path_value_rejects_malformed_config_paths():
    for value in ("", "   ", 123, b".psi/config.toml"):
        with pytest.raises(ValueError, match="config path|config root"):
            SSSNResolver.from_config(value)  # type: ignore[arg-type]
