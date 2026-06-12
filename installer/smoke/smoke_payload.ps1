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

function Invoke-MatchPatchCliVersionSmoke {
    param([Parameter(Mandatory = $true)][string]$GuiExe)

    $process = Start-Process -FilePath $GuiExe -ArgumentList @("--cli", "--version") -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "MatchPatch.exe --cli --version failed with exit code $($process.ExitCode)"
    }
}

$payload = (Resolve-Path -LiteralPath $PayloadDir).Path
$guiExe = Join-Path $payload "MatchPatch.exe"
$docsIndex = Join-Path $payload "docs_html\index.html"
$buildInfoPath = Join-Path $payload "build-info.json"
$installerIcon = Join-Path $payload "installer-assets\matchpatch.ico"
$wizardLogo = Join-Path $payload "installer-assets\wizard-logo.bmp"
$wizardSmallLogo = Join-Path $payload "installer-assets\wizard-small-logo.bmp"
$referenceDi = Join-Path $payload "audio\reference-di\DI_Strandberg_Boden_Fusion_Bridge_Humbucker.wav"

Assert-FileExists $guiExe
Assert-FileExists $docsIndex
Assert-FileExists $buildInfoPath
Assert-FileExists $installerIcon
Assert-FileExists $wizardLogo
Assert-FileExists $wizardSmallLogo
Assert-FileExists $referenceDi

$buildInfo = Get-Content -LiteralPath $buildInfoPath -Raw | ConvertFrom-Json
if ($buildInfo.version -ne $ExpectedVersion) {
    throw "Payload build-info.json version '$($buildInfo.version)' did not match expected '$ExpectedVersion'"
}

Invoke-MatchPatchCliVersionSmoke $guiExe

if ($GuiSmoke) {
    Invoke-MatchPatchGuiSmoke $guiExe
}

Write-Host "Payload smoke passed: $payload"
