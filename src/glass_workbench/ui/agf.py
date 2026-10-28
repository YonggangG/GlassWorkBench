"""Catalog-management UI; all AGF interpretation and serialization live in catalogs."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
    QTabWidget, QVBoxLayout, QWidget,
)

from glass_workbench.catalogs.agf import load_agf
from glass_workbench.catalogs.agf_export import (
    DEFAULT_CATALOG_COMMENT, allocate_export_items, build_export, glass_to_agf,
    material_comment, write_export,
)
from .filters import filtered_glasses
from .widgets import JobController, RecordsModel, json_default


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=json_default)


class BasketModel(RecordsModel):
    """Export-only presentation; source names and other tables stay untouched."""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and self.columns[index.column()] == "export_name":
            row = self.rows[index.row()]
            if row["export_name"] != row["original_name"]:
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QColor("#b71c1c")
                if role == Qt.ItemDataRole.ToolTipRole:
                    return f"{row['original_name']} → {row['export_name']} (output only; source unchanged)"
        return super().data(index, role)


class BasketNameDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.data(Qt.ItemDataRole.ForegroundRole) is not None:
            # Native styles normally replace ForegroundRole for selected rows.
            highlight = option.palette.color(QPalette.ColorRole.Highlight)
            red = QColor("#ffb4ab" if highlight.lightness() < 150 else "#b71c1c")
            option.palette.setColor(QPalette.ColorRole.HighlightedText, red)

    def paint(self, painter, option, index):
        color = index.data(Qt.ItemDataRole.ForegroundRole)
        if color is None:
            return super().paint(painter, option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        style = styled.widget.style() if styled.widget else QApplication.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, styled, styled.widget)
        styled.text = ""
        # Draw native background/focus normally, then paint alias text ourselves.
        # QStyleSheetStyle can replace even HighlightedText during native painting.
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        if styled.state & QStyle.StateFlag.State_Selected:
            # Windows' native item highlight can ignore the stylesheet palette.
            # Use its application highlight for readable red on the native blue.
            native_highlight = QApplication.palette().color(QPalette.ColorRole.Highlight)
            color = QColor("#ffb4ab" if native_highlight.lightness() < 150 else "#b71c1c")
        painter.save()
        painter.setClipRect(styled.rect)
        painter.setFont(styled.font)
        painter.setPen(color)
        text_rect.adjust(3, 0, -3, 0)
        text = styled.fontMetrics.elidedText(text, styled.textElideMode, text_rect.width())
        painter.drawText(text_rect, int(styled.displayAlignment), text)
        painter.restore()


class CommentDialog(QDialog):
    """Edit a draft only; None preserves original records, empty explicitly clears."""

    def __init__(self, title, original, override, parent=None, *, allow_reset=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 520)
        self.original_text = original
        self.comment_value = override
        self.original = QPlainTextEdit()
        self.original.setReadOnly(True)
        self.original.setPlainText(original)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(original if override is None else override)
        self.editor.textChanged.connect(self._edited)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.reset_button = None
        if allow_reset:
            self.reset_button = self.buttons.addButton("Reset to original", QDialogButtonBox.ButtonRole.ResetRole)
            self.reset_button.clicked.connect(self.reset_original)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Original glass GC comment (read-only)" if allow_reset else "Loaded source catalog headers (read-only)"))
        layout.addWidget(self.original, 1)
        layout.addWidget(QLabel("Effective output glass comment" if allow_reset else "New combined catalog CC comment"))
        layout.addWidget(self.editor, 1)
        hint = QLabel("Output only; source files remain unchanged. Empty text removes output comment records. "
                      "Changes take effect only after Save, then require a new export preview.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.buttons)

    def _edited(self):
        self.comment_value = self.editor.toPlainText()

    def reset_original(self):
        self.editor.setPlainText(self.original_text)
        self.comment_value = None


def _table(parent, model_type=RecordsModel):
    model = model_type(parent)
    view = QTableView()
    view.setModel(model)
    view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
    view.horizontalHeader().setStretchLastSection(True)
    return model, view


class AgfTab(QWidget):
    """Independent source snapshots and identity-keyed, persistent export basket."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.materials = {}
        self.sources = {}
        self.material_sources = {}
        self.documents = {}
        self.basket = {}
        self.protected_paths = set()
        self.selected_ids = set()
        self.preview = None
        self.catalog_comment = DEFAULT_CATALOG_COMMENT
        self.generation = 0
        self.closing = False
        self._resetting = False
        self._workbook_sources = set()
        self.workbook_glasses = {}  # Original Glass snapshots, not lossy AGF conversions.
        self.source_suppliers = {}  # Imported source -> (supplier, assignment basis).
        self._current_workbook_matches = {}
        self.filter_metadata = {}  # Inspection only; never modify/export AGF records.
        self._filter_glasses = {}
        self._global_filters = {}
        self._global_ids = set()

        self.load_button = QPushButton("Load AGF files…")
        self.cancel_button = QPushButton("Cancel import")
        self.cancel_button.setEnabled(False)
        self.encoding = QComboBox()
        self.encoding.addItem("Detect encoding (strict)", None)
        for label, value in [("Windows-1252 override", "cp1252"), ("GB18030 override", "gb18030"),
                             ("UTF-8 override", "utf-8"), ("UTF-16 override", "utf-16")]:
            self.encoding.addItem(label, value)
        self.encoding.setToolTip("Explicit override for legacy text. Decoding failures are never replaced with lossy characters.")
        self.source_filter = QComboBox()
        self.source_filter.addItem("All sources", None)
        self.source_filter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source_filter.setMinimumContentsLength(26)
        self.source_filter.setMaximumWidth(480)
        self.source_supplier = QComboBox()
        self.source_supplier.addItems(["Unknown", "CDGM", "SCHOTT", "Corning", "Infrared"])
        self.source_supplier.setEnabled(False)
        self.source_supplier.setToolTip("Select one imported AGF source at left to assign informational supplier metadata. Imported AGF entries bypass global filters; this does not change AGF records.")
        self.supplier_basis = QLabel("Select an AGF source to assign informational supplier metadata.")
        self.supplier_basis.setWordWrap(True)
        self.formula_filter = QComboBox()
        self.formula_filter.addItem("All formulas", None)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Local material-name / source search")
        self.status = QLabel("Load explicit AGF files or load Excel workbooks above. No AGF directories are scanned.")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(56)
        self.selection_label = QLabel("0 selected")
        self.selection_label.setWordWrap(True)
        self.clear_selection_button = QPushButton("Clear selection")
        self.add_button = QPushButton("Add selected to export basket")
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Remove selected glasses from the export basket")
        self.rename_button = QPushButton("Rename…")
        self.rename_button.setToolTip("Rename the selected glass for export only")
        self.glass_comment_button = QPushButton("Comment…")
        self.glass_comment_button.setToolTip("View and edit the selected glass comment")
        self.glass_comment_button.setEnabled(False)
        self.catalog_comment_button = QPushButton("Export catalog comment…")
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Clear the entire export basket")
        self.basket_label = QLabel("Export basket: 0")
        self.acknowledge = QCheckBox("Acknowledge generated-material conversion warnings / limitations")
        self.preserve_invalid = QCheckBox("Preserve original records with unresolved diagnostics (archival; NOT validated for OpticStudio)")
        self.acknowledge.setChecked(False)
        self.preserve_invalid.setChecked(False)
        self.validate_button = QPushButton("Validate / Preview export")
        self.export_button = QPushButton("Export new AGF…")
        self.export_button.setEnabled(False)
        self.source_model, self.source_view = _table(self)
        self.basket_model, self.basket_view = _table(self, BasketModel)
        self.basket_view.setItemDelegate(BasketNameDelegate(self.basket_view))
        for view in (self.source_view, self.basket_view):
            view.setMinimumHeight(140)
        self.details = QPlainTextEdit()
        self.raw = QPlainTextEdit()
        self.preview_text = QPlainTextEdit()
        self.diagnostics = QPlainTextEdit()
        for editor in (self.details, self.raw, self.preview_text, self.diagnostics):
            editor.setReadOnly(True)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setMinimumHeight(140)
        for editor, title in [(self.details, "Interpreted / provenance"), (self.raw, "Original / generated records"),
                              (self.preview_text, "Exact export text"), (self.diagnostics, "Validation / manifest")]:
            self.detail_tabs.addTab(editor, title)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self.scroll_area.setWidget(body)
        outer_layout.addWidget(self.scroll_area)
        layout = QVBoxLayout(body)
        notice = QLabel("Global filters apply only to Excel-derived entries; imported AGF entries bypass all global filters. "
                        "Local source / formula / search filters apply to both. Existing export basket entries are never filtered or removed. "
                        "Imports do not enter calculation tabs. Workbook reloads retain original snapshots. "
                        "Imported supplier and workbook-matched melt metadata are informational only; AGF numeric melt codes are not Excel MA categories.")
        notice.setWordWrap(True)
        notice.setObjectName("notice")
        layout.addWidget(notice)
        load_bar = QHBoxLayout()
        for widget in (self.load_button, self.encoding, self.cancel_button):
            load_bar.addWidget(widget)
        load_bar.addStretch()
        layout.addLayout(load_bar)
        filters = QHBoxLayout()
        for widget in (self.source_filter, self.formula_filter, self.search):
            filters.addWidget(widget)
        layout.addLayout(filters)
        supplier_bar = QHBoxLayout()
        supplier_bar.addWidget(QLabel("Selected AGF source supplier (informational only):"))
        supplier_bar.addWidget(self.source_supplier)
        supplier_bar.addWidget(self.supplier_basis, 1)
        layout.addLayout(supplier_bar)
        layout.addWidget(self.status)
        tables = QSplitter(Qt.Orientation.Horizontal)
        browser = QWidget()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(self.selection_label)
        browser_bar = QHBoxLayout()
        for widget in (self.clear_selection_button, self.add_button):
            browser_bar.addWidget(widget)
        browser_layout.addLayout(browser_bar)
        browser_layout.addWidget(self.source_view)
        basket_panel = QWidget()
        basket_layout = QVBoxLayout(basket_panel)
        basket_layout.setContentsMargins(0, 0, 0, 0)
        basket_layout.addWidget(self.basket_label)
        basket_bar = QHBoxLayout()
        for widget in (self.rename_button, self.glass_comment_button, self.remove_button, self.clear_button):
            basket_bar.addWidget(widget)
        basket_layout.addLayout(basket_bar)
        basket_layout.addWidget(self.basket_view)
        tables.addWidget(browser)
        tables.addWidget(basket_panel)
        tables.setSizes([650, 550])
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        splitter.setMinimumHeight(365)
        splitter.addWidget(tables)
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([280, 210])
        layout.addWidget(splitter, 1)
        layout.addWidget(self.acknowledge)
        layout.addWidget(self.preserve_invalid)
        export_bar = QHBoxLayout()
        export_bar.addWidget(self.validate_button)
        export_bar.addWidget(self.export_button)
        export_bar.addWidget(self.catalog_comment_button)
        export_bar.addStretch()
        layout.addLayout(export_bar)

        self.job = JobController(self)
        self.job.completed.connect(self.imported)
        self.job.failed.connect(self.import_failed)
        self.job.busy_changed.connect(self.busy_changed)
        self.job.progress.connect(self.import_progress)
        self.load_button.clicked.connect(self.choose_files)
        self.cancel_button.clicked.connect(self.cancel_import)
        self.source_filter.currentIndexChanged.connect(self.refresh_sources)
        self.source_supplier.currentTextChanged.connect(self.assign_source_supplier)
        self.source_supplier.activated.connect(lambda _: self.assign_source_supplier(self.source_supplier.currentText()))
        self.formula_filter.currentIndexChanged.connect(self.refresh_sources)
        self.search.textChanged.connect(self.refresh_sources)
        self.source_view.selectionModel().selectionChanged.connect(self.source_selection_changed)
        self.basket_view.selectionModel().selectionChanged.connect(self.inspect_basket)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.add_button.clicked.connect(self.add_selected)
        self.remove_button.clicked.connect(self.remove_selected)
        self.rename_button.clicked.connect(self.rename_selected)
        self.glass_comment_button.clicked.connect(self.edit_glass_comment)
        self.catalog_comment_button.clicked.connect(self.edit_catalog_comment)
        self.clear_button.clicked.connect(self.clear_basket)
        self.acknowledge.toggled.connect(self.invalidate_preview)
        self.preserve_invalid.toggled.connect(self.invalidate_preview)
        self.validate_button.clicked.connect(self.validate_export)
        self.export_button.clicked.connect(self.export_dialog)

    def protect_sources(self, paths):
        # Never forget old, unselected, failed-import or superseded source paths.
        self.protected_paths.update(str(Path(path).resolve()) for path in paths if path)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Load AGF catalogs", str(Path.cwd()), "AGF catalogs (*.agf *.AGF);;All files (*)")
        if paths:
            self.load_paths(paths)

    def load_paths(self, paths):
        if self.job.busy or self.closing:
            return False
        paths = tuple(str(path) for path in paths)
        self.protect_sources(paths)
        self.generation += 1
        generation = self.generation
        encoding = self.encoding.currentData()
        self.status.setText("Loading AGF files in the background…")

        def load(progress, cancelled):
            documents, errors = [], []
            for index, path in enumerate(paths):
                if cancelled():
                    break
                try:
                    documents.append(load_agf(path, encoding=encoding))
                except Exception as exc:
                    errors.append(f"{path}: {type(exc).__name__}: {exc}")
                progress(index + 1, len(paths), "Loading AGF catalogs")
            return generation, documents, errors

        return self.job.start(load)

    def cancel_import(self):
        self.generation += 1
        self.job.cancel()
        self.status.setText("Import cancelled; pending results discarded. Previously loaded snapshots retained.")

    def shutdown(self):
        self.closing = True
        self.cancel_import()

    def busy_changed(self, busy):
        self.load_button.setEnabled(not busy and not self.closing)
        self.encoding.setEnabled(not busy and not self.closing)
        self.cancel_button.setEnabled(busy and not self.closing)

    def import_progress(self, current, total, text):
        if not self.closing and self.job.worker and not self.job.worker.stop.is_set():
            self.status.setText(f"{text} ({current}/{total})")

    def import_failed(self, text):
        if not self.closing:
            self.status.setText("AGF import failed; existing sources retained. " + text)

    def imported(self, result):
        generation, documents, errors = result
        if self.closing or generation != self.generation:
            return
        for document in documents:
            key = (str(document.path), document.sha256)
            self.documents[key] = document
            self.protect_sources([document.path])
            label = f"AGF · {Path(document.path).name} · {document.sha256[:10]} · {document.path}"
            source = _json(("agf", *key))
            stem = Path(document.path).stem.upper()
            supplier = stem if stem in ("CDGM", "SCHOTT") else "Unknown"
            self.source_suppliers.setdefault(source, (supplier, "filename-based" if supplier != "Unknown" else "unassigned"))
            self.register_source(source, label, document.materials)
        self.rebuild_filter_metadata()
        self.refresh_filters()
        messages = [f"{len(documents)} AGF files loaded; {len(errors)} failed. Existing sources and basket retained."]
        messages.extend(errors)
        for document in documents:
            messages.extend(f"{Path(document.path).name}: {d.severity} / {d.code}: {d.message}" for d in document.diagnostics)
        self.diagnostics.setPlainText("Import report\n\n" + "\n".join(messages))
        diagnostic_count = sum(len(document.diagnostics) for document in documents)
        summary = (f"{len(documents)} AGF files loaded; {len(errors)} failed; {diagnostic_count} source diagnostics. "
                   f"{sum(len(d.materials) for d in documents)} AGF material blocks imported. Full report: Validation / manifest tab.")
        if errors:
            summary += "\nFirst failure: " + errors[0][:200]
        self.status.setText(summary)
        if errors or diagnostic_count:
            self.detail_tabs.setCurrentWidget(self.diagnostics)

    def register_source(self, key, label, materials):
        self.sources[key] = label
        for material in materials:
            self.materials[material.identity] = material
            self.material_sources[material.identity] = key

    def update_workbooks(self, catalogs):
        """Receive ALL current catalogs; retain historical originals only as snapshots."""
        self._current_workbook_matches = {}
        for catalog in catalogs:
            self.protect_sources([catalog.path, *(g.source_file for g in catalog.glasses)])
            for glass in catalog.glasses:
                match = (glass, {"source_file": catalog.path, "source_sha256": catalog.sha256,
                                 "source_sheet": catalog.sheet, "source_row": glass.source_row})
                self._current_workbook_matches.setdefault((glass.supplier, glass.name), []).append(match)
            key = ("workbook", str(catalog.path), catalog.sha256, catalog.sheet)
            if key in self._workbook_sources:
                continue
            materials = tuple(glass_to_agf(glass) for glass in catalog.glasses)
            self.workbook_glasses.update((material.identity, glass) for material, glass in zip(materials, catalog.glasses))
            label = f"Excel · {catalog.supplier} · {Path(catalog.path).name} / {catalog.sheet} · {catalog.sha256[:10]}"
            self.register_source(_json(key), label, materials)
            self._workbook_sources.add(key)
        self.rebuild_filter_metadata()
        self.refresh_filters()

    def rebuild_filter_metadata(self):
        """Keep workbook-category enrichment outside original AGF material objects."""
        self._filter_glasses = dict(self.workbook_glasses)
        self.filter_metadata = {}
        for identity, material in self.materials.items():
            if identity in self.workbook_glasses:
                glass = self.workbook_glasses[identity]
                self.filter_metadata[identity] = {"supplier": glass.supplier, "supplier_basis": "original workbook snapshot",
                    "melt_category": glass.melt_frequency or None, "workbook_match": {
                        "source_file": glass.source_file, "source_sha256": glass.source_hash,
                        "source_sheet": glass.source_sheet, "source_row": glass.source_row}}
                continue
            supplier, basis = self.source_suppliers.get(self.material_sources[identity], ("Unknown", "unassigned"))
            matches = self._current_workbook_matches.get((supplier, material.name), []) if supplier != "Unknown" else []
            unique = matches[0] if len(matches) == 1 else None
            melt = unique[0].melt_frequency if unique else ""
            self._filter_glasses[identity] = SimpleNamespace(name=material.name, supplier=supplier,
                                                           melt_frequency=melt, supplemental=False)
            self.filter_metadata[identity] = {"supplier": supplier, "supplier_basis": basis,
                "melt_category": melt or None, "exact_name_match_count": len(matches),
                "workbook_match": unique[1] if unique else None,
                "scope": "Informational only; imported AGF entries bypass all global filters. Numeric AGF melt codes are not Excel categories. Original records unchanged."}

    def set_global_filters(self, **state):
        self._global_filters = dict(state)
        self.refresh_sources()

    def globally_eligible_ids(self):
        # Global controls apply to original workbook snapshots, never imported AGF.
        return (self.materials.keys() - self.workbook_glasses.keys()) | {
            identity for identity, glass in self.workbook_glasses.items()
            if filtered_glasses((glass,), **self._global_filters)}

    def source_label(self, key):
        label = self.sources[key]
        if key in self.source_suppliers:
            supplier, basis = self.source_suppliers[key]
            label += f" · {supplier} ({basis})"
        return label

    def sync_source_supplier(self):
        key = self.source_filter.currentData()
        assignment = self.source_suppliers.get(key)
        self.source_supplier.blockSignals(True)
        self.source_supplier.setEnabled(assignment is not None)
        self.source_supplier.setCurrentText(assignment[0] if assignment else "Unknown")
        self.source_supplier.blockSignals(False)
        self.supplier_basis.setText(f"{assignment[0]} — {assignment[1]}; informational only, no global-filter impact."
                                   if assignment else "Select an AGF source to assign informational supplier metadata.")

    def assign_source_supplier(self, supplier):
        key = self.source_filter.currentData()
        if key not in self.source_suppliers or supplier not in ("Unknown", "CDGM", "SCHOTT", "Corning", "Infrared"):
            return
        self.source_suppliers[key] = (supplier, "explicit source assignment")
        self.rebuild_filter_metadata()
        self.refresh_filters()

    def refresh_filters(self):
        source = self.source_filter.currentData()
        formula = self.formula_filter.currentData()
        for combo in (self.source_filter, self.formula_filter):
            combo.blockSignals(True)
            combo.clear()
        self.source_filter.addItem("All sources", None)
        for key in self.sources:
            self.source_filter.addItem(self.source_label(key), key)
        self.formula_filter.addItem("All formulas", None)
        formulas = {m.formula: m.properties.get("formula_label", "Unknown / locally unevaluated") for m in self.materials.values()}
        for number, label in sorted(formulas.items(), key=lambda pair: str(pair[0])):
            # A distinct sentinel keeps missing-formula records locally filterable.
            self.formula_filter.addItem(f"{number}: {label}", str(number))
        self.source_filter.setCurrentIndex(max(0, self.source_filter.findData(source)))
        self.formula_filter.setCurrentIndex(max(0, self.formula_filter.findData(formula)))
        for combo in (self.source_filter, self.formula_filter):
            combo.blockSignals(False)
        self.refresh_sources()

    def refresh_sources(self, *_):
        self._global_ids = self.globally_eligible_ids()
        self.selected_ids.intersection_update(self._global_ids)
        self.sync_source_supplier()
        source, formula = self.source_filter.currentData(), self.formula_filter.currentData()
        search = self.search.text().strip().casefold()
        rows = []
        for identity, material in self.materials.items():
            if identity not in self._global_ids:
                continue
            key = self.material_sources[identity]
            label = self.source_label(key)
            if source is not None and source != key:
                continue
            if formula is not None and formula != str(material.formula):
                continue
            if search and search not in f"{material.name} {label}".casefold():
                continue
            rows.append({"name": material.name, "source": label, "formula": material.formula,
                         "n_d": material.nd, "V_d": material.vd,
                         "diagnostics": "; ".join(f"{d.severity}: {d.message}" for d in material.diagnostics),
                         "identity": identity})
        self._resetting = True
        try:
            self._set_rows(self.source_model, self.source_view, rows)
            selection = self.source_view.selectionModel()
            for index, row in enumerate(self.source_model.rows):
                if row["identity"] in self.selected_ids:
                    selection.select(self.source_model.index(index, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        finally:
            self._resetting = False
        self.update_selection_label()
        indexes = self.source_view.selectionModel().selectedRows()
        if indexes:
            self.inspect(self.materials[self.source_model.rows[indexes[-1].row()]["identity"]])
        else:
            # Do not leave stale enrichment visible after a workbook reload or correction.
            self.details.clear()
            self.raw.clear()

    @staticmethod
    def _set_rows(model, view, rows):
        header = view.horizontalHeader()
        column, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        model.set_rows(rows)
        if 0 <= column < model.columnCount():
            model.sort(column, order)
        if "identity" in model.columns:
            view.hideColumn(model.columns.index("identity"))
        for index, name in enumerate(model.columns):
            if name != "identity":
                view.setColumnWidth(index, 130 if name in ("name", "export_name") else 180)

    def source_selection_changed(self, *_):
        if self._resetting:
            return
        visible = {row["identity"] for row in self.source_model.rows}
        self.selected_ids.difference_update(visible)
        indexes = self.source_view.selectionModel().selectedRows()
        self.selected_ids.update(self.source_model.rows[index.row()]["identity"] for index in indexes)
        self.update_selection_label()
        if indexes:
            self.inspect(self.materials[self.source_model.rows[indexes[-1].row()]["identity"]])

    def update_selection_label(self):
        visible = {row["identity"] for row in self.source_model.rows}
        hidden = len(self.selected_ids - visible)
        self.selection_label.setText(f"{len(visible)} / {len(self.materials)} materials · {len(self._global_ids)} globally eligible · "
                                     f"{len(self.selected_ids)} selected ({hidden} hidden by local filters)")

    def clear_selection(self):
        self.selected_ids.clear()
        self.source_view.clearSelection()
        self.update_selection_label()

    def add_selected(self):
        # Recheck eligibility even if selection was programmatically changed or stale.
        self.selected_ids.intersection_update(self.globally_eligible_ids())
        # Iterate source insertion order, never row positions or unordered selection order.
        materials = [material for identity, material in self.materials.items()
                     if identity in self.selected_ids and identity not in self.basket]
        new_items = allocate_export_items(materials, existing_items=self.basket.values())
        for item in new_items:
            original = material_comment(item.material)
            first_line = original.splitlines()[0] if original else ""
            if first_line != original:
                item = replace(item, glass_comment=first_line)
            self.basket[item.material.identity] = item
        self.update_selection_label()
        if new_items:
            self.refresh_basket()

    def refresh_basket(self):
        selected = {self.basket_model.rows[i.row()]["identity"] for i in self.basket_view.selectionModel().selectedRows()}
        rows = [{"export_name": item.export_name if item.export_name is not None else item.material.name,
                 "original_name": item.material.name, "source": item.material.source_path,
                 "kind": "Generated" if item.material.generated else "Preserved", "identity": identity}
                for identity, item in self.basket.items()]
        self._set_rows(self.basket_model, self.basket_view, rows)
        for index, row in enumerate(self.basket_model.rows):
            if row["identity"] in selected:
                self.basket_view.selectionModel().select(self.basket_model.index(index, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.basket_label.setText(f"Export basket: {len(rows)}")
        # An acknowledgment of an earlier basket must not silently cover newly added warnings.
        self.acknowledge.setChecked(False)
        self.invalidate_preview()
        self.inspect_basket()

    def rename_item(self, identity, name):
        item = self.basket[identity]
        updated = replace(item, export_name=name)
        if updated != item:
            self.basket[identity] = updated
            self.refresh_basket()

    def set_glass_comment(self, identity, comment):
        item = self.basket[identity]
        updated = replace(item, glass_comment=comment)
        if updated != item:
            self.basket[identity] = updated
            self.refresh_basket()

    def edit_glass_comment(self):
        indexes = self.basket_view.selectionModel().selectedRows()
        if len(indexes) != 1:
            self.status.setText("Select exactly one basket row to edit its output glass comment.")
            return
        identity = self.basket_model.rows[indexes[0].row()]["identity"]
        item = self.basket[identity]
        dialog = CommentDialog(f"Glass comment — {item.material.name}", material_comment(item.material),
                               item.glass_comment, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_glass_comment(identity, dialog.comment_value)
        dialog.deleteLater()

    def source_catalog_comments(self):
        sections = []
        headers = {_json(("agf", *key)): document.header for key, document in self.documents.items()}
        for source, label in self.sources.items():
            materials = [material for identity, material in self.materials.items()
                         if self.material_sources[identity] == source]
            header = headers.get(source, materials[0].source_header if materials else "")
            comments = [line for line in header.splitlines()
                        if line.split() and line.split()[0].upper() == "CC"]
            sections.append(label + "\n" + ("\n".join(comments) or "(No source catalog CC comment)"))
        # Header-only catalogs have no material rows, but still have source comments.
        return "\n\n".join(sections) or "No loaded source catalogs."

    def edit_catalog_comment(self):
        dialog = CommentDialog("Export catalog comment", self.source_catalog_comments(),
                               self.catalog_comment, self, allow_reset=False)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.comment_value != self.catalog_comment:
            self.catalog_comment = dialog.comment_value
            self.invalidate_preview()
            self.inspect_basket()
        dialog.deleteLater()

    def rename_selected(self):
        indexes = self.basket_view.selectionModel().selectedRows()
        if len(indexes) != 1:
            self.status.setText("Select exactly one basket row to rename its output material.")
            return
        identity = self.basket_model.rows[indexes[0].row()]["identity"]
        item = self.basket[identity]
        name, accepted = QInputDialog.getText(self, "Export name", "Explicit new AGF material name (validated in preview)",
                                             text=item.export_name if item.export_name is not None else item.material.name)
        if accepted:
            self.rename_item(identity, name)

    def remove_selected(self):
        for index in self.basket_view.selectionModel().selectedRows():
            self.basket.pop(self.basket_model.rows[index.row()]["identity"], None)
        self.refresh_basket()

    def clear_basket(self):
        self.basket.clear()
        self.refresh_basket()

    def inspect_basket(self, *_):
        indexes = self.basket_view.selectionModel().selectedRows()
        self.glass_comment_button.setEnabled(len(indexes) == 1)
        if indexes:
            identity = self.basket_model.rows[indexes[-1].row()]["identity"]
            # Selection signals may fire while rows are reset after removal.
            if identity in self.basket:
                item = self.basket[identity]
                self.inspect(item.material, item=item)

    def inspect(self, material, *, item=None):
        summary = [material.name,
                   f"Formula {material.formula}: {material.properties.get('formula_label', 'Unknown / locally unevaluated')}",
                   f"Status: {material.properties.get('status_label', 'Unspecified/unknown')}",
                   f"{'Generated workbook snapshot' if material.generated else 'Preserved AGF source'}: {material.source_path}",
                   f"Source lines: {material.start_line}–{material.end_line}",
                   "", "Diagnostics (no missing values are silently repaired):"]
        summary.extend(f"{d.severity.upper()} [{d.code}] line {d.line}: {d.message}" for d in material.diagnostics)
        if not material.diagnostics:
            summary.append("No parser / conversion diagnostics.")
        summary.extend(["", "Interpreted values below retain the backend's explicit unit labels (_um, _mm, _ppm_k, etc.).",
                        "Null means unavailable, not zero. Original token spelling and precision are on the records tab.", ""])
        output = {}
        if item is not None:
            original = material_comment(material)
            output["output_overrides"] = {
                "export_name": item.export_name,
                "effective_name": item.export_name if item.export_name is not None else material.name,
                "original_glass_comment": original, "glass_comment_override": item.glass_comment,
                "effective_glass_comment": original if item.glass_comment is None else item.glass_comment,
                "catalog_comment": self.catalog_comment,
                "scope": "Output only; original raw records and source files are unchanged.",
            }
        self.details.setPlainText("\n".join(summary) + "\n" + _json({**output, "name": material.name, "formula": material.formula,
            "n_d": material.nd, "V_d": material.vd, "properties": material.properties,
            "diagnostics": material.diagnostics, "source_path": material.source_path,
            "source_sha256": material.source_sha256, "encoding": material.source_encoding,
            "source_lines": [material.start_line, material.end_line], "source_header": material.source_header,
            "identity": material.identity, "generated": material.generated, "provenance": material.provenance,
            "browser_metadata": self.filter_metadata.get(material.identity, {}),
            "records": [{"mnemonic": r.mnemonic, "line": r.line, "tokens": r.tokens, "values": r.values} for r in material.records]}))
        self.raw.setPlainText(material.raw_text)
        self.detail_tabs.setCurrentWidget(self.details)

    def invalidate_preview(self, *_):
        self.preview = None
        self.export_button.setEnabled(False)
        self.preview_text.clear()
        self.diagnostics.setPlainText("Basket or options changed. Validate / Preview export before saving.")

    def validate_export(self):
        self.invalidate_preview()
        try:
            preview = build_export(tuple(self.basket.values()), acknowledge_warnings=self.acknowledge.isChecked(),
                                   preserve_invalid=self.preserve_invalid.isChecked(),
                                   catalog_comment=self.catalog_comment)
        except Exception as exc:
            self.diagnostics.setPlainText(f"Validation failed: {type(exc).__name__}: {exc}")
            self.detail_tabs.setCurrentWidget(self.diagnostics)
            return None
        self.preview = preview
        self.preview_text.setPlainText(preview.text)
        self.diagnostics.setPlainText(_json({"valid": preview.valid, "errors": preview.errors,
                                           "warnings": preview.warnings, "manifest": preview.manifest}))
        self.export_button.setEnabled(preview.valid)
        self.status.setText(f"Preview: {len(self.basket)} materials; {len(preview.errors)} blocking errors; {len(preview.warnings)} warnings. "
                            "Review exact export text and validation / manifest before saving.")
        self.detail_tabs.setCurrentWidget(self.diagnostics if not preview.valid else self.preview_text)
        return preview

    def save_to(self, path, *, overwrite=False):
        """Write only the last validated, unchanged preview; backend enforces path safety."""
        if self.preview is None or not self.preview.valid:
            raise ValueError("Validate the current basket and resolve blocking diagnostics before saving.")
        outputs = write_export(self.preview, path, source_paths=tuple(self.protected_paths), overwrite=overwrite)
        self.status.setText("Saved catalog and provenance: " + " | ".join(str(path) for path in outputs))
        return outputs

    def export_dialog(self):
        if self.preview is None or not self.preview.valid:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export a new AGF catalog and provenance", "combined.agf", "AGF catalog (*.agf)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".agf":
            target = target.with_suffix(".agf")
        manifest = target.with_suffix(".metadata.json")
        # Protection is checked before asking for an overwrite and again by the writer.
        protected = {str(Path(p).resolve()).casefold() for p in self.protected_paths}
        if any(str(p.resolve()).casefold() in protected for p in (target, manifest)):
            QMessageBox.warning(self, "Protected source", "Loaded source files cannot be overwritten, including unselected or superseded sources.")
            return
        existing = [p for p in (target, manifest) if p.exists()]
        overwrite = False
        if existing:
            overwrite = QMessageBox.question(self, "Replace existing export files?",
                "This export writes BOTH targets:\n" + "\n".join(str(p) for p in (target, manifest)) +
                "\n\nExisting files to replace:\n" + "\n".join(str(p) for p in existing),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            if not overwrite:
                return
        try:
            self.save_to(target, overwrite=overwrite)
        except Exception as exc:
            written = getattr(exc, "written_paths", ())
            message = f"{type(exc).__name__}: {exc}"
            if written:
                message += "\nFiles already replaced before failure:\n" + "\n".join(str(p) for p in written)
            self.status.setText("Export failed. " + message)
            QMessageBox.warning(self, "Export failed", message)
