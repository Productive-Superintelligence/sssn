import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest


ROOT = Path(__file__).resolve().parents[1]


def build_docs(tmp_path: Path) -> Path:
    pytest.importorskip("mkdocs")
    site_dir = tmp_path / "site"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--site-dir",
            str(site_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    return site_dir


def test_docs_render_mermaid_as_diagram_containers(tmp_path):
    site_dir = build_docs(tmp_path)
    html_pages = [
        (path, path.read_text(encoding="utf-8"))
        for path in sorted(site_dir.rglob("*.html"))
    ]
    diagram_pages = [
        path for path, html in html_pages if 'class="mermaid"' in html
    ]
    highlighted_pages = [
        path
        for path, html in html_pages
        if "language-mermaid" in html or "highlight-mermaid" in html
    ]

    assert diagram_pages
    assert not highlighted_pages

    for path in diagram_pages:
        html = path.read_text(encoding="utf-8")
        assert "javascripts/vendor/mermaid.min.js" in html
        assert "javascripts/mermaid.js" in html
        assert "cdn.jsdelivr" not in html
        assert "unpkg" not in html

    vendor_js = site_dir / "javascripts" / "vendor" / "mermaid.min.js"
    vendor_license = site_dir / "javascripts" / "vendor" / "mermaid-LICENSE.txt"
    assert vendor_js.exists()
    assert vendor_license.exists()


def test_docs_keep_light_brand_styles(tmp_path):
    site_dir = build_docs(tmp_path)
    custom_css = (site_dir / "stylesheets" / "custom.css").read_text(
        encoding="utf-8"
    )
    mermaid_js = (site_dir / "javascripts" / "mermaid.js").read_text(
        encoding="utf-8"
    )
    index_html = (site_dir / "index.html").read_text(encoding="utf-8")

    assert ".md-header," in custom_css
    assert ".md-tabs {" in custom_css
    assert ".md-header--shadow" in custom_css
    assert "background-color: #ffffff;" in custom_css
    assert "--md-footer-fg-color--light: var(--psi-ink);" in custom_css
    assert '--md-text-font: "Roboto";' in custom_css
    assert "--md-text-font-family" in custom_css
    assert "-apple-system" in custom_css
    assert ".md-header__button.md-logo" in custom_css
    assert "width: 1.2rem;" in custom_css
    assert ".md-search__form .md-icon svg" in custom_css
    assert "fill: currentcolor;" in custom_css
    assert ".md-nav__button.md-logo" in custom_css
    assert ".psi-footer-mark" in custom_css
    assert 'background-image: url("../assets/logo.svg");' in custom_css
    assert "font-size: 0.8rem;" in custom_css
    assert "min-height: 2.2rem;" in custom_css
    assert ".md-social__link" in custom_css
    assert "height: 1rem;" in custom_css
    assert ".psi-brand img" in custom_css
    assert "height: clamp(1.85rem, 5vw, 2.35rem);" in custom_css
    assert ".md-typeset .mermaid svg" in custom_css
    assert "max-width: 100%;" in custom_css
    assert "min-width: 34rem;" in custom_css
    assert ".md-typeset .mermaid .node rect" in custom_css
    assert ".md-typeset .mermaid .edgePath path" in custom_css
    assert ".md-typeset .mermaid marker path" in custom_css
    assert "-apple-system, BlinkMacSystemFont" in mermaid_js
    assert "window.mermaid.startOnLoad = false" in mermaid_js
    assert 'securityLevel: "strict"' in mermaid_js
    assert "flowchart:" in mermaid_js
    assert "htmlLabels: false" in mermaid_js
    assert "useMaxWidth: true" in mermaid_js
    assert "data-mermaid-source" in mermaid_js
    assert "normalizeDiagramNode" in mermaid_js
    assert "pre code.language-mermaid" in mermaid_js
    assert "data-mermaid-error" in mermaid_js
    assert "attempt < 30" in mermaid_js
    assert "requestAnimationFrame" in mermaid_js
    assert "window.document$.subscribe(scheduleRender)" in mermaid_js
    assert 'window.addEventListener("load", scheduleRender)' in mermaid_js
    assert "assets/logo.svg" in index_html
    assert "assets/sssn-logo-text-dark.png" in index_html
    assert "psi-footer-mark" in index_html
    assert "<div class=\"md-source__repository\">\n    GitHub\n  </div>" in index_html
    assert 'data-md-component="source"' not in index_html
    assert 'src="/assets/sssn-logo-text-dark.png"' not in index_html

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '<img src="assets/sssn-logo-text-dark.png" alt="SSSN" height="56">' in readme
    assert (site_dir / "CNAME").read_text(encoding="utf-8").strip() == "sssn.one"


def test_http_api_reference_distinguishes_artifact_payload_and_metadata():
    reference = (ROOT / "docs" / "reference" / "http-api.md").read_text(
        encoding="utf-8"
    )

    assert "| `GET /artifacts/{id}` | Read artifact payload bytes. |" in reference
    assert (
        "| `GET /artifacts/{id}/metadata` | Read artifact metadata only. |"
        in reference
    )


def test_http_api_reference_lists_portable_endpoints():
    reference = (ROOT / "docs" / "reference" / "http-api.md").read_text(
        encoding="utf-8"
    )
    expected = {
        "POST /channels",
        "GET /channels",
        "GET /channels/{name}",
        "POST /events",
        "GET /events?channel=...",
        "GET /events/{id}",
        "POST /subscriptions",
        "GET /subscriptions/{id}",
        "POST /subscriptions/{id}/pull",
        "POST /artifacts",
        "GET /artifacts/{id}",
        "GET /artifacts/{id}/metadata",
        "PUT /snapshots/{name}",
        "GET /snapshots/{name}",
    }

    for endpoint in expected:
        assert f"| `{endpoint}` |" in reference


def test_cli_reference_lists_portable_resource_commands():
    reference = (ROOT / "docs" / "reference" / "cli.md").read_text(
        encoding="utf-8"
    )
    expected = [
        "create-channel events --schema demo.Event --metadata",
        "append events",
        "--correlation-id corr-1 --parent-id <event-id>",
        "query-events events --limit 10",
        "get-event <event-id>",
        "create-subscription events --id worker --kind message",
        "pull-subscription worker --limit 10",
        "get-subscription worker",
        "write-artifact 'hello' --media-type text/plain --event-id <event-id>",
        "get-artifact <artifact-id>",
        "read-artifact <artifact-id>",
        "put-snapshot latest",
        "--source-event-id <event-id>",
        "get-snapshot latest",
    ]

    for command in expected:
        assert command in reference


def test_psihub_package_guide_documents_endpoint_metadata():
    guide = (ROOT / "docs" / "guides" / "psihub-packages.md").read_text(
        encoding="utf-8"
    )

    assert "custom_endpoints=[channel_tail]" in guide
    assert '"path": "/channels/{name}/tail"' in guide
    assert "create_app(..., custom_endpoints=...)" in guide
    assert (
        "python -m pytest tests/test_psihub_integration.py tests/test_examples.py -q"
        in guide
    )


def test_public_text_does_not_use_staging_name():
    text_paths = [ROOT / "README.md"]
    text_paths.extend((ROOT / "docs").rglob("*.md"))
    text_paths.extend(
        path
        for path in (ROOT / "examples").rglob("*")
        if path.suffix in {".md", ".py", ".toml", ".yaml", ".yml"}
    )

    for path in text_paths:
        text = path.read_text(encoding="utf-8")
        assert "LLLM v2" not in text, path
        assert "lllmv2" not in text, path
        assert "SSSN v2" not in text, path
        assert "sssnv2" not in text, path


def test_tutorials_keep_step_by_step_shape():
    required = [
        "Goal:",
        "## Prerequisites",
        "## Files Used",
        "## Verify",
        "Expected output:",
        "Next,",
    ]

    for path in sorted((ROOT / "docs" / "tutorials").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path.relative_to(ROOT)} missing {marker}"


def test_readme_and_docs_local_links_resolve():
    pattern = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    text_paths = [ROOT / "README.md"]
    text_paths.extend((ROOT / "docs").rglob("*.md"))
    skip_prefixes = ("http://", "https://", "mailto:", "#")

    missing = []
    for path in sorted(text_paths):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            if not target or target.startswith(skip_prefixes) or "://" in target:
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            if not (path.parent / unquote(target)).resolve().exists():
                missing.append(f"{path.relative_to(ROOT)} -> {match.group(1)}")

    assert missing == []
