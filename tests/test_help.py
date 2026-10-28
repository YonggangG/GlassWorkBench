"""Catalog-free offline manual, resource, navigation and safety checks."""
from pathlib import Path
import os
import subprocess
import sys
import tomllib

import pytest
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QTextDocument, QTextTable
from PySide6.QtWidgets import QDialogButtonBox

from glass_workbench.ui import help as help_ui
from glass_workbench.ui.main_window import MainWindow


MANUAL = """# Example manual

[Jump to final section](#last-section)

## Table section

| Name | Value |
| --- | --- |
| Example | 42 |

```text
some_command --offline
# Not a section
```

""" + "A paragraph to scroll past.\n\n" * 80 + "## Last section\n\nEnd of the manual.\n"


def test_canonical_readme_from_unrelated_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("WRONG working-directory manual", encoding="utf-8")
    text = help_ui.load_readme()
    assert text.startswith("# Glass Workbench")
    assert "## Run from source" in text
    assert "WRONG working-directory manual" not in text


def test_packaged_resource_precedes_source(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("# Packaged manual", encoding="utf-8")
    packages = []
    def resource_root(package):
        packages.append(package)
        return tmp_path
    monkeypatch.setattr(help_ui.resources, "files", resource_root)
    monkeypatch.setattr(help_ui, "_source_readme", lambda: pytest.fail("Resource should take precedence"))
    assert help_ui.load_readme() == "# Packaged manual"
    assert packages == ["glass_workbench"]


def test_source_fallback_does_not_use_cwd(monkeypatch, tmp_path):
    monkeypatch.setattr(help_ui.resources, "files", lambda _: tmp_path / "missing-package")
    monkeypatch.chdir(tmp_path)
    assert help_ui.load_readme() == help_ui._source_readme().read_text(encoding="utf-8")


@pytest.mark.parametrize("invalid_text", [False, True])
def test_missing_or_unreadable_documentation_is_graceful(qtbot, monkeypatch, tmp_path, invalid_text):
    monkeypatch.setattr(help_ui.resources, "files", lambda _: tmp_path)
    source = tmp_path / "README.md"
    if invalid_text:
        source.write_bytes(b"\xff\xfe\xff")
    monkeypatch.setattr(help_ui, "_source_readme", lambda: source)
    dialog = help_ui.HelpDialog()
    qtbot.addWidget(dialog)
    assert "Help documentation is unavailable" in dialog.browser.toPlainText()
    assert "Reinstall the complete application bundle" in dialog.browser.toPlainText()
    assert not dialog.sections.isEnabled()
    assert dialog.sections.count() == 0


def test_markdown_format_sections_and_local_anchor(qtbot, monkeypatch):
    monkeypatch.setattr(help_ui, "load_readme", lambda: MANUAL)
    dialog = help_ui.HelpDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    document = dialog.browser.document()
    assert document.begin().blockFormat().headingLevel() == 1
    assert any(isinstance(frame, QTextTable) for frame in document.rootFrame().childFrames())
    assert "some_command --offline" in dialog.browser.toPlainText()
    assert "```" not in dialog.browser.toPlainText()
    assert dialog.sections.count() == 3
    assert dialog.sections.itemData(2) == "last-section"
    assert document.documentMargin() >= 20
    qtbot.waitUntil(lambda: dialog.browser.verticalScrollBar().maximum() > 0)
    dialog.sections.activated.emit(2)
    assert dialog.browser.verticalScrollBar().value() > 0
    dialog.browser.verticalScrollBar().setValue(0)
    dialog.browser.anchorClicked.emit(QUrl("#last-section"))
    assert dialog.browser.verticalScrollBar().value() > 0
    assert dialog.browser.toPlainText().startswith("Example manual")


def test_repeated_heading_anchors_are_unique(qtbot, monkeypatch):
    monkeypatch.setattr(help_ui, "load_readme", lambda: "# Intro\n\n## Repeat\n\n## Repeat\n\n## Repeat-1\n")
    dialog = help_ui.HelpDialog()
    qtbot.addWidget(dialog)
    anchors = [dialog.sections.itemData(i) for i in range(dialog.sections.count())]
    assert len(anchors) == len(set(anchors))


def test_only_activated_http_links_open_externally(qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(help_ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    browser = help_ui.OfflineTextBrowser()
    qtbot.addWidget(browser)
    browser.setMarkdown("![tracking image](https://example.com/tracker.png)\n\n[Reference](https://example.com/docs)")
    browser.show()
    assert not opened
    assert not browser.openLinks()
    assert not browser.openExternalLinks()
    for target in ("https://example.com/tracker.png", "file:///private/image.png", "//example.com/image.png"):
        assert browser.loadResource(QTextDocument.ResourceType.ImageResource, QUrl(target)).isEmpty()
    for target in ("file:///private/file.txt", "javascript:alert(1)", "mailto:test@example.com", "//example.com", "local.md", "#local"):
        browser.anchorClicked.emit(QUrl(target))
    assert not opened
    browser.anchorClicked.emit(QUrl("https://example.com/docs"))
    browser.anchorClicked.emit(QUrl("http://example.com/other"))
    assert opened == ["https://example.com/docs", "http://example.com/other"]


def test_help_button_f1_reuses_owned_resizable_dialog_without_catalogs(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.show()
    assert window.catalogs == {}
    assert window.help_button.text() == "Help"
    assert window.sources_button.text() == "Source / model details"
    qtbot.mouseClick(window.help_button, Qt.MouseButton.LeftButton)
    dialog = window.help_dialog
    assert dialog.parent() is window
    assert dialog.isVisible()
    assert dialog.isSizeGripEnabled()
    dialog.resize(850, 650)
    qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Close), Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keyClick(window, Qt.Key.Key_F1)
    qtbot.waitUntil(dialog.isVisible)
    assert window.help_dialog is dialog
    assert dialog.width() == 850
    window.show_help()
    assert window.help_dialog is dialog
    dialog.close()
    window.close()


def test_smoke_help_requires_smoke_test(monkeypatch, capsys):
    from glass_workbench.__main__ import main
    monkeypatch.setattr(sys, "argv", ["glass-workbench", "--smoke-help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "--smoke-help requires --smoke-test" in capsys.readouterr().err


@pytest.mark.parametrize("help_mode", [False, True])
def test_smoke_screenshot_target_and_clean_exit(tmp_path, help_mode):
    from PySide6.QtGui import QImage
    screenshot = tmp_path / "smoke.png"
    command = [sys.executable, "-m", "glass_workbench", "--no-autoload", "--smoke-test",
               "--screenshot", str(screenshot)]
    if help_mode:
        command.append("--smoke-help")
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    assert result.returncode == 0, result.stdout + result.stderr
    image = QImage(str(screenshot))
    assert not image.isNull()
    # Account for host high-DPI scaling while distinguishing the two target windows.
    expected_ratio = 980 / 760 if help_mode else 1480 / 980
    assert image.width() / image.height() == pytest.approx(expected_ratio, abs=.02)


def test_packaging_maps_canonical_readme():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert included["README.md"] == "glass_workbench/README.md"
    # Evaluate only the declarative spec with no-op PyInstaller build functions.
    captured = {}
    class Analysis:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            self.pure = self.scripts = self.binaries = self.datas = []
    spec = root / "packaging" / "GlassWorkbench.spec"
    namespace = {"SPECPATH": str(spec.parent), "Analysis": Analysis,
                 "PYZ": lambda *a, **k: None, "EXE": lambda *a, **k: None,
                 "COLLECT": lambda *a, **k: None}
    exec(compile(spec.read_text(encoding="utf-8"), str(spec), "exec"), namespace)
    assert (str(root / "README.md"), "glass_workbench") in captured["datas"]
