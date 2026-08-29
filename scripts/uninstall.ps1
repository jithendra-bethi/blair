[CmdletBinding()]
param(
    [string] $InstallRoot,
    [string] $BlairDataRoot,
    [switch] $PurgeUserData,
    [switch] $PurgeBackups,
    [switch] $HooksAlreadyRemoved
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\BLAIR'
    }
    else {
        throw 'Specify -InstallRoot because LOCALAPPDATA is unavailable.'
    }
}
$managedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$installMarker = Join-Path $managedInstallRoot 'installation.json'
if (-not (Test-Path -LiteralPath $installMarker -PathType Leaf)) {
    throw "This is not a BLAIR-managed installation: $managedInstallRoot"
}
$markerRecord = Get-Content -LiteralPath $installMarker -Raw | ConvertFrom-Json
if ($markerRecord.product -ne 'BLAIR') {
    throw "Invalid BLAIR installation marker: $installMarker"
}

$virtualEnvironment = Join-Path $managedInstallRoot 'venv'
$venvPython = Join-Path $virtualEnvironment 'Scripts\python.exe'
if (-not $HooksAlreadyRemoved) {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'Managed hooks cannot be removed because the installed BLAIR runtime is missing.'
    }
    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @('-m', 'blair', 'uninstall') `
        -Description 'Managed hook removal'
}

if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    & $venvPython -m blair daemon stop *> $null
}

if (Test-Path -LiteralPath $virtualEnvironment) {
    $safeEnvironment = Assert-BlairChildPath -ChildPath $virtualEnvironment `
        -ParentPath $managedInstallRoot -Purpose 'BLAIR virtual environment'
    Remove-Item -LiteralPath $safeEnvironment -Recurse -Force
}

foreach ($managedFileName in @('blair.cmd', 'installation.json', 'uninstall.ps1', '_common.ps1')) {
    $managedFile = Join-Path $managedInstallRoot $managedFileName
    if (Test-Path -LiteralPath $managedFile -PathType Leaf) {
        Remove-Item -LiteralPath $managedFile -Force
    }
}

if ($PurgeUserData) {
    if ([string]::IsNullOrWhiteSpace($BlairDataRoot)) {
        if (-not [string]::IsNullOrWhiteSpace($env:BLAIR_HOME)) {
            $BlairDataRoot = $env:BLAIR_HOME
        }
        elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $BlairDataRoot = Join-Path $env:LOCALAPPDATA 'BLAIR'
        }
        else {
            throw 'Specify -BlairDataRoot before purging user data.'
        }
    }
    if (Test-Path -LiteralPath $BlairDataRoot) {
        $safeDataRoot = Assert-BlairSafeRemovalPath -Path $BlairDataRoot `
            -Purpose 'BLAIR user data'
        Remove-Item -LiteralPath $safeDataRoot -Recurse -Force
        Write-Host "Removed BLAIR user data and models: $safeDataRoot"
    }
}
else {
    Write-Host 'BLAIR user data and downloaded models were preserved.'
}

if ($PurgeBackups) {
    if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        throw 'USERPROFILE is required to remove BLAIR-created configuration backups.'
    }
    $backupLocations = @(
        [PSCustomObject]@{
            Directory = Join-Path $env:USERPROFILE '.codex'
            Filter = 'config.toml.blair-backup-*'
        },
        [PSCustomObject]@{
            Directory = Join-Path $env:USERPROFILE '.claude'
            Filter = 'settings.json.blair-backup-*'
        }
    )
    foreach ($backupLocation in $backupLocations) {
        if (Test-Path -LiteralPath $backupLocation.Directory -PathType Container) {
            Get-ChildItem -LiteralPath $backupLocation.Directory -Filter $backupLocation.Filter `
                -File | Remove-Item -Force
        }
    }
    Write-Host 'Removed BLAIR-created Codex and Claude configuration backups.'
}
else {
    Write-Host 'BLAIR-created configuration backups were preserved.'
}

if (Test-Path -LiteralPath $managedInstallRoot -PathType Container) {
    $remainingFiles = @(Get-ChildItem -LiteralPath $managedInstallRoot -Force)
    if ($remainingFiles.Count -eq 0) {
        Remove-Item -LiteralPath $managedInstallRoot -Force
    }
}
Write-Host 'BLAIR managed hooks and core runtime were removed.'
