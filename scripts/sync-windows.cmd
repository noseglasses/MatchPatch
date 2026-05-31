@echo off
setlocal

pushd "%~dp0.." || exit /b 1
set "UV_PROJECT_ENVIRONMENT=.venv-windows"
set "UV_LINK_MODE=copy"

uv sync --locked --no-default-groups --group windows %*
set "status=%errorlevel%"

popd
exit /b %status%
