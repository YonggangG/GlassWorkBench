"""Offline site-icon resources and source/frozen configuration."""
from hashlib import sha256
from importlib import resources
from pathlib import Path
import struct
import tomllib

from glass_workbench.ui import app_icon
from glass_workbench.ui.main_window import MainWindow


def test_original_assets_and_desktop_ico():
    assets = resources.files("glass_workbench").joinpath("assets")
    assert sha256(assets.joinpath("aurora.ico").read_bytes()).hexdigest() == "27597b34ad4c4cdea4e5f5b54b141fdb495ba9fd27953fd98ee28ab4467ce4f3"
    assert sha256(assets.joinpath("aurora-touch.png").read_bytes()).hexdigest() == "57ddd0bbef4c263e9eb2bb3cfabb32d77ed021940f0d5c0f98aee3061c3664a9"
    ico = assets.joinpath("app.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    assert (reserved, kind) == (0, 1)
    sizes = {ico[6 + 16*i] or 256 for i in range(count)}
    assert {16, 32, 48, 64, 128, 180} <= sizes


def test_icons_load_from_unrelated_directory(qtbot, qapp, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    icon = app_icon.application_icon()
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()
    original = qapp.windowIcon()
    try:
        app_icon.configure_application_icon(qapp)
        assert not qapp.windowIcon().isNull()
        window = MainWindow(auto_load=False)
        qtbot.addWidget(window)
        assert not window.windowIcon().isNull()
        window.close()
    finally:
        qapp.setWindowIcon(original)


def test_missing_icon_is_graceful(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(app_icon.resources, "files", lambda _: tmp_path)
    assert app_icon.application_icon().isNull()


def test_icon_packaging_configuration():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]["src/glass_workbench/assets"] == "glass_workbench/assets"
    captured = {}
    class Analysis:
        def __init__(self, *args, **kwargs):
            captured["datas"] = kwargs["datas"]
            self.pure = self.scripts = self.binaries = self.datas = []
    def executable(*args, **kwargs):
        captured["icon"] = kwargs["icon"]
    spec = root / "packaging/GlassWorkbench.spec"
    scope = {"SPECPATH": str(spec.parent), "Analysis": Analysis,
             "PYZ": lambda *a, **kw: None, "EXE": executable,
             "COLLECT": lambda *a, **kw: None}
    exec(compile(spec.read_text(encoding="utf-8"), str(spec), "exec"), scope)
    assert Path(captured["icon"]) == root / "src/glass_workbench/assets/app.ico"
    assert (str(root / "src/glass_workbench/assets"), "glass_workbench/assets") in captured["datas"]
