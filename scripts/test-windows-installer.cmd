@echo off
setlocal

if not "%OS%"=="Windows_NT" (
  echo MatchPatch Windows installer tests must run on Windows. >&2
  exit /b 1
)

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~0,2%"=="\\" (
  echo MatchPatch Windows installer tests must run from a native Windows path, not a UNC path. >&2
  echo If Git lives in WSL, run scripts\test-windows-installer-from-wsl.sh from WSL to create a Windows mirror. >&2
  exit /b 1
)

set "REUSE_ARTIFACT=0"
set "INSTALLER_EXE="
set "GUI_SMOKE="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--reuse-artifact" (
  set "REUSE_ARTIFACT=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--installer" (
  if "%~2"=="" (
    echo Missing path after --installer. >&2
    exit /b 1
  )
  set "INSTALLER_EXE=%~2"
  set "REUSE_ARTIFACT=1"
  shift
  shift
  goto :parse_args
)
if /i "%~1"=="--gui-smoke" (
  set "GUI_SMOKE=-GuiSmoke"
  shift
  goto :parse_args
)
echo Unknown argument: %~1 >&2
echo Usage: scripts\test-windows-installer.cmd [--reuse-artifact] [--installer path] [--gui-smoke] >&2
exit /b 1

:args_done
pushd "%~dp0.." || exit /b 1

for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $inProject = $false; foreach ($line in Get-Content -LiteralPath 'pyproject.toml') { if ($line -match '^\[project\]') { $inProject = $true; continue }; if ($line -match '^\[') { $inProject = $false }; if ($inProject -and $line -match '^version\s*=\s*\x22([^\x22]+)\x22') { $matches[1]; exit 0 } }; throw 'project.version not found in pyproject.toml'"`) do set "APP_VERSION=%%V"
if errorlevel 1 goto :fail
if not defined APP_VERSION (
  echo Could not resolve project.version from pyproject.toml. >&2
  goto :fail
)

if not defined INSTALLER_EXE set "INSTALLER_EXE=%CD%\dist\installer\MatchPatch-Setup-%APP_VERSION%.exe"

if "%REUSE_ARTIFACT%"=="0" (
  call scripts\build-windows-installer.cmd
  if errorlevel 1 goto :fail
) else (
  echo Reusing installer artifact:
  echo   %INSTALLER_EXE%
)

set "PAYLOAD_DIR=%CD%\build\windows-payload\MatchPatch"
if not exist "%PAYLOAD_DIR%" (
  echo Missing payload directory for smoke tests: %PAYLOAD_DIR% >&2
  echo Run without --reuse-artifact to rebuild the payload and installer. >&2
  goto :fail
)
if not exist "%INSTALLER_EXE%" (
  echo Missing installer artifact: %INSTALLER_EXE% >&2
  goto :fail
)

powershell -NoProfile -ExecutionPolicy Bypass -File installer\smoke\smoke_payload.ps1 -PayloadDir "%PAYLOAD_DIR%" -ExpectedVersion "%APP_VERSION%" %GUI_SMOKE%
if errorlevel 1 goto :fail

powershell -NoProfile -ExecutionPolicy Bypass -File installer\smoke\smoke_installed.ps1 -InstallerPath "%INSTALLER_EXE%" -ExpectedVersion "%APP_VERSION%" %GUI_SMOKE%
if errorlevel 1 goto :fail

echo.
echo MatchPatch Windows installer test bench passed:
echo   %INSTALLER_EXE%

popd
exit /b 0

:fail
set "STATUS=%ERRORLEVEL%"
if "%STATUS%"=="0" set "STATUS=1"
popd
exit /b %STATUS%
