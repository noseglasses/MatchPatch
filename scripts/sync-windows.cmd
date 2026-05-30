@echo off
setlocal

cd /d "%~dp0.."
set "UV_PROJECT_ENVIRONMENT=.venv-windows"
set "UV_LINK_MODE=copy"

uv sync --locked --no-default-groups --group windows %*
