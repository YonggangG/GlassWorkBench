from __future__ import annotations

from dataclasses import asdict

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from glass_workbench.contracts import Environment
from .widgets import JobController, PlotWidget, ResultsTable, spin


class AtmosphereControls(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Air conditions • phase index • wavelength in vacuum", parent)
        self.pressure = spin(101325, 10000, 150000, 0, " Pa")
        self.humidity = spin(0, 0, 100, 1, " % RH")
        self.co2 = spin(450, 0, 2000, 0, " ppm")
        self.hold = QComboBox()
        self.hold.addItems(["Fixed relative humidity", "Fixed water mole fraction"])
        form = QHBoxLayout(self)
        for label, control in [("Pressure", self.pressure), ("Humidity", self.humidity), ("CO₂", self.co2), ("dn/dT holds p, CO₂ and", self.hold)]:
            form.addWidget(QLabel(label))
            form.addWidget(control)

    def environment(self):
        return Environment(self.pressure.value(), self.humidity.value() / 100, self.co2.value(),
                           "relative_humidity" if self.hold.currentIndex() == 0 else "water_mole_fraction")


class ThermalTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.glasses = []
        self.source_metadata = {}
        self.generation = 0
        self.job_generation = 0
        self.last_context = None
        self.wavelength = spin(1550, 300, 1690, 3, " nm")
        self.temperature = spin(20, -40, 100, 2, " °C")
        self.extrapolate = QCheckBox("Allow flagged dispersion / thermal extrapolation (e.g. SCHOTT / HPFS 7980 at 1550 nm)")
        self.preset = QComboBox()
        self.preset.addItems(["1550 nm / 20 °C", "1550 nm / 50 °C", "905 nm / 20 °C", "905 nm / 50 °C"])
        self.preset.currentIndexChanged.connect(self.apply_preset)
        self.run = QPushButton("Calculate filtered glasses")
        self.run.clicked.connect(self.calculate)
        self.cancel = QPushButton("Cancel")
        self.atmosphere = AtmosphereControls()
        self.status = QLabel("Both absolute and air-relative derivatives are reported. Missing/unsupported data remain explicit.")
        self.status.setWordWrap(True)
        self.table = ResultsTable()
        self.plot = PlotWidget()
        self.curve = QComboBox()
        self.curve.addItems(["Temperature curve", "Wavelength curve"])
        self.curve.currentIndexChanged.connect(self.plot_selected)
        self.table.view.selectionModel().selectionChanged.connect(self.plot_selected)
        controls = QHBoxLayout()
        for label, widget in [("Preset", self.preset), ("λ", self.wavelength), ("T", self.temperature)]:
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addWidget(self.run)
        controls.addWidget(self.cancel)
        self.show_plot = QCheckBox("Show curve plot")
        self.show_plot.setToolTip("Show the selected glass curve; hidden by default to give the table more space.")
        controls.addWidget(self.show_plot)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        self.plot_container = QWidget()
        plot_layout = QVBoxLayout(self.plot_container)
        plot_layout.addWidget(self.curve)
        plot_layout.addWidget(self.plot)
        splitter.addWidget(self.plot_container)
        splitter.setSizes([320, 290])
        self.plot_container.hide()
        self.show_plot.toggled.connect(self.set_plot_visible)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.atmosphere)
        layout.addWidget(self.extrapolate)
        layout.addWidget(self.status)
        layout.addWidget(splitter)
        self.job = JobController(self)
        self.job.completed.connect(self.completed)
        self.job.failed.connect(self.status.setText)
        self.job.busy_changed.connect(self.busy_changed)
        self.job.progress.connect(lambda a, b, text: self.status.setText(f"{text} ({a}/{b})"))
        self.cancel.clicked.connect(self.job.cancel)
        self.cancel.setEnabled(False)

    def set_plot_visible(self, visible):
        self.plot_container.setVisible(visible)
        if visible:
            self.plot_selected()

    def apply_preset(self, index):
        self.wavelength.setValue(1550 if index < 2 else 905)
        self.temperature.setValue(20 if index % 2 == 0 else 50)

    def busy_changed(self, busy):
        self.run.setEnabled(not busy)
        self.cancel.setEnabled(busy)

    def update_glasses(self, glasses, metadata):
        self.generation += 1
        self.job.cancel()
        self.glasses = list(glasses)
        self.source_metadata = metadata
        self.last_context = None
        self.table.set_rows([])
        self.plot.axes[0].clear()
        self.plot.canvas.draw_idle()
        self.status.setText(f"{len(glasses)} filtered glasses. Calculate to update results.")

    def calculate(self):
        if self.job.busy:
            return
        from glass_workbench.optics.thermal import evaluate
        records = list(self.glasses)
        wavelength, temperature = self.wavelength.value() / 1000, self.temperature.value()
        environment = self.atmosphere.environment()
        extrapolate = self.extrapolate.isChecked()
        self.job_generation = self.generation
        metadata = dict(self.source_metadata, wavelength_um=wavelength, temperature_c=temperature,
                        environment=asdict(environment), allow_extrapolation=extrapolate)
        self.pending_context = (records, wavelength, temperature, environment, extrapolate)
        self.last_context = None
        self.table.set_rows([])
        self.plot.axes[0].clear()
        self.plot.canvas.draw_idle()
        def compute(progress, cancelled):
            rows = []
            for index, glass in enumerate(records):
                if cancelled():
                    break
                row = {"supplier": glass.supplier, "glass": glass.name}
                try:
                    value = evaluate(glass, wavelength, temperature, environment, extrapolate)
                    row.update(n_relative=value.n_relative, n_absolute=value.n_absolute,
                               dn_relative_ppm_K=value.dn_relative * 1e6, dn_absolute_ppm_K=value.dn_absolute * 1e6,
                               n_air=value.n_air, dn_air_ppm_K=value.dn_air * 1e6,
                               status="; ".join(value.warnings) or "Calculated")
                except (ValueError, ArithmeticError) as exc:
                    row.update(n_relative=None, n_absolute=None, dn_relative_ppm_K=None,
                               dn_absolute_ppm_K=None, n_air=None, dn_air_ppm_K=None, status=str(exc))
                rows.append(row)
                if index % 20 == 0:
                    progress(index + 1, len(records), "Calculating thermal properties")
            return rows, dict(metadata, cancelled=cancelled(), processed=len(rows))
        self.job.start(compute)

    def completed(self, result):
        if self.job_generation != self.generation:
            return
        rows, metadata = result
        self.last_context = self.pending_context
        self.table.set_rows(rows, metadata)
        count = sum(row.get("n_relative") is not None for row in rows)
        self.status.setText(f"{count}/{len(rows)} calculated; {len(rows) - count} unavailable. "
                            + ("Partial result — cancelled. " if metadata["cancelled"] else "")
                            + "Select a row and enable Show curve plot to view curves. Derivative conditions and source provenance are included in export.")

    def plot_selected(self, *_):
        if not self.last_context:
            return
        selected = self.table.view.selectionModel().selectedRows()
        if not selected:
            return
        row = self.table.model.rows[selected[0].row()]
        records, wavelength, temperature, environment, extrapolate = self.last_context
        glass = next((g for g in records if g.name == row["glass"] and g.supplier == row["supplier"]), None)
        if glass is None:
            return
        from glass_workbench.optics.thermal import evaluate
        ax = self.plot.axes[0]
        ax.clear()
        if self.curve.currentIndex() == 0:
            xs = np.linspace(max(-40, temperature - 25), min(100, temperature + 25), 61)
            inputs = [(wavelength, x) for x in xs]
            xlabel = "Temperature (°C)"
        else:
            xs = np.linspace(max(300, wavelength * 1000 - 250), min(1690, wavelength * 1000 + 250), 61)
            inputs = [(x / 1000, temperature) for x in xs]
            xlabel = "Vacuum wavelength (nm)"
        relative, absolute = [], []
        for wave, temp in inputs:
            try:
                value = evaluate(glass, wave, temp, environment, extrapolate)
                relative.append(value.dn_relative * 1e6)
                absolute.append(value.dn_absolute * 1e6)
            except (ValueError, ArithmeticError):
                relative.append(float("nan"))
                absolute.append(float("nan"))
        ax.plot(xs, relative, label="Relative to air")
        ax.plot(xs, absolute, label="Absolute")
        ax.set(xlabel=xlabel, ylabel="dn/dT (10⁻⁶/K)", title=f"{glass.uid} • invalid samples omitted")
        ax.grid(alpha=.2)
        ax.legend()
        self.plot.canvas.draw_idle()


class AirTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.wavelength = spin(1550, 300, 1690, 3, " nm")
        self.temperature = spin(20, -40, 100, 2, " °C")
        self.atmosphere = AtmosphereControls()
        self.output = QLabel("Ciddor air phase-index calculation. dn/dT is not the group-index derivative.")
        self.output.setWordWrap(True)
        self.table = ResultsTable()
        self.plot = PlotWidget(2)
        controls = QHBoxLayout()
        for label, widget in [("Vacuum wavelength", self.wavelength), ("Temperature", self.temperature)]:
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        button = QPushButton("Calculate air")
        button.clicked.connect(self.calculate)
        controls.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.atmosphere)
        layout.addWidget(self.output)
        layout.addWidget(self.plot, 3)
        layout.addWidget(self.table, 2)

    def calculate(self):
        from glass_workbench.optics.air import air_dn_dt, air_index
        wave, temp = self.wavelength.value() / 1000, self.temperature.value()
        env = self.atmosphere.environment()
        self.table.set_rows([])
        for ax in self.plot.axes:
            ax.clear()
        self.plot.canvas.draw_idle()
        try:
            n = air_index(wave, temp, env)
            derivative = air_dn_dt(wave, temp, env)
        except (ValueError, ArithmeticError) as exc:
            self.output.setText(str(exc))
            return
        self.output.setText(f"n_air = {n:.12f}    •    (n − 1) = {(n - 1) * 1e6:.6f} ppm    •    "
                            f"dn/dT = {derivative * 1e6:.6f} × 10⁻⁶/K\n"
                            f"Derivative at fixed pressure, CO₂ and {env.hold.replace('_', ' ')}.")
        rows = []
        for label, xs in [("temperature", np.linspace(max(-40, temp - 20), min(100, temp + 20), 81)),
                          ("wavelength", np.linspace(.3, 1.69, 81))]:
            ax = self.plot.axes[0 if label == "temperature" else 1]
            ax.clear()
            ys = []
            for x in xs:
                w, t = (wave, x) if label == "temperature" else (x, temp)
                try:
                    value = air_index(w, t, env)
                    dn = air_dn_dt(w, t, env)
                    ys.append((value - 1) * 1e6)
                    rows.append({"sweep": label, "wavelength_nm": w * 1000, "temperature_C": t,
                                 "n_air": value, "dn_dT_ppm_K": dn, "status": "calculated"})
                    rows[-1]["dn_dT_ppm_K"] *= 1e6
                except (ValueError, ArithmeticError) as exc:
                    ys.append(float("nan"))
                    rows.append({"sweep": label, "wavelength_nm": w * 1000, "temperature_C": t,
                                 "n_air": None, "dn_dT_ppm_K": None, "status": str(exc)})
            ax.plot(xs if label == "temperature" else xs * 1000, ys)
            ax.set(xlabel="Temperature (°C)" if label == "temperature" else "Vacuum wavelength (nm)",
                   ylabel="Air refractivity (ppm)")
            ax.grid(alpha=.2)
        self.plot.canvas.draw_idle()
        self.table.set_rows(rows, {"model": "Ciddor phase index", "environment": asdict(env),
                                   "selected_wavelength_um": wave, "selected_temperature_c": temp})
