param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,

    [string]$InstallDir = (Join-Path $env:TEMP ("MatchPatch-smoke-" + [guid]::NewGuid().ToString("N"))),

    [switch]$GuiSmoke
)

$ErrorActionPreference = "Stop"

function Assert-FileExists {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing expected file: $Path"
    }
}

function Invoke-MatchPatchGuiSmoke {
    param([Parameter(Mandatory = $true)][string]$GuiExe)

    $previousSmoke = $env:MATCHPATCH_GUI_SMOKE
    try {
        $env:MATCHPATCH_GUI_SMOKE = "1"
        & $GuiExe
        if ($LASTEXITCODE -ne 0) {
            throw "GUI smoke failed with exit code $LASTEXITCODE"
        }
    } finally {
        $env:MATCHPATCH_GUI_SMOKE = $previousSmoke
    }
}

$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$installArgs = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=$InstallDir"
)

& $installer @installArgs
if ($LASTEXITCODE -ne 0) {
    throw "Installer failed with exit code $LASTEXITCODE"
}

$guiExe = Join-Path $InstallDir "MatchPatch.exe"
$cliExe = Join-Path $InstallDir "matchpatch.exe"
$docsIndex = Join-Path $InstallDir "docs_html\index.html"
$uninstaller = Join-Path $InstallDir "unins000.exe"

Assert-FileExists $guiExe
Assert-FileExists $cliExe
Assert-FileExists $docsIndex
Assert-FileExists $uninstaller

$versionOutput = & $cliExe --version
if ($LASTEXITCODE -ne 0) {
    throw "Installed matchpatch.exe --version failed with exit code $LASTEXITCODE"
}
if (($versionOutput -join "`n") -notmatch [regex]::Escape($ExpectedVersion)) {
    throw "Installed matchpatch.exe --version output did not contain expected version '$ExpectedVersion': $versionOutput"
}

if ($GuiSmoke) {
    Invoke-MatchPatchGuiSmoke $guiExe
}

& $uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
if ($LASTEXITCODE -ne 0) {
    throw "Uninstaller failed with exit code $LASTEXITCODE"
}

Start-Sleep -Seconds 2
if (Test-Path -LiteralPath $InstallDir) {
    $leftovers = @(Get-ChildItem -LiteralPath $InstallDir -Force)
    $unexpected = @($leftovers | Where-Object { $_.Name -notmatch "^unins\d+\.dat$|^unins\d+\.msg$|^unins\d+\.log$" })
    if ($unexpected.Count -gt 0) {
        throw "Install directory contains unexpected leftovers after uninstall: $($unexpected.FullName -join ', ')"
    }
}

Write-Host "Installed smoke passed: $installer"
