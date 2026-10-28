"""Offline viewer for the single canonical project README."""
from __future__ import annotations

from importlib import resources
from pathlib import Path
import re

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtGui import QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTextBrowser,
    QVBoxLayout,
)


def _source_readme() -> Path:
    # ui/help.py -> glass_workbench -> src -> repository; never depend on CWD.
    return Path(__file__).resolve().parents[3] / "README.md"


def load_readme() -> str:
    """Prefer the wheel/frozen resource, with an editable/source-tree fallback."""
    try:
        return resources.files("glass_workbench").joinpath("README.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError, ModuleNotFoundError):
        try:
            return _source_readme().read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise OSError(
                "Help documentation is unavailable. The application README.md could not be read. "
                "Reinstall the complete application bundle, or restore README.md in the source checkout."
            ) from exc


class OfflineTextBrowser(QTextBrowser):
    """Render Markdown, but never fetch embedded images or other resources."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self.follow_link)

    def loadResource(self, resource_type, url):
        # Deny all automatic resource access, including local files and remote images.
        return QByteArray()

    def follow_link(self, url: QUrl):
        if not url.scheme() and not url.authority() and not url.path() and url.hasFragment():
            self.scrollToAnchor(url.fragment())
        elif url.isValid() and url.scheme().lower() in {"http", "https"} and url.host():
            # This handler runs only for an activated link, never while rendering.
            QDesktopServices.openUrl(url)


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Glass Workbench Help")
        self.resize(980, 760)
        self.setMinimumSize(540, 400)
        self.setSizeGripEnabled(True)
        self.browser = OfflineTextBrowser(self)
        self.browser.setStyleSheet(
            "QTextBrowser { background: white; color: #23364d; "
            "font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 11pt; "
            "border: 1px solid #ced8e3; }"
        )
        self.browser.document().setDocumentMargin(24)
        self.browser.document().setDefaultStyleSheet(
            "h1, h2, h3 { color: #14516c; } "
            "a { color: #146a94; } "
            "pre, code { font-family: Consolas, monospace; background-color: #f2f6fa; } "
            "th { background-color: #e7eff7; } td, th { padding: 6px; }"
        )
        self.sections = QComboBox(self)
        self.sections.setAccessibleName("Help section")
        self.sections.setMinimumContentsLength(20)
        self.sections.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sections.activated.connect(self.navigate_section)
        section_label = QLabel("Go to section:")
        section_label.setBuddy(self.sections)
        navigation = QHBoxLayout()
        navigation.addWidget(section_label)
        navigation.addWidget(self.sections, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(navigation)
        layout.addWidget(self.browser, 1)
        layout.addWidget(QLabel("Offline manual • Web reference links open in your browser only when activated."))
        layout.addWidget(self.buttons)
        try:
            self.browser.setMarkdown(load_readme())
        except OSError as exc:
            self.browser.setPlainText(str(exc))
        self._index_sections()

    def _index_sections(self):
        """Add stable GitHub-style anchors to rendered headings, not code fences."""
        self.sections.clear()
        used = set()
        block = self.browser.document().begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level:
                text = block.text()
                base = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-") or "section"
                anchor = base
                suffix = 1
                while anchor in used:
                    anchor = f"{base}-{suffix}"
                    suffix += 1
                used.add(anchor)
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                char_format = QTextCharFormat()
                char_format.setAnchor(True)
                char_format.setAnchorNames([anchor])
                cursor.mergeCharFormat(char_format)
                self.sections.addItem("  " * (level - 1) + text, anchor)
            block = block.next()
        self.sections.setEnabled(self.sections.count() > 0)
        self.browser.moveCursor(QTextCursor.MoveOperation.Start)

    def navigate_section(self, index):
        anchor = self.sections.itemData(index)
        if anchor:
            self.browser.scrollToAnchor(anchor)
