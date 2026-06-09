param(
    [Parameter(Mandatory = $true)]
    [string]$PayloadDir,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,

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

$payload = (Resolve-Path -LiteralPath $PayloadDir).Path
$guiExe = Join-Path $payload "MatchPatch.exe"
$cliExe = Join-Path $payload "matchpatch.exe"
$docsIndex = Join-Path $payload "docs_html\index.html"
$buildInfoPath = Join-Path $payload "build-info.json"

Assert-FileExists $guiExe
Assert-FileExists $cliExe
Assert-FileExists $docsIndex
Assert-FileExists $buildInfoPath

$buildInfo = Get-Content -LiteralPath $buildInfoPath -Raw | ConvertFrom-Json
if ($buildInfo.version -ne $ExpectedVersion) {
    throw "Payload build-info.json version '$($buildInfo.version)' did not match expected '$ExpectedVersion'"
}

$versionOutput = & $cliExe --version
if ($LASTEXITCODE -ne 0) {
    throw "matchpatch.exe --version failed with exit code $LASTEXITCODE"
}
if (($versionOutput -join "`n") -notmatch [regex]::Escape($ExpectedVersion)) {
    throw "matchpatch.exe --version output did not contain expected version '$ExpectedVersion': $versionOutput"
}

if ($GuiSmoke) {
    Invoke-MatchPatchGuiSmoke $guiExe
}

Write-Host "Payload smoke passed: $payload"
