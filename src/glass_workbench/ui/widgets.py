from __future__ import annotations

import csv
import json
import math
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure


def display(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.8g}" if math.isfinite(value) else str(value)
    if isinstance(value, (tuple, list)):
        return ", ".join(display(v) for v in value)
    return str(value)


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def export_rows(path, rows, metadata):
    """Save visible results with a neighboring reproducibility manifest."""
    path = Path(path)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("" if value is None else display(value)) for key, value in row.items()})
    path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=json_default), encoding="utf-8"
    )


class RecordsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.columns = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.columns = list(dict.fromkeys(key for row in self.rows for key in row))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.rows[index.row()].get(self.columns[index.column()])
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return display(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (float, int)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.columns[section].replace("_", " ")
            return str(section + 1)
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not self.columns:
            return
        key = self.columns[column]
        self.layoutAboutToBeChanged.emit()
        old_indexes = self.persistentIndexList()
        old_records = [(self.rows[index.row()], index.column()) for index in old_indexes]
        def sort_key(row):
            value = row.get(key)
            if value is None:
                return (2, "")
            if isinstance(value, (int, float)):
                return (0, value)
            return (1, str(value).casefold())
        self.rows.sort(key=sort_key, reverse=order == Qt.SortOrder.DescendingOrder)
        positions = {id(row): index for index, row in enumerate(self.rows)}
        self.changePersistentIndexList(old_indexes, [self.index(positions[id(row)], column)
                                                     for row, column in old_records])
        self.layoutChanged.emit()


class ResultsTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.metadata = {}
        self.model = RecordsModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.summary = QLabel("No results yet")
        button = QPushButton("Export table + metadata…")
        button.clicked.connect(self.export)
        bar = QHBoxLayout()
        bar.addWidget(self.summary)
        bar.addStretch()
        bar.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.view)

    def set_rows(self, rows, metadata=None):
        self.metadata = metadata or {}
        self.model.set_rows(rows)
        self.summary.setText(f"{len(rows):,} rows • click headers to sort")
        self.view.resizeColumnsToContents()
        for col in range(self.model.columnCount()):
            self.view.setColumnWidth(col, min(360, max(95, self.view.columnWidth(col))))

    def export(self):
        if not self.model.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "glass_results.csv", "CSV (*.csv)")
        if path:
            try:
                export_rows(path, self.model.rows, self.metadata)
            except OSError as exc:
                QMessageBox.warning(self, "Export failed", str(exc))


class PlotWidget(QWidget):
    def __init__(self, axes=1, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(9, 4), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.subplots(1, axes, squeeze=False)[0]
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self.canvas.setMinimumHeight(230)


def spin(value, minimum, maximum, decimals=3, suffix=""):
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    return widget


class Worker(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)
    finished = Signal()

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.stop = threading.Event()

    @Slot()
    def run(self):
        try:
            result = self.function(self.progress.emit, self.stop.is_set)
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class JobController(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None

    @property
    def busy(self):
        return self.thread is not None

    def start(self, function):
        if self.busy:
            return False
        self.thread = QThread(self)
        self.worker = Worker(function)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.done.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self.thread.start()
        return True

    @Slot()
    def _finished(self):
        thread = self.thread
        self.thread = None
        self.worker = None
        thread.deleteLater()
        self.busy_changed.emit(False)

    def cancel(self):
        if self.worker:
            self.worker.stop.set()
