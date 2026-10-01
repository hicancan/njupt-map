#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Blender = $env:BLENDER_EXE,
    [string]$TempRoot = $(if ($IsWindows) { 'D:\Temp\codex' } else { [IO.Path]::GetTempPath() }),
    [switch]$Full,
    [switch]$Render
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $Blender) { $Blender = (Get-Command blender -ErrorAction Stop).Source }
$tempBase = [IO.Path]::GetFullPath($TempRoot)
$temporary = Join-Path $tempBase ('njupt-map-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary -Force | Out-Null
$reports = Join-Path $repo 'build/checks/toolchain'
New-Item -ItemType Directory -Path $reports -Force | Out-Null
$oldTemp, $oldTmp = $env:TEMP, $env:TMP
$steps = [Collections.Generic.List[object]]::new()
function Invoke-Check([string]$Name, [string]$Exe, [string[]]$Arguments) {
    $log = Join-Path $temporary ($Name + '.log')
    $clock = [Diagnostics.Stopwatch]::StartNew()
    & $Exe @Arguments *> $log
    $code = $LASTEXITCODE
    $clock.Stop()
    Copy-Item -LiteralPath $log -Destination (Join-Path $reports ($Name + '.log')) -Force
    $steps.Add([pscustomobject]@{ name=$Name; exit_code=$code; seconds=[math]::Round($clock.Elapsed.TotalSeconds, 2) })
    Write-Host "$Name exit=$code seconds=$($steps[-1].seconds)"
    if ($code -ne 0) { Get-Content -LiteralPath $log -Tail 35; throw "$Name failed" }
}
Push-Location $repo
try {
    $env:TEMP = $temporary
    $env:TMP = $temporary
    if (-not (Test-Path -LiteralPath (Join-Path $repo '.venv'))) {
        Invoke-Check 'venv' 'uv' @('venv', '--python', '3.12')
    }
    Invoke-Check 'dependencies' 'uv' @('sync', '--locked')
    Invoke-Check 'tests' 'uv' @('run', 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v')
    Invoke-Check 'map-export' 'uv' @('run', 'python', '-m', 'src.map.export')
    Invoke-Check 'map-validation' 'uv' @('run', 'python', '-m', 'src.map.validate')
    Invoke-Check 'public-observations' 'uv' @('run', 'python', '-m', 'src.observations.validate', '--public')
    Invoke-Check 'scene-sync' 'uv' @('run', 'python', '-m', 'src.sync', '--blender', $Blender)
    $nativeArgs = @('--background', '--factory-startup', '--python-exit-code', '1', '--python', 'src/blender/checks/validate_native.py')
    if ($Render) { $nativeArgs += @('--', '--render') }
    Invoke-Check 'native-sources' $Blender $nativeArgs
    if ($Full) {
        Invoke-Check 'interiors' $Blender @('--background', '--factory-startup', '--python-exit-code', '1', '--python', 'src/blender/checks/validate_interiors.py', '--', '--authored')
        Invoke-Check 'native-exteriors' 'uv' @('run', 'python', '-m', 'src.runtime.native', '--blender', $Blender)
        Invoke-Check 'runtime' 'uv' @('run', 'python', '-m', 'src.runtime.export', '--native-detail', 'build/native-exteriors')
    } else {
        Invoke-Check 'runtime' 'uv' @('run', 'python', '-m', 'src.runtime.export')
    }
} finally {
    $env:TEMP, $env:TMP = $oldTemp, $oldTmp
    Pop-Location
    $steps | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $reports 'summary.json') -Encoding utf8NoBOM
    $resolved = [IO.Path]::GetFullPath($temporary)
    if (-not $resolved.StartsWith($tempBase.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Temporary directory escaped its configured root'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
