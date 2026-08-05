$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"

function Find-Python {
    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path -LiteralPath $localPrograms) {
        $installed = Get-ChildItem -LiteralPath $localPrograms -Directory -Filter "Python*" |
            Sort-Object Name -Descending
        foreach ($directory in $installed) {
            $candidate = Join-Path $directory.FullName "python.exe"
            if (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    throw "Python was not found. Install a current 64-bit Python release."
}

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    $systemPython = Find-Python
    Write-Host "Creating a virtual environment with $systemPython"
    & $systemPython -m venv $venvRoot
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install --upgrade -r (Join-Path $projectRoot "requirements-build.txt")

$env:PYTHONPATH = Join-Path $projectRoot "src"
& $venvPython -m unittest discover -s (Join-Path $projectRoot "tests") -v
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed."
}

& $venvPython (Join-Path $projectRoot "tools\prepare_font_resources.py") --check-only
if ($LASTEXITCODE -ne 0) {
    throw "Font resources are not prepared. See fonts\README.md."
}

& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --contents-directory "_internal" `
    --name "LocalisationChecker" `
    --paths (Join-Path $projectRoot "src") `
    --version-file (Join-Path $projectRoot "version_info.txt") `
    (Join-Path $projectRoot "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}

$distRoot = Join-Path $projectRoot "dist\LocalisationChecker"
$fontTarget = Join-Path $distRoot "fonts"
$resolvedProject = (Resolve-Path -LiteralPath $projectRoot).Path

if (Test-Path -LiteralPath $fontTarget) {
    $resolvedFontTarget = (Resolve-Path -LiteralPath $fontTarget).Path
    if (-not $resolvedFontTarget.StartsWith(
        $resolvedProject,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Unsafe font target: $resolvedFontTarget"
    }
    Remove-Item -LiteralPath $resolvedFontTarget -Recurse -Force
}

Copy-Item -LiteralPath (Join-Path $projectRoot "fonts") -Destination $fontTarget -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot "font_profile.json") -Destination $distRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "settings.example.json") `
    -Destination (Join-Path $distRoot "settings.example.json")
Copy-Item -LiteralPath (Join-Path $projectRoot "README.txt") -Destination $distRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination $distRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "CHANGELOG.md") -Destination $distRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_NOTICES.md") -Destination $distRoot

$archivePath = Join-Path $projectRoot "dist\LocalisationChecker-Windows.zip"
if (Test-Path -LiteralPath $archivePath) {
    $resolvedArchive = (Resolve-Path -LiteralPath $archivePath).Path
    if (-not $resolvedArchive.StartsWith(
        $resolvedProject,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Unsafe archive target: $resolvedArchive"
    }
    Remove-Item -LiteralPath $resolvedArchive -Force
}
Compress-Archive -LiteralPath $distRoot -DestinationPath $archivePath -CompressionLevel Optimal

Write-Host ""
Write-Host "Application: $distRoot\LocalisationChecker.exe"
Write-Host "Distribution archive: $archivePath"
