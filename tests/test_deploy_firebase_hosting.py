"""The Firebase Hosting deploy script translates firebase.json faithfully."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location(
        "deploy_firebase_hosting", ROOT / "scripts" / "deploy_firebase_hosting.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_firebase_json_deploys_the_built_docs_to_sssn_one():
    script = _script()
    hosting = json.loads((ROOT / "firebase.json").read_text())["hosting"]
    rc = json.loads((ROOT / ".firebaserc").read_text())

    # sssn.one is site sssn-one in project prosi-501105; the docs workflow
    # builds the site into site/, which the "docs" target publishes as is.
    assert rc["projects"] == {"default": "prosi-501105"}
    assert rc["targets"]["prosi-501105"]["hosting"] == {"docs": ["sssn-one"]}
    assert [(entry["target"], entry["public"]) for entry in hosting] == [("docs", "site")]
    config = script.serving_config(hosting[0])
    assert set(config) == {"redirects"}  # pages of the old docs move to new ones
    assert all(rule["statusCode"] == 301 for rule in config["redirects"])
    assert all(rule["location"].startswith("/") for rule in config["redirects"])


def _docs_page(url: str) -> Path:
    """The docs source of a site page such as ``/channels/``."""

    path = ROOT / "docs" / url.strip("/")
    return path / "index.md" if path.is_dir() else path.with_name(f"{path.name}.md")


def test_redirects_lead_from_a_page_that_is_gone_to_one_that_exists():
    (hosting,) = json.loads((ROOT / "firebase.json").read_text())["hosting"]

    for rule in hosting["redirects"]:
        source = rule["source"].split("{", 1)[0]  # "/old{,/**}" is /old and below
        assert not _docs_page(source).exists(), rule
        assert _docs_page(rule["destination"]).is_file(), rule


def test_serving_config_translates_rewrites_redirects_and_url_options():
    script = _script()
    entry = {
        "rewrites": [
            {"source": "/api/**", "run": {"serviceId": "api"}},
            {"source": "**", "destination": "/index.html"},
        ],
        "redirects": [{"source": "/old", "destination": "https://sssn.one/", "type": 302}],
        "cleanUrls": True,
        "trailingSlash": False,
    }

    assert script.serving_config(entry) == {
        "rewrites": [
            {"glob": "/api/**", "run": {"serviceId": "api", "region": "us-central1"}},
            {"glob": "**", "path": "/index.html"},
        ],
        "redirects": [{"glob": "/old", "location": "https://sssn.one/", "statusCode": 302}],
        "cleanUrls": True,
        "trailingSlashBehavior": "REMOVE",
    }
