[CmdletBinding()]
param(
    [string] $WheelPath,
    [string] $InstallRoot,
    [ValidateSet('Prompt', 'Install', 'Skip')]
    [string] $Kokoro = 'Prompt',
    [ValidateSet('codex', 'claude')]
    [string[]] $Providers = @('codex', 'claude'),
    [string] $PythonExecutable
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $localApplicationData = $env:LOCALAPPDATA
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $localApplicationData = Join-Path $env:USERPROFILE 'AppData\Local'
    }
    else {
        throw 'LOCALAPPDATA or USERPROFILE is required for a no-admin installation.'
    }
    $InstallRoot = Join-Path $localApplicationData 'Programs\BLAIR'
}
$managedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$releaseWheel = Resolve-BlairWheel -WheelPath $WheelPath -SearchDirectories @(
    (Join-Path $PSScriptRoot '..\wheel'),
    (Join-Path $PSScriptRoot '..\dist'),
    (Join-Path $PSScriptRoot 'wheel')
)
$pythonLauncher = Get-BlairPythonLauncher -PythonExecutable $PythonExecutable

$virtualEnvironment = Join-Path $managedInstallRoot 'venv'
$venvPython = Join-Path $virtualEnvironment 'Scripts\python.exe'
$installMarker = Join-Path $managedInstallRoot 'installation.json'
if ((Test-Path -LiteralPath $virtualEnvironment) -and -not (Test-Path -LiteralPath $installMarker)) {
    throw "Refusing to reuse an unmarked virtual environment: $virtualEnvironment"
}

New-Item -ItemType Directory -Path $managedInstallRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $venvArguments = @($pythonLauncher.Prefix) + @('-m', 'venv', $virtualEnvironment)
    Invoke-BlairChecked -FilePath $pythonLauncher.Executable -ArgumentList $venvArguments `
        -Description 'Virtual environment creation'
}

Invoke-BlairChecked -FilePath $venvPython -ArgumentList @(
    '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--upgrade', $releaseWheel
) -Description 'BLAIR core installation'

$installationRecord = [ordered]@{
    product = 'BLAIR'
    format_version = 1
    install_root = $managedInstallRoot
    installed_from = $releaseWheel
    installed_at_utc = [DateTime]::UtcNow.ToString('o')
}
$installationRecord | ConvertTo-Json | Set-Content -LiteralPath $installMarker -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') `
    -Destination (Join-Path $managedInstallRoot 'uninstall.ps1') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '_common.ps1') `
    -Destination (Join-Path $managedInstallRoot '_common.ps1') -Force

$launcherPath = Join-Path $managedInstallRoot 'blair.cmd'
$launcherLines = @(
    '@echo off',
    '"%~dp0venv\Scripts\python.exe" -m blair %*'
)
$launcherLines | Set-Content -LiteralPath $launcherPath -Encoding ASCII

$installKokoro = $false
if ($Kokoro -eq 'Install') {
    $installKokoro = $true
}
elseif ($Kokoro -eq 'Prompt') {
    Write-Host 'Kokoro adds a local neural voice and downloads about 354 MB of model files.'
    $kokoroAnswer = Read-Host 'Install Kokoro and download its verified models? [y/N]'
    $installKokoro = $kokoroAnswer.Trim().ToLowerInvariant() -in @('y', 'yes')
}

if ($installKokoro) {
    $wheelWithKokoroExtra = '{0}[kokoro]' -f $releaseWheel
    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @(
        '-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', $wheelWithKokoroExtra
    ) -Description 'Optional Kokoro installation'
    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @(
        '-m', 'blair', 'setup', '--yes'
    ) -Description 'BLAIR Kokoro setup'
}
else {
    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @(
        '-m', 'blair', 'setup', '--skip-models'
    ) -Description 'BLAIR core setup'
}

$hookArguments = @('-m', 'blair', 'install') + @($Providers)
Invoke-BlairChecked -FilePath $venvPython -ArgumentList $hookArguments `
    -Description 'BLAIR hook installation'

Write-Host ''
Write-Host "BLAIR installed without administrator privileges at: $managedInstallRoot"
Write-Host "Launcher: $launcherPath"
Write-Host 'Open a new terminal and run the launcher path above with: doctor'
