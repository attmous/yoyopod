from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_ROOT = REPO_ROOT / "yoyopod_cli"
FORBIDDEN_ROOT = "yoyo" + "pod"


def _active_python_files() -> list[Path]:
    return [
        path
        for path in ACTIVE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def test_cli_sources_do_not_import_retired_python_runtime_package() -> None:
    offenders: list[str] = []
    for path in _active_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_names = [node.module or ""]
            else:
                continue
            for imported_name in imported_names:
                if imported_name == FORBIDDEN_ROOT or imported_name.startswith(
                    f"{FORBIDDEN_ROOT}."
                ):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)} imports {imported_name!r}"
                    )

    assert offenders == []
