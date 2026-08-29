Set-StrictMode -Version 3.0

function Get-BlairPythonLauncher {
    [CmdletBinding()]
    param(
        [string] $PythonExecutable
    )

    $pythonCandidates = @()
    if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $resolvedCommand = Get-Command -Name $PythonExecutable -ErrorAction SilentlyContinue
        if ($null -eq $resolvedCommand -and (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
            $resolvedPath = (Resolve-Path -LiteralPath $PythonExecutable).Path
        }
        elseif ($null -ne $resolvedCommand) {
            $resolvedPath = $resolvedCommand.Source
        }
        else {
            throw "Python executable was not found: $PythonExecutable"
        }
        $pythonCandidates += [PSCustomObject]@{
            Executable = $resolvedPath
            Prefix = @()
        }
    }
    else {
        $pyLauncher = Get-Command -Name 'py.exe' -ErrorAction SilentlyContinue
        if ($null -ne $pyLauncher) {
            $pythonCandidates += [PSCustomObject]@{
                Executable = $pyLauncher.Source
                Prefix = @('-3')
            }
        }
        $pythonCommand = Get-Command -Name 'python.exe' -ErrorAction SilentlyContinue
        if ($null -ne $pythonCommand) {
            $pythonCandidates += [PSCustomObject]@{
                Executable = $pythonCommand.Source
                Prefix = @()
            }
        }
    }

    $versionProbe = @'
import struct
import sys
supported = (3, 11) <= sys.version_info[:2] < (3, 14) and struct.calcsize("P") == 8
raise SystemExit(0 if supported else 1)
'@
    foreach ($pythonCandidate in $pythonCandidates) {
        $probeArguments = @($pythonCandidate.Prefix) + @('-c', $versionProbe)
        & $pythonCandidate.Executable @probeArguments *> $null
        if ($LASTEXITCODE -eq 0) {
            return $pythonCandidate
        }
    }
    throw 'BLAIR requires 64-bit Python 3.11, 3.12, or 3.13.'
}

function Invoke-BlairChecked {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,

        [Parameter(Mandatory = $true)]
        [string[]] $ArgumentList,

        [Parameter(Mandatory = $true)]
        [string] $Description
    )

    & $FilePath @ArgumentList
    $processExitCode = $LASTEXITCODE
    if ($processExitCode -ne 0) {
        throw "$Description failed with exit code $processExitCode."
    }
}

function Resolve-BlairWheel {
    [CmdletBinding()]
    param(
        [string] $WheelPath,
        [string[]] $SearchDirectories = @()
    )

    if (-not [string]::IsNullOrWhiteSpace($WheelPath)) {
        if (-not (Test-Path -LiteralPath $WheelPath -PathType Leaf)) {
            throw "Release wheel was not found: $WheelPath"
        }
        $wheelItem = Get-Item -LiteralPath $WheelPath
        if ($wheelItem.Extension -ne '.whl') {
            throw "Expected a local .whl file, received: $WheelPath"
        }
        return $wheelItem.FullName
    }

    $wheelCandidates = @()
    foreach ($searchDirectory in $SearchDirectories) {
        if (Test-Path -LiteralPath $searchDirectory -PathType Container) {
            $wheelCandidates += Get-ChildItem -LiteralPath $searchDirectory `
                -Filter 'blair_briefing-*.whl' -File
        }
    }
    $wheelCandidates = @($wheelCandidates | Sort-Object -Property FullName -Unique)
    if ($wheelCandidates.Count -ne 1) {
        throw 'Specify -WheelPath; exactly one local blair_briefing wheel was not found.'
    }
    return $wheelCandidates[0].FullName
}

function Assert-BlairSafeRemovalPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $Purpose
    )

    if (Test-Path -LiteralPath $Path) {
        $fullPath = (Resolve-Path -LiteralPath $Path).Path
    }
    else {
        $fullPath = [IO.Path]::GetFullPath($Path)
    }
    $trimCharacters = [char[]]@('\', '/')
    $trimmedPath = $fullPath.TrimEnd($trimCharacters)
    $pathRoot = [IO.Path]::GetPathRoot($fullPath).TrimEnd($trimCharacters)
    if ([string]::IsNullOrWhiteSpace($trimmedPath) -or $trimmedPath -eq $pathRoot) {
        throw "Refusing to remove an unsafe $Purpose path: $fullPath"
    }

    $protectedPaths = @(
        $env:SystemRoot,
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        $env:USERPROFILE,
        $env:LOCALAPPDATA
    )
    foreach ($protectedPath in $protectedPaths) {
        if ([string]::IsNullOrWhiteSpace($protectedPath)) {
            continue
        }
        $protectedFullPath = [IO.Path]::GetFullPath($protectedPath).TrimEnd($trimCharacters)
        if ($trimmedPath.Equals($protectedFullPath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove protected $Purpose path: $fullPath"
        }
    }
    return $fullPath
}

function Assert-BlairChildPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string] $ChildPath,

        [Parameter(Mandatory = $true)]
        [string] $ParentPath,

        [Parameter(Mandatory = $true)]
        [string] $Purpose
    )

    $fullParent = [IO.Path]::GetFullPath($ParentPath).TrimEnd('\', '/')
    $fullChild = Assert-BlairSafeRemovalPath -Path $ChildPath -Purpose $Purpose
    $parentPrefix = $fullParent + [IO.Path]::DirectorySeparatorChar
    if (-not $fullChild.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove $Purpose outside its managed parent: $fullChild"
    }
    return $fullChild
}

function Write-BlairUtf8NoBom {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string[]] $Lines
    )

    $utf8WithoutBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($Path, $Lines, $utf8WithoutBom)
}
