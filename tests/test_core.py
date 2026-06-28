import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "sssn" / "core"
FORBIDDEN_CORE_IMPORT_PREFIXES = (
    "fastapi",
    "httpx",
    "lllm",
    "psihub",
    "sssn.cli",
    "sssn.client",
    "sssn.integrations",
    "sssn.server",
    "sssn.stores",
)


def test_core_layer_has_no_store_service_or_cross_layer_imports():
    leaks: list[str] = []
    for path in sorted(CORE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _source_imports(tree):
            if module.startswith(FORBIDDEN_CORE_IMPORT_PREFIXES):
                leaks.append(f"{path.relative_to(ROOT)} imports {module}")

    assert leaks == []


def _source_imports(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(node)
            if module:
                modules.append(module)
    return modules


def _resolve_import_from(node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    if node.level == 1:
        return f"sssn.core.{node.module}" if node.module else "sssn.core"
    if node.level == 2:
        return f"sssn.{node.module}" if node.module else "sssn"
    return f"<outside-sssn>.{node.module}" if node.module else "<outside-sssn>"
