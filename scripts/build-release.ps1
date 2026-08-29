[CmdletBinding()]
param(
    [string] $OutputDirectory,
    [string] $PythonExecutable
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $projectRoot 'release'
}
$releaseOutput = [IO.Path]::GetFullPath($OutputDirectory)
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $projectPython -PathType Leaf) {
        $PythonExecutable = $projectPython
    }
}
$pythonLauncher = Get-BlairPythonLauncher -PythonExecutable $PythonExecutable

$buildToolProbe = @'
from importlib.metadata import version
from packaging.version import Version
assert Version(version("build")) < Version("2")
assert Version(version("setuptools")) >= Version("77")
assert Version(version("wheel")) >= Version("0.45")
'@
$buildToolArguments = @($pythonLauncher.Prefix) + @('-c', $buildToolProbe)
& $pythonLauncher.Executable @buildToolArguments *> $null
if ($LASTEXITCODE -ne 0) {
    throw (
        'The selected Python environment must already contain build, setuptools>=77, ' +
        'and wheel>=0.45. Install the project dev dependencies before building a release.'
    )
}

foreach ($requiredProjectFile in @(
    'pyproject.toml',
    'README.md',
    'PRIVACY.md',
    'LICENSE',
    'docs\third-party-licenses.md'
)) {
    $requiredPath = Join-Path $projectRoot $requiredProjectFile
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Release build requires: $requiredPath"
    }
}

$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$stagingRoot = Join-Path $temporaryBase ('BLAIR release build ' + [Guid]::NewGuid().ToString('N'))
$stagingDist = Join-Path $stagingRoot 'dist'
New-Item -ItemType Directory -Path $stagingDist -Force | Out-Null
New-Item -ItemType Directory -Path $releaseOutput -Force | Out-Null

try {
    $buildArguments = @($pythonLauncher.Prefix) + @(
        '-m', 'build', '--wheel', '--sdist', '--no-isolation',
        '--outdir', $stagingDist, $projectRoot
    )
    Invoke-BlairChecked -FilePath $pythonLauncher.Executable -ArgumentList $buildArguments `
        -Description 'Python release build'

    $builtWheels = @(Get-ChildItem -LiteralPath $stagingDist `
        -Filter 'blair_briefing-*.whl' -File)
    $builtSourceArchives = @(Get-ChildItem -LiteralPath $stagingDist `
        -Filter 'blair_briefing-*.tar.gz' -File)
    if ($builtWheels.Count -ne 1 -or $builtSourceArchives.Count -ne 1) {
        throw 'Expected exactly one BLAIR wheel and one source archive.'
    }
    $coreWheel = $builtWheels[0]
    $sourceArchive = $builtSourceArchives[0]
    $wheelNameMatch = [regex]::Match(
        $coreWheel.Name,
        '^blair_briefing-(?<version>.+?)-py3-none-any\.whl$'
    )
    if (-not $wheelNameMatch.Success) {
        throw "Cannot derive a release version from: $($coreWheel.Name)"
    }
    $releaseVersion = $wheelNameMatch.Groups['version'].Value

    $bundleRoot = Join-Path $stagingRoot "BLAIR-$releaseVersion-windows-core"
    $bundleWheelDirectory = Join-Path $bundleRoot 'wheel'
    $bundleScriptsDirectory = Join-Path $bundleRoot 'scripts'
    $bundlePackagingDirectory = Join-Path $bundleRoot 'packaging'
    $bundleDocsDirectory = Join-Path $bundleRoot 'docs'
    New-Item -ItemType Directory -Path $bundleWheelDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $bundleScriptsDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $bundlePackagingDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $bundleDocsDirectory -Force | Out-Null

    Copy-Item -LiteralPath $coreWheel.FullName -Destination $bundleWheelDirectory
    foreach ($releaseScript in @(
        '_common.ps1', 'install.ps1', 'uninstall.ps1', 'test-clean-install.ps1'
    )) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $releaseScript) `
            -Destination $bundleScriptsDirectory
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\WINDOWS_RELEASE.md') `
        -Destination $bundlePackagingDirectory
    Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\portable-core-manifest.json') `
        -Destination $bundlePackagingDirectory
    Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination $bundleRoot
    Copy-Item -LiteralPath (Join-Path $projectRoot 'PRIVACY.md') -Destination $bundleRoot
    Copy-Item -LiteralPath (Join-Path $projectRoot 'CHANGELOG.md') -Destination $bundleRoot
    Copy-Item -LiteralPath (Join-Path $projectRoot 'SECURITY.md') -Destination $bundleRoot
    Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $bundleRoot
    Get-ChildItem -LiteralPath (Join-Path $projectRoot 'docs') -Filter '*.md' -File |
        Copy-Item -Destination $bundleDocsDirectory

    $forbiddenBundleFiles = @(Get-ChildItem -LiteralPath $bundleRoot -Recurse -File | Where-Object {
        $_.Extension -in @('.onnx', '.bin', '.npy') -or
        $_.Name -match '^(kokoro[_-]onnx|soundfile)-.+\.whl$'
    })
    if ($forbiddenBundleFiles.Count -gt 0) {
        throw 'Portable core bundle unexpectedly contains optional runtime or model assets.'
    }

    $publishedWheel = Join-Path $releaseOutput $coreWheel.Name
    $publishedSourceArchive = Join-Path $releaseOutput $sourceArchive.Name
    Copy-Item -LiteralPath $coreWheel.FullName -Destination $publishedWheel -Force
    Copy-Item -LiteralPath $sourceArchive.FullName -Destination $publishedSourceArchive -Force

    $portableArchiveName = "BLAIR-$releaseVersion-windows-core.zip"
    $portableArchive = Join-Path $releaseOutput $portableArchiveName
    Compress-Archive -Path (Join-Path $bundleRoot '*') -DestinationPath $portableArchive `
        -CompressionLevel Optimal -Force

    $checksumTargets = @(
        Get-Item -LiteralPath $publishedWheel
        Get-Item -LiteralPath $publishedSourceArchive
        Get-Item -LiteralPath $portableArchive
    ) | Sort-Object -Property Name
    $checksumLines = @($checksumTargets | ForEach-Object {
        $fileHash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        '{0}  {1}' -f $fileHash.Hash.ToLowerInvariant(), $_.Name
    })
    $checksumPath = Join-Path $releaseOutput 'SHA256SUMS'
    Write-BlairUtf8NoBom -Path $checksumPath -Lines $checksumLines

    Write-Host "Release artifacts written to: $releaseOutput"
    $checksumTargets | ForEach-Object { Write-Host "  $($_.Name)" }
    Write-Host '  SHA256SUMS'
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        $resolvedStaging = Assert-BlairSafeRemovalPath -Path $stagingRoot `
            -Purpose 'release staging directory'
        $temporaryPrefix = $temporaryBase.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        $stagingLeaf = Split-Path -Leaf $resolvedStaging
        if (
            -not $resolvedStaging.StartsWith(
                $temporaryPrefix,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $stagingLeaf.StartsWith('BLAIR release build ')
        ) {
            throw "Refusing to clean unexpected release staging directory: $resolvedStaging"
        }
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
}
