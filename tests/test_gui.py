from dataclasses import replace
import json

from glass_workbench.contracts import Catalog, Glass
from glass_workbench.ui.main_window import MainWindow, filtered_glasses
from glass_workbench.ui.widgets import JobController, RecordsModel, ResultsTable, export_rows


def glasses():
    base = Glass("CDGM", "H-K9L", "517642", 1.5168, 64.2, .5359, melt_frequency="MA")
    return [base, replace(base, name="H-K1", melt_frequency="A"),
            replace(base, supplier="SCHOTT", name="N-BK7", melt_frequency=""),
            replace(base, supplier="SCHOTT", name="F2", melt_frequency="")]


def test_filter_semantics():
    records = glasses()
    assert len(filtered_glasses(records)) == 4
    assert len(filtered_glasses(records, preset="H- or N-")) == 3
    assert len(filtered_glasses(records, preset="Popular: (CDGM H- ∩ MA) or SCHOTT N-")) == 2
    assert len(filtered_glasses(records, melt="MA")) == 1
    assert len(filtered_glasses(records, supplier="SCHOTT", melt="MA")) == 0
    assert len(filtered_glasses(records, search="h-k")) == 2


def test_table_sort_and_export(qtbot, tmp_path):
    model = RecordsModel()
    model.set_rows([{"glass": "a", "value": 10}, {"glass": "b", "value": 2}, {"glass": "c", "value": None}])
    model.sort(1)
    assert [r["glass"] for r in model.rows] == ["b", "a", "c"]
    target = tmp_path / "result.csv"
    export_rows(target, model.rows, {"units": "ppm/K", "first_sheet_only": True})
    assert "glass,value" in target.read_text(encoding="utf-8-sig")
    assert json.loads(target.with_suffix(".metadata.json").read_text())["first_sheet_only"]


def test_sort_preserves_selected_record(qtbot):
    table = ResultsTable()
    qtbot.addWidget(table)
    table.set_rows([{"glass": "a", "value": 10}, {"glass": "b", "value": 2}])
    table.view.selectRow(0)
    table.model.sort(1)
    selected = table.view.selectionModel().selectedRows()[0]
    assert table.model.rows[selected.row()]["glass"] == "a"


def test_invalid_air_calculation_clears_previous_results(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.air.calculate()
    assert window.air.table.model.rows
    window.air.temperature.setValue(100)
    window.air.atmosphere.pressure.setValue(10000)
    window.air.atmosphere.humidity.setValue(100)
    window.air.calculate()
    assert not window.air.table.model.rows
    assert all(not ax.lines for ax in window.air.plot.axes)
    assert "mole fraction" in window.air.output.text()
    window.close()


def test_six_tab_window_and_filters(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    assert window.tabs.count() == 6
    for checkbox in window.supplement_controls.values():
        checkbox.setChecked(False)
    records = glasses()
    window.imported(([Catalog("test", "test.xlsx", "First", "hash", records)], []))
    assert len(window.maps.table.model.rows) == 4
    window.preset.setCurrentText("H- or N-")
    assert len(window.maps.table.model.rows) == 3
    window.melt.setCurrentText("MA")
    assert len(window.maps.table.model.rows) == 1
    assert not window.thermal.table.model.rows
    window.close()


def test_worker_success_and_cleanup(qtbot):
    controller = JobController()
    with qtbot.waitSignal(controller.completed, timeout=5000) as result:
        assert controller.start(lambda progress, cancelled: 42)
        assert not controller.start(lambda progress, cancelled: 43)
    assert result.args == [42]
    qtbot.waitUntil(lambda: not controller.busy, timeout=5000)


def test_worker_error_and_cleanup(qtbot):
    controller = JobController()
    def fail(progress, cancelled):
        raise ValueError("test error")
    with qtbot.waitSignal(controller.failed, timeout=5000) as result:
        controller.start(fail)
    assert "test error" in result.args[0]
    qtbot.waitUntil(lambda: not controller.busy, timeout=5000)


def test_air_tab_calculation(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.air.calculate()
    assert "n_air =" in window.air.output.text()
    assert len(window.air.table.model.rows) == 162
    assert all(row["n_air"] is not None for row in window.air.table.model.rows)
    window.close()
