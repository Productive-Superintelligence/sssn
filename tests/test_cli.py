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
