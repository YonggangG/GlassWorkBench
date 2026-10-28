# Build on the target OS. No source catalogs or other workspace data are bundled.
from pathlib import Path

project_root = Path(SPECPATH).resolve().parent

analysis = Analysis(
    [str(project_root / "packaging" / "frozen_entry.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(project_root / "src/glass_workbench/optics/model_notes.txt"), "glass_workbench/optics"),
        (str(project_root / "README.md"), "glass_workbench"),
        (str(project_root / "src/glass_workbench/assets"), "glass_workbench/assets"),
    ],
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["QtAgg"]}},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="GlassWorkbench",
    icon=str(project_root / "src/glass_workbench/assets/app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="GlassWorkbench",
)
