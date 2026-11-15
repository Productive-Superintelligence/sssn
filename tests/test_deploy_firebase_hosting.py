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
    assert hosting == [{"target": "docs", "public": "site"}]
    assert script.serving_config(hosting[0]) == {}


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
