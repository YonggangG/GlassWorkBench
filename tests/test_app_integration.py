"""Local source-data smoke tests; skipped in CI where catalogs are external."""
from pathlib import Path

import pytest

from glass_workbench.catalogs.loader import discover_catalogs, load_catalog
from glass_workbench.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def actual_catalogs():
    root = Path(__file__).resolve().parents[1]
    paths = discover_catalogs(root)
    if len(paths) < 2:
        pytest.skip("Official workbooks are external and not distributed with the application")
    return [load_catalog(path) for path in paths]


def test_actual_catalog_gui_thermal_and_reload(qtbot, actual_catalogs):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.imported((actual_catalogs, []))
    assert sum(not g.supplemental for g in window.glasses) == 450
    assert len(window.glasses) == 452
    window.preset.setCurrentText("Popular: (CDGM H- ∩ MA) or SCHOTT N-")
    assert len(window.thermal.glasses) == 146
    for checkbox in window.supplement_controls.values():
        checkbox.setChecked(False)
    assert len(window.thermal.glasses) == 144
    window.thermal.extrapolate.setChecked(True)
    with qtbot.waitSignal(window.thermal.job.completed, timeout=30000):
        window.thermal.calculate()
    qtbot.waitUntil(lambda: not window.thermal.job.busy, timeout=5000)
    assert len(window.thermal.table.model.rows) == 144
    assert any(r.get("n_relative") for r in window.thermal.table.model.rows)
    window.thermal.table.view.selectRow(0)
    assert len(window.thermal.plot.axes[0].lines) == 2
    window.thermal.temperature.setValue(50)
    with qtbot.waitSignal(window.thermal.job.completed, timeout=30000):
        window.thermal.calculate()
        assert not window.thermal.plot.axes[0].lines
    qtbot.waitUntil(lambda: not window.thermal.job.busy, timeout=5000)
    assert not window.thermal.plot.axes[0].lines
    assert window.thermal.table.metadata["temperature_c"] == 50
    window.preset.setCurrentText("All first-sheet glasses")
    assert not window.thermal.table.model.rows
    window.close()


def test_screening_tabs_real_sources(qtbot, actual_catalogs):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.imported((actual_catalogs, []))
    window.preset.setCurrentText("Popular: (CDGM H- ∩ MA) or SCHOTT N-")
    window.triplet.top_k.setValue(5)
    with qtbot.waitSignal(window.triplet.job.completed, timeout=30000):
        window.triplet.search()
    qtbot.waitUntil(lambda: not window.triplet.job.busy, timeout=5000)
    assert len(window.triplet.table.model.rows) == 5
    assert all(r["powers"][0] > 0 and r["powers"][1] < 0 and r["powers"][2] > 0
               for r in window.triplet.table.model.rows)
    window.telescope.candidates.setValue(30)
    window.telescope.refine.setValue(3)
    window.telescope.top_k.setValue(5)
    with qtbot.waitSignal(window.telescope.job.completed, timeout=30000):
        window.telescope.search()
    qtbot.waitUntil(lambda: not window.telescope.job.busy, timeout=5000)
    assert window.telescope.table.model.rows
    assert all(abs(r["efl_d_mm"] - 500) < 1e-6 for r in window.telescope.table.model.rows)
    window.close()


def test_1550_gui_search_with_both_supplements(qtbot, actual_catalogs):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.imported((actual_catalogs, []))
    window.triplet.names.setText("H-ZLaF96, HPFS 7980, Silicon")
    window.triplet.extrapolate.setChecked(True)
    window.triplet.unknown_transmission.setChecked(True)
    with qtbot.waitSignal(window.triplet.job.completed, timeout=30000):
        window.triplet.search()
    qtbot.waitUntil(lambda: not window.triplet.job.busy, timeout=5000)
    assert len(window.triplet.table.model.rows) == 1
    row = window.triplet.table.model.rows[0]
    assert set(row["supplemental_glasses"]) == {"Corning:HPFS 7980", "Infrared:Silicon"}
    assert row["transmission_min"] is None
    assert row["powers"][0] > 0 and row["powers"][1] < 0 and row["powers"][2] > 0
    assert row["warnings"]
    window.close()


def test_import_worker_real_sources(qtbot, actual_catalogs):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    with qtbot.waitSignal(window.import_job.completed, timeout=30000):
        window.load_paths([c.path for c in actual_catalogs])
    qtbot.waitUntil(lambda: not window.import_job.busy, timeout=5000)
    assert sum(not g.supplemental for g in window.glasses) == 450
    assert len(window.glasses) == 452
    window.close()
