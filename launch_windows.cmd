@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo uv was not found. Install uv and reopen your terminal; see README.md.
    exit /b 1
)
uv run python -m glass_workbench %*
exit /b %errorlevel%
