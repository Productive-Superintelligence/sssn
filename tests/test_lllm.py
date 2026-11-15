"""SSSN plugs into LLLM: hub channel forms, `lllm network`, and the old paths."""

import importlib.util
import os
import shutil
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

import lllm.cli
from lllm.hub import ChannelResource, PackageManifest
from lllm.hub.models import CHANNEL_FORM_VALUES

import sssn.cli
from sssn import ChannelForm, LocalStore, create_app


def test_hub_channel_forms_match_sssn_channel_forms():
    # lllm.hub keeps its own copy of the forms so it never imports sssn.
    assert CHANNEL_FORM_VALUES == frozenset(get_args(ChannelForm))
    for form in get_args(ChannelForm):
        assert ChannelResource(form=form).form == form


@pytest.mark.parametrize("form", ["stream", "Log", "logs"])
def test_hub_rejects_channel_forms_sssn_cannot_create(form):
    with pytest.raises(ValidationError, match="channel.form must be one of"):
        ChannelResource(form=form)
    with pytest.raises(ValidationError, match="channel.form must be one of"):
        PackageManifest.model_validate(
            {"package": {"name": "demo"}, "channels": {"events": {"form": form}}}
        )


def test_sssn_registers_the_lllm_network_command():
    points = [point for point in entry_points(group="lllm.commands") if point.name == "network"]

    assert [point.value for point in points] == ["sssn.cli"]
    assert points[0].load() is sssn.cli


def test_lllm_network_runs_the_sssn_cli(tmp_path, capsys):
    store = tmp_path / "store"

    assert lllm.cli.main(["network", "--store", str(store), "create-channel", "inbox"]) == 0
    assert lllm.cli.main(["network", "--store", str(store), "channels"]) == 0

    assert '"name":"inbox"' in capsys.readouterr().out
    assert [channel.name for channel in LocalStore(store).list_channels()] == ["inbox"]


@pytest.mark.parametrize(
    ("argv", "usage"),
    [
        (["/venv/bin/sssn", "--help"], "usage: sssn [-h] [--store STORE]"),
        (["/venv/bin/lllm", "network", "--help"], "usage: lllm network [-h] [--store STORE]"),
    ],
)
def test_help_names_the_command_that_ran(monkeypatch, capsys, argv, usage):
    monkeypatch.setattr(sys, "argv", argv)
    command = sssn.cli.main if Path(argv[0]).name == "sssn" else lllm.cli.main

    with pytest.raises(SystemExit) as exc:
        command(argv[1:])

    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith(usage)


@pytest.mark.parametrize("command", [["sssn", "--help"], ["lllm", "network", "--help"]])
def test_console_scripts_show_help(command):
    script = shutil.which(command[0], path=os.path.dirname(sys.executable))
    if script is None:
        pytest.skip(f"the {command[0]} console script is not installed next to {sys.executable}")

    result = subprocess.run(
        [script, *command[1:]], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"usage: {' '.join(command[:-1])} ")


def test_the_deprecated_lllm_network_path_reaches_sssn():
    # LLLM 0.4 keeps lllm.network as an alias of sssn for code written
    # against LLLM 0.3; it relies on sssn keeping that module layout.
    if importlib.util.find_spec("lllm.network") is None:
        pytest.skip("this lllm has no lllm.network alias")
    code = (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    import lllm.network\n"
        "import sssn\n"
        "from lllm.network.server.fastapi import create_app\n"
        "assert lllm.network.LocalStore is sssn.LocalStore\n"
        "assert lllm.network.TacticProcessor is sssn.TacticProcessor\n"
        "assert create_app is sssn.server.fastapi.create_app\n"
        "print(caught[0].category.__name__, caught[0].message)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("DeprecationWarning")
    assert "import sssn" in result.stdout


def test_the_store_app_keeps_the_store_where_lllm_network_kept_it(tmp_path):
    # Code written against LLLM 0.3's lllm.network reads the store from
    # app.state.network_store; sssn's own name for it is app.state.sssn_store.
    store = LocalStore(tmp_path / "store")
    app = create_app(store)

    assert app.state.sssn_store is store
    assert app.state.network_store is store
