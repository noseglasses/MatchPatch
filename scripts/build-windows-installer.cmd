@echo off
setlocal

if not "%OS%"=="Windows_NT" (
  echo MatchPatch Windows installer builds must run on Windows. >&2
  exit /b 1
)

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~0,2%"=="\\" (
  echo MatchPatch Windows installer builds must run from a native Windows path, not a UNC path. >&2
  echo If Git lives in WSL, run scripts\build-windows-installer-from-wsl.sh from WSL to create a Windows mirror. >&2
  exit /b 1
)

pushd "%~dp0.." || exit /b 1

for /f "usebackq delims=" %%V in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $inProject = $false; foreach ($line in Get-Content -LiteralPath 'pyproject.toml') { if ($line -match '^\[project\]') { $inProject = $true; continue }; if ($line -match '^\[') { $inProject = $false }; if ($inProject -and $line -match '^version\s*=\s*\x22([^\x22]+)\x22') { $matches[1]; exit 0 } }; throw 'project.version not found in pyproject.toml'"`) do set "APP_VERSION=%%V"
if errorlevel 1 goto :fail
if not defined APP_VERSION (
  echo Could not resolve project.version from pyproject.toml. >&2
  goto :fail
)

call scripts\build-windows-payload.cmd
if errorlevel 1 goto :fail

set "ISCC_EXE="
if defined INNO_SETUP_ISCC (
  if exist "%INNO_SETUP_ISCC%" set "ISCC_EXE=%INNO_SETUP_ISCC%"
)

if not defined ISCC_EXE (
  for /f "usebackq delims=" %%I in (`where iscc.exe 2^>nul`) do (
    if not defined ISCC_EXE set "ISCC_EXE=%%I"
  )
)

if not defined ISCC_EXE (
  if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)

if not defined ISCC_EXE (
  if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
)

if not defined ISCC_EXE (
  echo Inno Setup compiler ISCC.exe was not found. >&2
  echo Install Inno Setup 6, add ISCC.exe to PATH, or set INNO_SETUP_ISCC to the full ISCC.exe path. >&2
  goto :fail
)

set "PAYLOAD_DIR=%CD%\build\windows-payload\MatchPatch"
set "OUTPUT_DIR=%CD%\dist\installer"
set "INSTALLER_EXE=%OUTPUT_DIR%\MatchPatch-Setup-%APP_VERSION%.exe"

if not exist "%PAYLOAD_DIR%\MatchPatch.exe" (
  echo Missing payload executable: %PAYLOAD_DIR%\MatchPatch.exe >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\installer-assets\matchpatch.ico" (
  echo Missing payload installer icon: %PAYLOAD_DIR%\installer-assets\matchpatch.ico >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\installer-assets\wizard-logo.bmp" (
  echo Missing payload installer wizard image: %PAYLOAD_DIR%\installer-assets\wizard-logo.bmp >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\installer-assets\wizard-small-logo.bmp" (
  echo Missing payload installer wizard small image: %PAYLOAD_DIR%\installer-assets\wizard-small-logo.bmp >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\docs_html\index.html" (
  echo Missing payload docs: %PAYLOAD_DIR%\docs_html\index.html >&2
  goto :fail
)

if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"
mkdir "%OUTPUT_DIR%"
if errorlevel 1 goto :fail

"%ISCC_EXE%" installer\matchpatch.iss /DAppVersion=%APP_VERSION% "/DSourceDir=%PAYLOAD_DIR%" "/DOutputDir=%OUTPUT_DIR%"
if errorlevel 1 goto :fail

if not exist "%INSTALLER_EXE%" (
  echo Expected installer was not produced: %INSTALLER_EXE% >&2
  goto :fail
)

echo.
echo MatchPatch Windows installer:
echo   %INSTALLER_EXE%

popd
exit /b 0

:fail
set "STATUS=%ERRORLEVEL%"
if "%STATUS%"=="0" set "STATUS=1"
popd
exit /b %STATUS%
