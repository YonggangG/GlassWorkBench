@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo uv was not found. Install uv and reopen your terminal; see README.md.
    exit /b 1
)
uv sync --group dev
if errorlevel 1 exit /b %errorlevel%
uv run python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\GlassWorkbench.spec
if errorlevel 1 exit /b %errorlevel%
echo Portable application: dist\GlassWorkbench\GlassWorkbench.exe
echo Keep the whole GlassWorkbench directory together. Catalogs are external and are not copied.
exit /b 0
