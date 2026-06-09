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

function Invoke-SetupProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $LogPath -PathType Leaf) {
            Write-Host "$FailureMessage log tail:"
            Get-Content -LiteralPath $LogPath -Tail 80 | Write-Host
        }
        throw "$FailureMessage with exit code $($process.ExitCode)"
    }
}

$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$installLog = Join-Path $env:TEMP ("MatchPatch-install-" + [guid]::NewGuid().ToString("N") + ".log")
$uninstallLog = Join-Path $env:TEMP ("MatchPatch-uninstall-" + [guid]::NewGuid().ToString("N") + ".log")
$installArgs = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/LOG=$installLog",
    "/DIR=$InstallDir"
)

Invoke-SetupProcess -Path $installer -Arguments $installArgs -FailureMessage "Installer failed" -LogPath $installLog

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

$uninstallArgs = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/LOG=$uninstallLog"
)
Invoke-SetupProcess -Path $uninstaller -Arguments $uninstallArgs -FailureMessage "Uninstaller failed" -LogPath $uninstallLog

Start-Sleep -Seconds 2
if (Test-Path -LiteralPath $InstallDir) {
    $leftovers = @(Get-ChildItem -LiteralPath $InstallDir -Force)
    $unexpected = @($leftovers | Where-Object { $_.Name -notmatch "^unins\d+\.dat$|^unins\d+\.msg$|^unins\d+\.log$" })
    if ($unexpected.Count -gt 0) {
        throw "Install directory contains unexpected leftovers after uninstall: $($unexpected.FullName -join ', ')"
    }
}

Write-Host "Installed smoke passed: $installer"
