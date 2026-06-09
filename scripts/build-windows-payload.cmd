@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~0,2%"=="\\" (
  echo MatchPatch Windows payload builds must run from a native Windows path, not a UNC path. >&2
  echo If Git lives in WSL, run scripts\build-windows-installer-from-wsl.sh from WSL to create a Windows mirror. >&2
  exit /b 1
)

pushd "%~dp0.." || exit /b 1

set "UV_PROJECT_ENVIRONMENT=.venv-windows"
set "UV_LINK_MODE=copy"
set "PAYLOAD_DIR=build\windows-payload\MatchPatch"

call scripts\sync-windows.cmd --group docs --group installer --extra gui
if errorlevel 1 goto :fail

if exist docs_html rmdir /s /q docs_html
if exist build\windows-payload rmdir /s /q build\windows-payload
if exist build\pyinstaller rmdir /s /q build\pyinstaller

uv run --frozen --no-default-groups --group docs sphinx-build -W --keep-going -b html docs docs_html
if errorlevel 1 goto :fail

uv run --frozen --no-default-groups --group windows --group installer --extra gui pyinstaller installer\pyinstaller\matchpatch-gui.spec
if errorlevel 1 goto :fail

uv run --frozen --no-default-groups --group windows --group installer --extra gui pyinstaller installer\pyinstaller\matchpatch-cli.spec
if errorlevel 1 goto :fail

if not exist "%PAYLOAD_DIR%\MatchPatch.exe" (
  echo Missing payload executable: %PAYLOAD_DIR%\MatchPatch.exe >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\matchpatch.exe" (
  echo Missing payload executable: %PAYLOAD_DIR%\matchpatch.exe >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\docs_html\index.html" (
  echo Missing payload docs: %PAYLOAD_DIR%\docs_html\index.html >&2
  goto :fail
)
if not exist "%PAYLOAD_DIR%\build-info.json" (
  echo Missing payload manifest: %PAYLOAD_DIR%\build-info.json >&2
  goto :fail
)

echo.
echo MatchPatch Windows payload:
echo   %CD%\%PAYLOAD_DIR%

popd
exit /b 0

:fail
set "STATUS=%ERRORLEVEL%"
if "%STATUS%"=="0" set "STATUS=1"
popd
exit /b %STATUS%
