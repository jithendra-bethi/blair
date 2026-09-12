[CmdletBinding()]
param(
    [string] $WheelPath,
    [string] $PythonExecutable,
    [int] $TimeoutSeconds = 60,
    [switch] $KeepTemporary
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if ($env:OS -ne 'Windows_NT') {
    throw 'The clean-install release test requires Windows.'
}
$releaseWheel = Resolve-BlairWheel -WheelPath $WheelPath -SearchDirectories @(
    (Join-Path $PSScriptRoot '..\wheel'),
    (Join-Path $PSScriptRoot '..\dist'),
    (Join-Path $PSScriptRoot 'wheel')
)

$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$sandboxRoot = Join-Path $temporaryBase ('BLAIR clean install ' + [Guid]::NewGuid().ToString('N'))
$testInstallRoot = Join-Path $sandboxRoot 'Installed Application With Spaces'
$testDataRoot = Join-Path $sandboxRoot 'BLAIR Home With Spaces'
$testProfileRoot = Join-Path $sandboxRoot 'User Profile With Spaces'
$testLocalApplicationData = Join-Path $testProfileRoot 'AppData\Local'
$testSessionId = 'clean-install-generic-hook'
$venvPython = Join-Path $testInstallRoot 'venv\Scripts\python.exe'

$environmentNames = @('BLAIR_HOME', 'BLAIR_CONSENT_RESPONSE', 'BLAIR_LAUNCH_ID', 'USERPROFILE', 'LOCALAPPDATA')
$savedEnvironment = @{}
foreach ($environmentName in $environmentNames) {
    $savedEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable(
        $environmentName,
        'Process'
    )
}

New-Item -ItemType Directory -Path $testProfileRoot -Force | Out-Null
New-Item -ItemType Directory -Path $testLocalApplicationData -Force | Out-Null
$env:BLAIR_HOME = $testDataRoot
$env:BLAIR_CONSENT_RESPONSE = 'yes'
$env:BLAIR_LAUNCH_ID = [Guid]::NewGuid().ToString()
$env:USERPROFILE = $testProfileRoot
$env:LOCALAPPDATA = $testLocalApplicationData

$installationSucceeded = $false
try {
    & (Join-Path $PSScriptRoot 'install.ps1') -WheelPath $releaseWheel `
        -InstallRoot $testInstallRoot -Kokoro Skip -PythonExecutable $PythonExecutable
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Clean installation did not create: $venvPython"
    }
    $installationSucceeded = $true

    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @('-m', 'blair', 'doctor') `
        -Description 'Clean-install doctor check'
    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @(
        '-m', 'blair', 'demo', '--no-play'
    ) -Description 'Clean-install demo'

    $genericPayload = [ordered]@{
        event_id = 'clean-install-event-1'
        provider = 'generic-e2e'
        session_id = $testSessionId
        text = 'Implemented the release verification. All checks passed.'
        event_name = 'agent-turn-complete'
    } | ConvertTo-Json -Compress
    $genericPayload | & $venvPython -m blair hook generic
    if ($LASTEXITCODE -ne 0) {
        throw "Generic hook process failed with exit code $LASTEXITCODE."
    }

    $statePath = Join-Path $testDataRoot 'sessions.json'
    $hookCompleted = $false
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            try {
                $sessionState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                $sessionProperty = @($sessionState.sessions.PSObject.Properties | Where-Object {
                    $_.Name -eq $testSessionId
                })
                if ($sessionProperty.Count -eq 1) {
                    $sessionRecord = $sessionProperty[0].Value
                    if (
                        -not [string]::IsNullOrWhiteSpace($sessionRecord.last_briefing) -and
                        -not [string]::IsNullOrWhiteSpace($sessionRecord.last_audio) -and
                        (Test-Path -LiteralPath $sessionRecord.last_audio -PathType Leaf)
                    ) {
                        $hookCompleted = $true
                        break
                    }
                }
            }
            catch {
                # The daemon writes atomically; retry transient observation failures.
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $hookCompleted) {
        throw 'Timed out waiting for the simulated generic hook briefing.'
    }

    $codexConfig = Join-Path $testProfileRoot '.codex\config.toml'
    $claudeSettings = Join-Path $testProfileRoot '.claude\settings.json'
    if (-not (Test-Path -LiteralPath $codexConfig -PathType Leaf)) {
        throw 'The clean install did not create the sandboxed Codex integration.'
    }
    if (-not (Test-Path -LiteralPath $claudeSettings -PathType Leaf)) {
        throw 'The clean install did not create the sandboxed Claude integration.'
    }

    Invoke-BlairChecked -FilePath $venvPython -ArgumentList @(
        '-m', 'blair', 'daemon', 'stop'
    ) -Description 'Clean-install daemon shutdown'

    if (-not $KeepTemporary) {
        & (Join-Path $PSScriptRoot 'uninstall.ps1') -InstallRoot $testInstallRoot `
            -BlairDataRoot $testDataRoot -PurgeUserData -PurgeBackups
        foreach ($sandboxedConfig in @($codexConfig, $claudeSettings)) {
            if (
                (Test-Path -LiteralPath $sandboxedConfig -PathType Leaf) -and
                (Get-Content -LiteralPath $sandboxedConfig -Raw) -match 'BLAIR'
            ) {
                throw "Managed hooks remain after clean uninstall: $sandboxedConfig"
            }
        }
    }
    Write-Host 'Clean-install verification passed: doctor, demo, hooks, and generic E2E.'
}
finally {
    if ($installationSucceeded -and (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        & $venvPython -m blair daemon stop *> $null
    }

    foreach ($environmentName in $environmentNames) {
        [Environment]::SetEnvironmentVariable(
            $environmentName,
            $savedEnvironment[$environmentName],
            'Process'
        )
    }

    if ($KeepTemporary) {
        Write-Host "Temporary clean-install sandbox preserved at: $sandboxRoot"
    }
    elseif (Test-Path -LiteralPath $sandboxRoot) {
        $safeSandbox = Assert-BlairSafeRemovalPath -Path $sandboxRoot `
            -Purpose 'clean-install sandbox'
        $temporaryPrefix = $temporaryBase.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        $sandboxLeaf = Split-Path -Leaf $safeSandbox
        if (
            -not $safeSandbox.StartsWith(
                $temporaryPrefix,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $sandboxLeaf.StartsWith('BLAIR clean install ')
        ) {
            throw "Refusing to clean unexpected test directory: $safeSandbox"
        }
        Remove-Item -LiteralPath $safeSandbox -Recurse -Force
    }
}
