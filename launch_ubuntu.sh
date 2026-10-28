#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'uv was not found. Install uv and reopen your terminal; see README.md.' >&2
    exit 1
fi
exec uv run python -m glass_workbench "$@"
