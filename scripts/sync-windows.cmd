@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~0,2%"=="\\" (
  echo MatchPatch native Windows environments cannot be synchronized from a UNC path. >&2
  echo If Git lives in WSL, run scripts/sync-windows-from-wsl.sh from WSL to create >&2
  echo a Windows runtime mirror, for example C:\src\MatchPatch-windows. >&2
  exit /b 1
)

pushd "%~dp0.." || exit /b 1
set "UV_PROJECT_ENVIRONMENT=.venv-windows"
set "UV_LINK_MODE=copy"

uv sync --locked --no-default-groups --group windows %*
set "status=%errorlevel%"

popd
exit /b %status%
