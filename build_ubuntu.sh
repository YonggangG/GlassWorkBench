#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ "$(uname -s)" != Linux ]]; then
    printf '%s\n' 'Run this build on Linux itself; PyInstaller does not cross-compile Ubuntu binaries.' >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'uv was not found. Install uv and reopen your terminal; see README.md.' >&2
    exit 1
fi
uv sync --group dev
uv run python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/GlassWorkbench.spec
printf '%s\n' 'Portable application: dist/GlassWorkbench/GlassWorkbench' \
    'Keep the whole GlassWorkbench directory together. Catalogs are external and are not copied.'
