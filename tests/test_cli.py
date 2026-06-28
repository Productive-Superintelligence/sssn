import json

from sssn.cli import main


def test_cli_create_list_and_append(tmp_path, capsys):
    store = tmp_path / "store"

    assert main(["--store", str(store), "create-channel", "events"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["name"] == "events"

    assert main(["--store", str(store), "channels"]) == 0
    listed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert listed[0]["name"] == "events"

    assert main(["--store", str(store), "append", "events", '{"n": 1}']) == 0
    event = json.loads(capsys.readouterr().out)
    assert event["channel"] == "events"
    assert event["payload"] == {"n": 1}

    assert (
        main(
            [
                "--store",
                str(store),
                "append",
                "events",
                '{"n": 2}',
                "--kind",
                "analysis",
            ]
        )
        == 0
    )
    analysis = json.loads(capsys.readouterr().out)

    assert main(["--store", str(store), "query-events", "events"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["id"] for item in events] == [event["id"], analysis["id"]]

    assert (
        main(
            [
                "--store",
                str(store),
                "query-events",
                "events",
                "--after-cursor",
                str(event["cursor"]),
                "--kind",
                "analysis",
                "--limit",
                "1",
            ]
        )
        == 0
    )
    filtered = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["id"] for item in filtered] == [analysis["id"]]

    assert main(["--store", str(store), "get-event", event["id"]]) == 0
    loaded = json.loads(capsys.readouterr().out)
    assert loaded["id"] == event["id"]
    assert loaded["payload"] == {"n": 1}

    assert (
        main(
            [
                "--store",
                str(store),
                "put-snapshot",
                "latest",
                '{"status": "ok"}',
                "--channel",
                "events",
                "--schema",
                "demo.schemas:State",
                "--source-event-id",
                event["id"],
                "--metadata",
                '{"role": "latest"}',
            ]
        )
        == 0
    )
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["name"] == "latest"
    assert snapshot["value"] == {"status": "ok"}
    assert snapshot["schema"] == "demo.schemas:State"
    assert snapshot["source_event_id"] == event["id"]
    assert snapshot["metadata"] == {"role": "latest"}

    assert main(["--store", str(store), "get-snapshot", "latest"]) == 0
    loaded_snapshot = json.loads(capsys.readouterr().out)
    assert loaded_snapshot["value"] == {"status": "ok"}

    assert (
        main(
            [
                "--store",
                str(store),
                "create-subscription",
                "events",
                "--id",
                "analysis-worker",
                "--consumer",
                "worker",
                "--batch-size",
                "10",
                "--kind",
                "analysis",
            ]
        )
        == 0
    )
    subscription = json.loads(capsys.readouterr().out)
    assert subscription["id"] == "analysis-worker"
    assert subscription["consumer"] == "worker"
    assert subscription["filters"] == {"kind": "analysis"}

    assert main(["--store", str(store), "pull-subscription", "analysis-worker"]) == 0
    pulled = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["id"] for item in pulled] == [analysis["id"]]

    assert main(["--store", str(store), "get-subscription", "analysis-worker"]) == 0
    loaded_subscription = json.loads(capsys.readouterr().out)
    assert loaded_subscription["cursor"] == analysis["cursor"]

    assert (
        main(
            [
                "--store",
                str(store),
                "create-subscription",
                "events",
                "--id",
                "analysis-worker",
            ]
        )
        == 0
    )
    reused_subscription = json.loads(capsys.readouterr().out)
    assert reused_subscription["cursor"] == analysis["cursor"]

    assert (
        main(
            [
                "--store",
                str(store),
                "append",
                "events",
                '{"n": 3}',
                "--kind",
                "analysis",
            ]
        )
        == 0
    )
    next_analysis = json.loads(capsys.readouterr().out)

    assert (
        main(
            [
                "--store",
                str(store),
                "pull-subscription",
                "analysis-worker",
                "--limit",
                "1",
            ]
        )
        == 0
    )
    pulled_again = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["id"] for item in pulled_again] == [next_analysis["id"]]
