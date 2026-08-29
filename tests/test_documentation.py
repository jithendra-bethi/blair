from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def test_relative_markdown_links_resolve_to_repository_files() -> None:
    documents = [
        *ROOT.glob("*.md"),
        *ROOT.joinpath("docs").glob("*.md"),
        *ROOT.joinpath("packaging").glob("*.md"),
        *ROOT.joinpath("tests", "fixtures").glob("*.md"),
    ]
    missing: list[str] = []
    for document in documents:
        for raw_target in LINK_PATTERN.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (document.parent / unquote(parsed.path)).resolve()
            if not destination.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")

    assert missing == []


def test_supported_python_range_is_consistent_across_release_surfaces() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = json.loads(
        (ROOT / "packaging" / "portable-core-manifest.json").read_text(encoding="utf-8")
    )
    common_script = (ROOT / "scripts" / "_common.ps1").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert metadata["project"]["requires-python"] == ">=3.11,<3.14"
    assert manifest["requires"]["python"] == ">=3.11,<3.14 (64-bit)"
    assert "(3, 11) <= sys.version_info[:2] < (3, 14)" in common_script
    assert "Python 3.11" in readme and "3.13" in readme
