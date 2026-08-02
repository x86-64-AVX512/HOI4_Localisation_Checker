$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = $null
$localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"

if (Test-Path -LiteralPath $localPrograms) {
    $installed = Get-ChildItem -LiteralPath $localPrograms -Directory -Filter "Python*" |
        Sort-Object Name -Descending
    foreach ($directory in $installed) {
        $candidate = Join-Path $directory.FullName "python.exe"
        if (Test-Path -LiteralPath $candidate) {
            $python = $candidate
            break
        }
    }
}
if (-not $python) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
& $python -m unittest discover -s (Join-Path $projectRoot "tests") -v
