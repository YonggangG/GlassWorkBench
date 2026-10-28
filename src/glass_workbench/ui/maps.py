from __future__ import annotations

from collections import defaultdict
from math import isfinite

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QSplitter, QVBoxLayout, QWidget

from .widgets import PlotWidget, ResultsTable, display


def plottable(glass, field):
    return all(value is not None and isfinite(value) for value in (glass.vd, getattr(glass, field)))


class MapsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.glasses = []
        self.all_glasses = []
        self.metadata = {}
        self.family_filter = QComboBox()
        self.family_filter.addItem("All families")
        self.family_filter.currentTextChanged.connect(self.redraw)
        self.highlight = QLineEdit()
        self.highlight.setPlaceholderText("Highlight prefix without hiding other glasses")
        self.highlight.textChanged.connect(self.redraw)
        self.collections = []
        self.annotations = []
        self.details = QLabel("Hover a point for catalog properties; click for source details. Workbook values and source-based supplemental properties; IR-only materials appear in the table, not visible maps.")
        self.details.setWordWrap(True)
        self.plot = PlotWidget(2)
        self.table = ResultsTable()
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.plot)
        splitter.addWidget(self.table)
        splitter.setSizes([470, 230])
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("Map family"))
        tools.addWidget(self.family_filter)
        tools.addWidget(self.highlight, 1)
        tools.addWidget(QLabel("● CDGM    ▲ SCHOTT    ◆ supplements • color = family"))
        layout.addLayout(tools)
        layout.addWidget(self.details)
        layout.addWidget(splitter)
        self.plot.canvas.mpl_connect("motion_notify_event", self.hover)
        self.plot.canvas.mpl_connect("button_press_event", self.click)

    def update_glasses(self, glasses, metadata):
        self.all_glasses = list(glasses)
        self.metadata = metadata
        previous = self.family_filter.currentText()
        self.family_filter.blockSignals(True)
        self.family_filter.clear()
        self.family_filter.addItems(["All families"] + sorted({g.family for g in glasses}))
        if self.family_filter.findText(previous) >= 0:
            self.family_filter.setCurrentText(previous)
        self.family_filter.blockSignals(False)
        self.redraw()

    def redraw(self, *_):
        family = self.family_filter.currentText()
        glasses = [g for g in self.all_glasses if family == "All families" or g.family == family]
        metadata = dict(self.metadata, map_family=family, highlight_prefix=self.highlight.text())
        self.glasses = list(glasses)
        self.collections.clear()
        self.annotations.clear()
        groups = defaultdict(list)
        for glass in glasses:
            groups[(glass.family, glass.supplier)].append(glass)
        families = sorted({g.family for g in glasses})
        from matplotlib import colormaps
        colors = {family: colormaps["tab20"](i % 20) for i, family in enumerate(families)}
        for index, (ax, title, field) in enumerate(zip(self.plot.axes, ["Refractive index map", "Relative partial dispersion"], ["nd", "pgf"])):
            ax.clear()
            for (family, supplier), records in sorted(groups.items()):
                records = [g for g in records if plottable(g, field)]
                if not records:
                    continue
                scatter = ax.scatter([g.vd for g in records], [getattr(g, field) for g in records],
                                     s=30, c=[colors[family]], alpha=.85,
                                     marker={"CDGM": "o", "SCHOTT": "^"}.get(supplier, "D"),
                                     label=f"{family} / {supplier}", picker=5)
                self.collections.append((scatter, records))
            prefix = self.highlight.text().strip().casefold()
            matches = [g for g in glasses if prefix and g.name.casefold().startswith(prefix) and plottable(g, field)]
            if matches:
                highlight = ax.scatter([g.vd for g in matches], [getattr(g, field) for g in matches],
                                       marker="*", s=150, color="black", edgecolors="white", linewidths=.6,
                                       label="Highlighted prefix", zorder=10)
                self.collections.insert(0, (highlight, matches))
            if index == 1:
                ax.plot([64.2, 37.0], [.5359, .5867], color="#23364d", linewidth=1.4,
                        label="Reference H-K9L—H-F2 segment")
            ax.set_title(title, fontsize=11, fontweight="bold")
            ax.set_xlabel("Abbe number Vd (descending)")
            ax.set_ylabel("nd" if index == 0 else "Pg,F")
            ax.invert_xaxis()
            ax.grid(alpha=.2)
            annotation = ax.annotate("", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
                                     bbox={"boxstyle": "round", "fc": "white", "alpha": .95}, fontsize=8)
            annotation.set_visible(False)
            self.annotations.append(annotation)
        handles, _ = self.plot.axes[0].get_legend_handles_labels()
        if len(groups) <= 14 and handles:
            self.plot.axes[0].legend(fontsize=6, loc="best", ncol=2)
        self.plot.canvas.draw_idle()
        self.table.set_rows([
            {"supplier": g.supplier, "glass": g.name, "code": g.code, "nd": g.nd,
             "Vd": g.vd, "PgF": g.pgf, "family": g.family, "melt_frequency": g.melt_frequency or None,
             "relative_price_supplier_only": g.price, "CTE_ppm_K": None if g.cte is None else g.cte * 1e6,
             "dispersion_model": g.dispersion_model, "thermal_model": g.thermal_model if g.thermal or g.thermal_model != "catalog_d" else "missing",
             "visible_map": "available" if plottable(g, "nd") else "unavailable (IR-only or missing visible data)",
             "supplemental": g.supplemental, "source_urls": g.source_urls,
             "source_sheet": g.source_sheet, "source_row": g.source_row,
             "remarks": g.remarks, "warnings": "; ".join(g.warnings)} for g in glasses
        ], metadata)

    def hit(self, event):
        if event.inaxes:
            for scatter, records in self.collections:
                if scatter.axes is event.inaxes:
                    contains, info = scatter.contains(event)
                    if contains:
                        idx = info["ind"][0]
                        return scatter, records[idx], idx
        return None

    def hover(self, event):
        hit = self.hit(event)
        for ann in self.annotations:
            ann.set_visible(False)
        if hit:
            scatter, glass, idx = hit
            annotation = self.annotations[list(self.plot.axes).index(scatter.axes)]
            annotation.xy = scatter.get_offsets()[idx]
            annotation.set_text(f"{glass.uid} [{glass.code}]\nnd={display(glass.nd)}; Vd={display(glass.vd)}\n"
                                f"Melt: {glass.melt_frequency or 'not specified'}; supplier price: {glass.price}")
            annotation.set_visible(True)
        self.plot.canvas.draw_idle()

    def click(self, event):
        hit = self.hit(event)
        if hit:
            _, glass, _ = hit
            self.details.setText(f"{glass.uid} • {glass.source_file} • {glass.source_sheet}, row {glass.source_row}\n"
                                 f"{glass.remarks} {'; '.join(glass.warnings)}")
            for row, record in enumerate(self.table.model.rows):
                if record["supplier"] == glass.supplier and record["glass"] == glass.name:
                    self.table.view.selectRow(row)
                    self.table.view.scrollTo(self.table.model.index(row, 0))
                    break
