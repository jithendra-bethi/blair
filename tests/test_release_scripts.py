from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PACKAGING = ROOT / "packaging"
POWERSHELL_SCRIPTS = [
    SCRIPTS / "_common.ps1",
    SCRIPTS / "install.ps1",
    SCRIPTS / "uninstall.ps1",
    SCRIPTS / "build-release.ps1",
    SCRIPTS / "test-clean-install.ps1",
]


def _powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")


@pytest.mark.parametrize("script_path", POWERSHELL_SCRIPTS, ids=lambda path: path.name)
def test_release_powershell_has_no_parser_errors(script_path: Path) -> None:
    executable = _powershell()
    if executable is None:
        pytest.skip("PowerShell is unavailable")

    escaped_path = str(script_path).replace("'", "''")
    parser_command = """
$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    '__SCRIPT_PATH__',
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    $parseErrors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }
    exit 1
}
""".replace("__SCRIPT_PATH__", escaped_path)
    completed = subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            parser_command,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_install_is_no_admin_local_wheel_flow_with_explicit_setup_and_hooks() -> None:
    content = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")

    assert "Resolve-BlairWheel" in content
    assert "'-m', 'venv'" in content
    assert "'--no-deps'" in content
    assert "'-m', 'blair', 'setup', '--skip-models'" in content
    assert "'-m', 'blair', 'setup', '--yes'" in content
    assert "@('-m', 'blair', 'install')" in content
    assert "RunAs" not in content
    assert "Start-Process" not in content


def test_uninstall_removes_hooks_before_runtime_and_requires_explicit_purge() -> None:
    content = (SCRIPTS / "uninstall.ps1").read_text(encoding="utf-8")

    hook_position = content.index("@('-m', 'blair', 'uninstall')")
    runtime_removal_position = content.index("Remove-Item -LiteralPath $safeEnvironment")
    assert hook_position < runtime_removal_position
    assert "[switch] $PurgeUserData" in content
    assert "[switch] $PurgeBackups" in content
    assert "user data and downloaded models were preserved" in content
    assert "configuration backups were preserved" in content


def test_build_contract_emits_core_archive_and_checksums_without_optional_assets() -> None:
    content = (SCRIPTS / "build-release.ps1").read_text(encoding="utf-8")
    manifest = json.loads((PACKAGING / "portable-core-manifest.json").read_text(encoding="utf-8"))

    assert "'-m', 'build', '--wheel', '--sdist'" in content
    assert "'.venv\\Scripts\\python.exe'" in content
    assert 'version("setuptools")' in content
    assert 'version("wheel")' in content
    assert "'--no-isolation'" in content
    assert "Compress-Archive" in content
    assert "Get-FileHash" in content
    assert "SHA256SUMS" in content
    assert "docs\\third-party-licenses.md" in content
    assert "PRIVACY.md" in content
    assert "kokoro[_-]onnx" in content
    assert "Kokoro runtime dependencies" in manifest["excludes"]
    assert "Kokoro ONNX model files" in manifest["excludes"]
    assert "Python interpreter" in manifest["excludes"]
    assert any("documentation" in item for item in manifest["bundles"])


def test_clean_install_contract_sandboxes_configs_and_exercises_generic_hook() -> None:
    content = (SCRIPTS / "test-clean-install.ps1").read_text(encoding="utf-8")

    assert "BLAIR clean install " in content
    assert "Installed Application With Spaces" in content
    assert "$env:BLAIR_HOME = $testDataRoot" in content
    assert "$env:USERPROFILE = $testProfileRoot" in content
    assert "$env:LOCALAPPDATA = $testLocalApplicationData" in content
    assert "'-m', 'blair', 'doctor'" in content
    assert "'-m', 'blair', 'demo', '--no-play'" in content
    assert "-m blair hook generic" in content
    assert "-PurgeUserData -PurgeBackups" in content
