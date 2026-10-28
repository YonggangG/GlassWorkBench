"""The editable mount assumption must reach the actual search and export metadata."""
import json

import pytest

from glass_workbench.contracts import Glass, ThermalResult
from glass_workbench.screening import triplet
from glass_workbench.screening.triplet import TripletSettings
from glass_workbench.ui.screening import ScreeningTab
from glass_workbench.ui.widgets import export_rows


def test_mount_default_and_persistent_guidance(qtbot):
    page = ScreeningTab("triplet")
    qtbot.addWidget(page)
    page.show()
    assert page.housing.value() == TripletSettings().housing_cte_ppm == 23.6
    assert page.housing.suffix() == " ppm/K"
    assert page.form_box.layout().labelForField(page.housing).text() == "Mounting / housing CTE"
    assert page.housing_help.isVisible()
    text = page.housing_help.text()
    for phrase in ("Default assumption", "Al6061 aluminum", "another mount", "alloy", "temperature range",
                   "1 ppm/K = 10⁻⁶/K", "1e-6/K", "Constant first-order", "not a temperature-dependent structural model"):
        assert phrase in text
        assert phrase in page.housing.toolTip()
    page.housing.setValue(12.34)
    assert page.housing.value() == 12.34
    assert page.housing_help.text() == text  # Al6061 describes only the default assumption.


def test_custom_mount_reaches_real_search_results_and_export(qtbot, monkeypatch, tmp_path):
    page = ScreeningTab("triplet")
    qtbot.addWidget(page)
    pool = [Glass("TEST", name, name, n, 60., cte=0., transmission=((.4, .995), (2., .99)))
            for name, n in [("a", 1.8), ("b", 1.5), ("c", 1.9)]]
    psis = dict(a=1e-6, b=8e-6, c=3.536842105263158e-6)
    def evaluate(glass, *args, **kwargs):
        dn = psis[glass.name] * (glass.nd - 1)
        return ThermalResult(glass.nd, glass.nd, dn, dn, 1., 0., ())
    monkeypatch.setattr(triplet.thermal, "evaluate", evaluate)
    page.update_glasses(pool, {"source": "synthetic optical data"})
    page.housing.setValue(12.34)
    page.signs.setCurrentText("Unrestricted")
    page.max_power.setValue(100)
    with qtbot.waitSignal(page.job.completed, timeout=10000):
        page.search()
        # Editing controls/programmatic changes after starting cannot rewrite the input snapshot.
        page.housing.setValue(19.)
    qtbot.waitUntil(lambda: not page.job.busy, timeout=10000)
    assert page.table.model.rows
    assert page.last_metadata["settings"]["housing_cte_ppm"] == 12.34
    assert page.last_metadata["screening"]["settings"]["housing_cte_ppm"] == 12.34
    row = page.table.model.rows[0]
    by_uid = {g.uid: psis[g.name] for g in pool}
    thermal_sum = sum(power * by_uid[uid] for power, uid in zip(row["powers"], row["glass_ids"]))
    assert thermal_sum == pytest.approx(-12.34e-6, abs=1e-16)
    target = tmp_path / "custom-mount.csv"
    export_rows(target, page.table.model.rows, page.last_metadata)
    exported = json.loads(target.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert exported["settings"]["housing_cte_ppm"] == 12.34
    assert exported["screening"]["settings"]["housing_cte_ppm"] == 12.34
