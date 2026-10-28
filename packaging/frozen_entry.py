"""PyInstaller entry point; keep package imports absolute."""

import os
from pathlib import Path
import sys

# A portable build discovers external catalogs alongside its executable, not
# inside PyInstaller's private _internal directory or the caller's directory.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)

from glass_workbench.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
