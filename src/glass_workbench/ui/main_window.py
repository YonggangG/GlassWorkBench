from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from glass_workbench import __version__
from .agf import AgfTab
from .app_icon import application_icon
from .filters import filtered_glasses
from .maps import MapsTab
from .screening import ScreeningTab
from .thermal import AirTab, ThermalTab
from .widgets import JobController


STYLE = """
QMainWindow { background: #f3f6fa; }
QWidget { font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 10pt; color: #23364d; }
QPushButton { background: #e5edf6; border: 1px solid #bdcbdb; border-radius: 5px; padding: 6px 10px; }
QPushButton:hover { background: #d2e3f5; }
QPushButton:disabled { color: #8b99a8; background: #edf0f3; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { padding: 4px; border: 1px solid #b9c9d9; border-radius: 3px; background: white; }
QTabWidget::pane { border: 1px solid #ced8e3; background: white; }
QTabBar::tab { padding: 10px 17px; background: #e6edf5; margin-right: 2px; }
QTabBar::tab:selected { background: white; border-top: 3px solid #187c99; }
QGroupBox { font-weight: bold; border: 1px solid #cfdae5; border-radius: 5px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLabel#notice { background: #edf6fa; border-left: 3px solid #187c99; padding: 8px; }
QTableView { background: white; alternate-background-color: #f2f6fa; gridline-color: #e0e7ef; selection-background-color: #c6e4f2; selection-color: #142c43; }
QHeaderView::section { background: #e7eff7; padding: 5px; border: 1px solid #d4dfeb; }
"""


class MainWindow(QMainWindow):
    def __init__(self, auto_load=True):
        super().__init__()
        self.setWindowTitle(f"Glass Workbench {__version__} — CDGM / SCHOTT")
        self.setWindowIcon(application_icon())
        self.resize(1480, 980)
        self.setMinimumSize(1060, 720)
        self.setStyleSheet(STYLE)
        self.catalogs = {}
        from glass_workbench.catalogs.supplemental import supplemental_glasses
        self.supplements = supplemental_glasses()
        self.supplement_controls = {}
        self.closing = False
        self.source_label = QLabel("No catalogs loaded. Load the two official Excel files; only the first sheet is used.")
        self.source_label.setWordWrap(True)
        self.load_button = QPushButton("Load Excel catalogs…")
        self.load_button.clicked.connect(self.choose_files)
        self.discover_button = QPushButton("Find catalogs in current folder")
        self.discover_button.clicked.connect(self.discover)
        self.sources_button = QPushButton("Source / model details")
        self.sources_button.clicked.connect(self.source_details)
        source_bar = QHBoxLayout()
        source_bar.addWidget(self.load_button)
        source_bar.addWidget(self.discover_button)
        source_bar.addWidget(self.sources_button)
        source_bar.addStretch()
        self.help_dialog = None
        self.help_button = QPushButton("Help")
        self.help_button.setToolTip("Open the offline manual (F1)")
        self.help_button.clicked.connect(self.show_help)
        source_bar.addWidget(self.help_button)
        self.help_shortcut = QShortcut(QKeySequence("F1"), self)
        self.help_shortcut.activated.connect(self.show_help)
        self.supplier = QComboBox()
        self.supplier.addItems(["All suppliers", "CDGM", "SCHOTT"] + sorted({g.supplier for g in self.supplements}))
        self.preset = QComboBox()
        self.preset.addItems(["All first-sheet glasses", "H- or N-", "Popular: (CDGM H- ∩ MA) or SCHOTT N-"])
        self.melt = QComboBox()
        self.melt.addItems(["Any melt category", "MA", "A", "B", "C", "D", "NEW"])
        self.melt.setToolTip("Melt category is a CDGM field. Selecting MA alone excludes SCHOTT, which has no such field.")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Glass-name prefix, e.g. H-K or N-BK")
        self.count = QLabel("0 glasses")
        filters = QHBoxLayout()
        for label, widget in [("Supplier", self.supplier), ("Name preset", self.preset), ("Melt category", self.melt)]:
            filters.addWidget(QLabel(label))
            filters.addWidget(widget)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.count)
        self.tabs = QTabWidget()
        self.maps = MapsTab()
        self.thermal = ThermalTab()
        self.air = AirTab()
        self.triplet = ScreeningTab("triplet")
        self.telescope = ScreeningTab("telescope")
        self.agf = AgfTab()
        for widget, title in [(self.maps, "Glass Maps"), (self.thermal, "Glass dn/dT"),
                              (self.air, "Air Index"), (self.triplet, "Cooke / Athermal 1550"),
                              (self.telescope, "Telescope C · d · F"), (self.agf, "AGF Catalogs")]:
            self.tabs.addTab(widget, title)
        center = QWidget()
        layout = QVBoxLayout(center)
        title = QLabel("GLASS WORKBENCH   /   Optical materials & first-order screening")
        title.setStyleSheet("font-size: 17pt; font-weight: 600; color: #14516c; padding: 5px;")
        layout.addWidget(title)
        layout.addLayout(source_bar)
        layout.addWidget(self.source_label)
        layout.addLayout(filters)
        supplemental_bar = QHBoxLayout()
        supplemental_bar.addWidget(QLabel("Supplemental materials:"))
        for glass in self.supplements:
            checkbox = QCheckBox(glass.uid)
            checkbox.setChecked(True)
            checkbox.setToolTip(
                "Independently include this material in the candidate pool; it does not require "
                "the other supplemental material to be selected. "
                "Included independently of H-/N-/MA presets; supplier and name-prefix filters still apply. "
                "Selection permits use, not mandatory inclusion in a combination. "
                "Screening eligibility and ranking still apply: appearance in the retained top results "
                "is not guaranteed.\n" + glass.remarks
            )
            self.supplement_controls[glass.uid] = checkbox
            supplemental_bar.addWidget(checkbox)
        supplemental_bar.addWidget(QLabel("Union with workbook filters • silicon is IR-only • transmission may be unknown"), 1)
        layout.addLayout(supplemental_bar)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(center)
        self.statusBar().showMessage("Offline • source files are never modified • first-order screening is not a lens prescription")
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(250)
        self.filter_timer.timeout.connect(self.apply_filters)
        for combo in [self.supplier, self.preset, self.melt]:
            combo.currentTextChanged.connect(self.apply_filters)
        self.search.textChanged.connect(lambda: self.filter_timer.start())
        self.import_job = JobController(self)
        self.import_job.completed.connect(self.imported)
        self.import_job.failed.connect(self.import_failed)
        self.import_job.busy_changed.connect(self.import_busy)
        for checkbox in self.supplement_controls.values():
            checkbox.toggled.connect(self.apply_filters)
        self.apply_filters()
        if auto_load:
            QTimer.singleShot(100, self.discover)

    @property
    def glasses(self):
        return [g for catalog in self.catalogs.values() for g in catalog.glasses] + self.supplements

    def selected_supplements(self):
        return [uid for uid, checkbox in self.supplement_controls.items() if checkbox.isChecked()]

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select official CDGM / SCHOTT Excel catalogs", str(Path.cwd()), "Excel workbook (*.xlsx)")
        if paths:
            self.load_paths(paths)

    def discover(self):
        from glass_workbench.catalogs.loader import discover_catalogs
        paths = discover_catalogs(Path.cwd())
        if paths:
            self.load_paths(paths)
        else:
            self.source_label.setText("No recognized official workbooks in this folder. Use Load Excel catalogs to select them.")

    def load_paths(self, paths):
        if self.import_job.busy:
            return
        from glass_workbench.catalogs.loader import load_catalog
        self.agf.protect_sources(paths)
        self.source_label.setText("Loading first worksheets in the background…")
        def load(progress, cancelled):
            catalogs, errors = [], []
            for index, path in enumerate(paths):
                if cancelled():
                    break
                try:
                    catalogs.append(load_catalog(path))
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
                progress(index + 1, len(paths), "Loading first sheet")
            return catalogs, errors
        self.import_job.start(load)

    def import_busy(self, busy):
        self.load_button.setEnabled(not busy)
        self.discover_button.setEnabled(not busy)

    def import_failed(self, text):
        self.source_label.setText("Catalog import failed; existing catalog data retained. " + text)

    def imported(self, result):
        if self.closing:
            return
        catalogs, errors = result
        for catalog in catalogs:
            self.catalogs[catalog.supplier] = catalog
        self.agf.update_workbooks(self.catalogs.values())
        summary = "  |  ".join(f"{cat.supplier}: {len(cat.glasses)} • {Path(cat.path).name} / {cat.sheet}" for cat in self.catalogs.values())
        self.source_label.setText(summary or "No catalogs loaded")
        flagged = sum(any("MISMATCH" in warning for warning in g.warnings) for g in self.glasses)
        if flagged:
            self.source_label.setText(self.source_label.text() + f"\nData audit: {flagged} glasses have coefficient/table discrepancies; relevant calculations exclude them by default. See source/model details.")
        if errors:
            self.source_label.setText(self.source_label.text() + "\nImport warnings: " + "; ".join(errors))
        self.apply_filters()

    def provenance(self):
        return {"app_version": __version__, "workbook_first_sheet_only": True,
                "supplemental_sources": [{"uid": g.uid, "urls": g.source_urls, "model": g.dispersion_model,
                                          "data_hash": g.source_hash, "warnings": g.warnings} for g in self.supplements],
                "sources": [{"supplier": c.supplier, "file": c.path, "sheet": c.sheet, "sha256": c.sha256,
                             "glass_count": len(c.glasses), "warnings": c.warnings} for c in self.catalogs.values()],
                "filters": {"supplier": self.supplier.currentText(), "name_preset": self.preset.currentText(),
                            "melt_category": self.melt.currentText(), "name_prefix": self.search.text().strip(),
                            "selected_supplements": self.selected_supplements(),
                            "supplement_logic": "union with name/melt presets; intersect supplier and name prefix"}}

    def apply_filters(self, *_):
        state = dict(supplier=self.supplier.currentText(), preset=self.preset.currentText(),
                     melt=self.melt.currentText(), search=self.search.text().strip(),
                     supplements=self.selected_supplements())
        records = filtered_glasses(self.glasses, **state)
        self.agf.set_global_filters(**state)
        self.count.setText(f"{len(records)} / {len(self.glasses)} glasses")
        metadata = self.provenance()
        for page in [self.maps, self.thermal, self.triplet, self.telescope]:
            page.update_glasses(records, metadata)

    def show_help(self):
        from .help import HelpDialog
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self)
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def source_details(self):
        text = ["Workbook imports read only their first worksheet. HPFS 7980 and silicon use bundled supplemental source data, not the legacy CSV/workbook.",
                "MA is a CDGM melt-frequency field, not a name prefix or a SCHOTT category.",
                "Supplier-native relative prices are not comparable currencies.",
                "Thermal/dispersion extrapolations require explicit permission; see calculation warnings.",
                "Models, references and limitations: README.md and packaged model notes where available."]
        for catalog in self.catalogs.values():
            text.extend(["", f"{catalog.supplier}: {catalog.path}", f"Sheet: {catalog.sheet}", f"SHA256: {catalog.sha256}"])
            text.extend(catalog.warnings)
        for glass in self.supplements:
            text.extend(["", glass.uid, *glass.source_urls, glass.remarks, *glass.warnings])
        from importlib.resources import files
        try:
            text.extend(["", files("glass_workbench.optics").joinpath("model_notes.txt").read_text(encoding="utf-8")])
        except (FileNotFoundError, ModuleNotFoundError):
            text.append("Model notes unavailable; consult the source README.")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Sources and scientific scope")
        dialog.setText("Catalog provenance and model safeguards")
        dialog.setInformativeText("\n".join(text[:5]))
        dialog.setDetailedText("\n".join(text))
        dialog.exec()

    def closeEvent(self, event):
        if not self.closing:
            self.agf.shutdown()
        jobs = [self.import_job, self.thermal.job, self.triplet.job, self.telescope.job, self.agf.job]
        active = [job for job in jobs if job.busy]
        if active:
            self.closing = True
            for job in active:
                job.cancel()
            self.statusBar().showMessage("Cancelling background work before closing…")
            event.ignore()
            QTimer.singleShot(150, self.close)
        else:
            event.accept()
