from __future__ import annotations

import json
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .widgets import JobController, PlotWidget, ResultsTable, json_default, spin


def integer(value, low, high):
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


class ScreeningTab(QWidget):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.glasses = []
        self.source_metadata = {}
        self.generation = 0
        self.job_generation = 0
        self.efl = spin(90 if kind == "triplet" else 500, 1, 100000, 2, " mm")
        self.max_power = spin(8, .1, 100, 2)
        self.top_k = integer(50, 1, 1000)
        self.names = QLineEdit()
        self.names.setPlaceholderText("Optional exact names/IDs, comma-separated; blank = global filtered pool")
        self.names.setToolTip("Example: H-K9L, N-BK7, CDGM:H-FK95N. Exact names, not prefixes.")
        self.form_box = QGroupBox("Screening constraints")
        form = QFormLayout(self.form_box)
        form.addRow("Target EFL", self.efl)
        form.addRow("Maximum |normalized power|", self.max_power)
        form.addRow("Results retained", self.top_k)
        if kind == "triplet":
            self.top_k.setToolTip(
                "Retain only the best feasible combinations ranked by RMS normalized power. "
                "Selecting a material permits its use; it does not require it in a result. "
                "Increase this limit to inspect lower-ranked feasible combinations."
            )
            self.wavelength = spin(1550, 300, 1690, 2, " nm")
            self.temperature = spin(20, -40, 100, 2, " °C")
            from glass_workbench.screening.triplet import TripletSettings
            default_housing_cte = TripletSettings().housing_cte_ppm
            self.housing = spin(default_housing_cte, -100, 200, 3, " ppm/K")
            housing_guidance = (
                f"Default assumption: Al6061 aluminum ({default_housing_cte:g} ppm/K). "
                "For another mount, edit its linear CTE here using a value appropriate to the alloy "
                "and temperature range. 1 ppm/K = 10⁻⁶/K (1e-6/K). "
                "Constant first-order expansion assumption, not a temperature-dependent structural model."
            )
            self.housing.setToolTip(housing_guidance)
            self.housing_help = QLabel(housing_guidance)
            self.housing_help.setWordWrap(True)
            self.housing_help.setToolTip(housing_guidance)
            self.transmission = spin(.97, 0, 1, 4)
            self.signs = QComboBox()
            self.signs.addItems(["Cooke + - +", "Unrestricted"])
            self.extrapolate = QCheckBox("Allow flagged thermal / dispersion extrapolation")
            self.unknown_transmission = QCheckBox("Allow unknown internal transmission")
            self.unknown_transmission.setToolTip("Needed when supplemental source data do not establish 10-mm internal transmission. Unknown stays unknown; known below-threshold materials remain excluded.")
            form.addRow("Vacuum wavelength", self.wavelength)
            form.addRow("Temperature", self.temperature)
            form.addRow("Mounting / housing CTE", self.housing)
            form.addRow(self.housing_help)
            form.addRow("Min estimated τ at 10 mm", self.transmission)
            form.addRow("Power architecture", self.signs)
            form.addRow(self.extrapolate)
            form.addRow(self.unknown_transmission)
            notice = ("PPTX thin-lens synthesis: Σy = 1, Σ(yψ) = −αhousing, Σ(y/n) = 0. "
                      "Rank by RMS power. + − + is a Cooke starting-material pattern, not a spaced lens prescription. "
                      "The slide's − + − recommendation is not Cooke.\n"
                      "Dry air / 101325 Pa / 450 ppm CO₂. SCHOTT thermal calculations at 1550 nm require "
                      "explicit extrapolation permission. Zero Petzval is not proof of a flat, astigmatism-free image. "
                      "f/2.7 is context only. For supplemental materials with no verified τ10mm, explicitly allow unknown transmission; "
                      "Corning 7980 at 1550 nm may also require extrapolation permission. Unknown τ is never assumed to be 1.")
        else:
            self.gap = spin(.1, 0, 2, 4, " × EFL")
            self.color_weight = spin(1, 0, 1000, 3)
            self.petzval_weight = spin(1, 0, 1000, 3)
            self.candidates = integer(3000, 10, 100000)
            self.refine = integer(100, 0, 1000)
            self.seed = integer(42, 0, 2147483647)
            self.exhaustive = QCheckBox("Exhaustive material tuples (small selected pools only)")
            self.positive_objective = QCheckBox("Require positive cemented objective group")
            self.positive_objective.setChecked(True)
            form.addRow("Air gap / EFL", self.gap)
            form.addRow("Chromatic weight", self.color_weight)
            form.addRow("Petzval weight", self.petzval_weight)
            form.addRow("Candidate budget", self.candidates)
            form.addRow("Refinement budget", self.refine)
            form.addRow("Reproducible seed", self.seed)
            form.addRow(self.positive_objective)
            form.addRow(self.exhaustive)
            notice = ("C / d / F: 656.2725 / 587.5618 / 486.1327 nm (conventional air wavelengths; converted internally to vacuum). Thin cemented triplet + air gap + thin singlet. "
                      "Evaluate common-plane focal spread and interface Petzval, not MTF. "
                      "EFL and gap are editable screening examples, not requested telescope specifications.\n"
                      "Results are best found within the reported search budget—not a global optimum. "
                      "Exhaustive mode covers material tuples only; continuous optimization is still local. "
                      "No thermal/cement stress model is included in this visible screening tab.")
        self.notice = QLabel(notice)
        self.notice.setWordWrap(True)
        self.notice.setObjectName("notice")
        self.run = QPushButton("Search glass combinations")
        self.run.clicked.connect(self.search)
        self.cancel = QPushButton("Cancel search")
        self.cancel.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.status = QLabel("Load catalogs and choose constraints to begin.")
        self.status.setWordWrap(True)
        self.table = ResultsTable()
        self.plot = PlotWidget()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Search coverage and assumptions appear here. Select a result for details.")
        self.table.view.selectionModel().selectionChanged.connect(self.show_detail)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self.form_box)
        controls_layout.addStretch()
        controls_layout.addWidget(self.run)
        controls_layout.addWidget(self.cancel)
        controls_layout.addWidget(self.progress_bar)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.status)
        right_layout.addWidget(self.table, 3)
        lower = QSplitter(Qt.Orientation.Horizontal)
        lower.addWidget(self.plot)
        lower.addWidget(self.detail)
        lower.setSizes([480, 380])
        right_layout.addWidget(lower, 2)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(controls)
        split.addWidget(right)
        split.setSizes([280, 1000])
        layout = QVBoxLayout(self)
        layout.addWidget(self.notice)
        layout.addWidget(self.names)
        layout.addWidget(split)
        self.job = JobController(self)
        self.job.completed.connect(self.completed)
        self.job.failed.connect(self.failed)
        self.job.progress.connect(self.progress)
        self.job.busy_changed.connect(self.busy_changed)
        self.cancel.clicked.connect(self.job.cancel)
        self.last_metadata = {}

    def busy_changed(self, busy):
        self.run.setEnabled(not busy)
        self.form_box.setEnabled(not busy)
        self.names.setEnabled(not busy)
        self.cancel.setEnabled(busy)

    def update_glasses(self, glasses, metadata):
        self.generation += 1
        self.job.cancel()
        self.glasses = list(glasses)
        self.source_metadata = metadata
        self.table.set_rows([])
        self.last_metadata = {}
        self.detail.clear()
        self.plot.axes[0].clear()
        self.plot.canvas.draw_idle()
        self.status.setText(f"{len(glasses)} glasses in global filtered pool. Search uses an immutable input snapshot.")

    def search(self):
        if self.job.busy:
            return
        glasses = list(self.glasses)
        requested = {name.strip().casefold() for name in self.names.text().split(",") if name.strip()}
        if requested:
            known = {v.casefold() for g in glasses for v in (g.name, g.uid)}
            unknown = requested - known
            if unknown:
                self.status.setText("Names not in current filtered pool: " + ", ".join(sorted(unknown)))
                return
            glasses = [g for g in glasses if g.name.casefold() in requested or g.uid.casefold() in requested]
        if not glasses:
            self.status.setText("No glasses selected. Load catalogs or change filters.")
            return
        if self.kind == "triplet":
            from glass_workbench.screening.triplet import TripletSettings, search_triplets
            settings = TripletSettings(wavelength_um=self.wavelength.value() / 1000,
                                       temperature_c=self.temperature.value(), efl_mm=self.efl.value(),
                                       housing_cte_ppm=self.housing.value(), max_power=self.max_power.value(),
                                       min_transmission=self.transmission.value(), sign_pattern=self.signs.currentText(),
                                       top_k=self.top_k.value(), allow_extrapolation=self.extrapolate.isChecked(),
                                       allow_unknown_transmission=self.unknown_transmission.isChecked())
            function = search_triplets
        else:
            from glass_workbench.screening.telescope import TelescopeSettings, search_telescope
            settings = TelescopeSettings(efl_mm=self.efl.value(), gap_ratio=self.gap.value(),
                                         max_power=self.max_power.value(), chromatic_weight=self.color_weight.value(),
                                         petzval_weight=self.petzval_weight.value(), top_k=self.top_k.value(),
                                         candidate_limit=self.candidates.value(), refine_count=self.refine.value(),
                                         seed=self.seed.value(), exhaustive=self.exhaustive.isChecked(),
                                         positive_objective=self.positive_objective.isChecked())
            function = search_telescope
        self.job_generation = self.generation
        self.pending_metadata = dict(self.source_metadata, settings=asdict(settings),
                                     selected_glasses=[g.uid for g in glasses])
        self.table.set_rows([])
        self.detail.clear()
        self.last_metadata = {}
        self.plot.axes[0].clear()
        self.plot.canvas.draw_idle()
        self.status.setText("Starting first-order screening…")
        self.progress_bar.setRange(0, 0)
        self.job.start(lambda progress, cancelled: function(glasses, settings, progress=progress, cancelled=cancelled))

    def progress(self, current, total, text):
        if total:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(round(1000 * current / total))
        self.status.setText(f"{text} • {current:,}/{total:,}")

    def failed(self, text):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status.setText(text)

    def completed(self, result):
        if self.job_generation != self.generation:
            return
        self.last_metadata = dict(self.pending_metadata, screening=result.metadata, cancelled=result.cancelled)
        self.table.set_rows(result.rows, self.last_metadata)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if not result.cancelled else 0)
        partial = "CANCELLED — partial results. " if result.cancelled else ""
        if self.kind == "triplet":
            counts = []
            eligible = result.metadata.get("eligible_glass_count")
            accepted = result.metadata.get("accepted_count")
            if eligible is not None:
                counts.append(f"{eligible:,} eligible glasses")
            if accepted is not None:
                counts.append(f"{accepted:,} feasible combinations")
            counts.append(f"{len(result.rows):,} best candidates retained")
            self.status.setText(
                partial + "; ".join(counts) + ". "
                "Ranked by RMS normalized power under the selected constraints. "
                "Selecting a material permits its use; it does not require it in a result. "
                "Eligible materials may be absent from the retained top results; "
                "increase Results retained to inspect lower-ranked feasible combinations."
            )
        else:
            self.status.setText(f"{len(result.rows)} candidates retained. " + partial
                                + "Best found within reported search coverage.")
        self.detail.setPlainText(json.dumps(self.last_metadata, indent=2, default=json_default))
        ax = self.plot.axes[0]
        ax.clear()
        if self.kind == "telescope":
            x = [abs(r.get("petzval", 0)) for r in result.rows]
            y = [r.get("bfl_spread_mm", 0) for r in result.rows]
            ax.scatter(x, y, c=[r["score"] for r in result.rows], cmap="viridis", s=28)
            ax.set(xlabel="|Normalized Petzval|", ylabel="C/d/F BFL spread (mm)", title="Chromatic / Petzval trade-off")
        else:
            ax.plot(range(1, len(result.rows) + 1), [r["score"] for r in result.rows], ".-")
            ax.set(xlabel="Rank", ylabel="RMS normalized power", title="Power burden under exact first-order constraints")
        ax.grid(alpha=.2)
        self.plot.canvas.draw_idle()

    def show_detail(self, *_):
        selected = self.table.view.selectionModel().selectedRows()
        if selected:
            row = self.table.model.rows[selected[0].row()]
            self.detail.setPlainText(json.dumps({"candidate": row, "run": self.last_metadata}, indent=2, default=json_default))
