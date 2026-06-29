import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_sdist_includes_repo_materials(tmp_path):
    pytest.importorskip("build")
    dist_dir = tmp_path / "dist"
    result = subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(dist_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    archives = list(dist_dir.glob("*.tar.gz"))
    assert len(archives) == 1
    root = archives[0].name.removesuffix(".tar.gz")
    with tarfile.open(archives[0]) as archive:
        names = set(archive.getnames())

    required = [
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "assets/sssn-logo-dark.svg",
        "assets/sssn-logo-text-dark.png",
        "assets/sssn-logo-text-white.png",
        "mkdocs.yml",
        "docs/index.md",
        "docs/assets/logo.svg",
        "docs/assets/sssn-logo-text-dark.png",
        "docs/assets/sssn-logo-text-white.png",
        "docs/javascripts/vendor/mermaid.min.js",
        "docs/javascripts/vendor/mermaid-LICENSE.txt",
        "docs/tutorials/first-channel.md",
        "examples/first_channel/README.md",
        "examples/first_channel/workflow.py",
        "examples/channel_processor/README.md",
        "examples/channel_processor/processor.py",
        "examples/artifact_snapshot/README.md",
        "examples/artifact_snapshot/workflow.py",
        "examples/psihub_manifest/README.md",
        "examples/psihub_manifest/package_manifest.py",
        "examples/lllm_tactic_processor/README.md",
        "examples/lllm_tactic_processor/workflow.py",
        "sssn/resolver.py",
    ]
    missing = [path for path in required if f"{root}/{path}" not in names]

    assert not missing
    assert not any(name.startswith(f"{root}/site/") for name in names)
