"""Selection admits materials to the pool; top-k ranking does not require them."""
import hashlib
from pathlib import Path

import pytest

from glass_workbench.contracts import Catalog, Glass, SearchResult
from glass_workbench.ui.main_window import MainWindow
from glass_workbench.ui.screening import ScreeningTab


@pytest.mark.parametrize("cancelled", [False, True])
def test_triplet_summary_distinguishes_eligible_feasible_and_retained(qtbot, cancelled):
    page = ScreeningTab("triplet")
    qtbot.addWidget(page)
    page.pending_metadata = {"settings": {"top_k": 2}}
    result = SearchResult(
        [{"score": 1.5}, {"score": 2.5}],
        {"eligible_glass_count": 65, "accepted_count": 1234}, cancelled,
    )
    page.completed(result)
    text = page.status.text()
    assert "65 eligible glasses" in text
    assert "1,234 feasible combinations" in text
    assert "2 best candidates retained" in text
    assert "Ranked by RMS normalized power" in text
    assert "permits its use; it does not require it" in text
    assert "increase Results retained" in text
    assert ("CANCELLED — partial results." in text) is cancelled
    assert page.progress_bar.value() == (0 if cancelled else 100)
    assert page.last_metadata["cancelled"] is cancelled
    assert page.last_metadata["screening"] == result.metadata
    assert page.table.model.rows == result.rows


@pytest.mark.parametrize("metadata", [{}, {"eligible_glass_count": 3}, {"accepted_count": 0}])
def test_triplet_summary_tolerates_missing_stub_counts(qtbot, metadata):
    page = ScreeningTab("triplet")
    qtbot.addWidget(page)
    page.pending_metadata = {}
    page.completed(SearchResult([], metadata))
    text = page.status.text()
    assert "0 best candidates retained" in text
    assert "None" not in text
    assert ("eligible glasses" in text) is ("eligible_glass_count" in metadata)
    assert ("0 feasible combinations" in text) is ("accepted_count" in metadata)


@pytest.mark.parametrize("cancelled", [False, True])
def test_telescope_summary_keeps_search_coverage_wording(qtbot, cancelled):
    page = ScreeningTab("telescope")
    qtbot.addWidget(page)
    page.pending_metadata = {}
    page.completed(SearchResult([], {}, cancelled))
    partial = "CANCELLED — partial results. " if cancelled else ""
    assert page.status.text() == (
        "0 candidates retained. " + partial + "Best found within reported search coverage."
    )


@pytest.mark.parametrize("corning,silicon", [(False, False), (True, False), (False, True), (True, True)])
def test_supplement_toggles_independently_update_screening_pool(qtbot, corning, silicon):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    ordinary = Glass("CDGM", "H-K9L", "517642", 1.5168, 64.2, melt_frequency="MA")
    window.imported(([Catalog("CDGM", "synthetic.xlsx", "First", "hash", [ordinary])], []))
    window.preset.setCurrentText("H- or N-")
    window.melt.setCurrentText("MA")
    window.supplement_controls["Corning:HPFS 7980"].setChecked(corning)
    window.supplement_controls["Infrared:Silicon"].setChecked(silicon)
    selected = ({"Corning:HPFS 7980"} if corning else set()) | ({"Infrared:Silicon"} if silicon else set())
    assert {g.uid for g in window.triplet.glasses} == {ordinary.uid} | selected
    assert set(window.selected_supplements()) == selected
    assert set(window.triplet.source_metadata["filters"]["selected_supplements"]) == selected
    for checkbox in window.supplement_controls.values():
        assert "does not require the other supplemental material" in checkbox.toolTip()
        assert "not guaranteed" in checkbox.toolTip()
    assert "does not require it in a result" in window.triplet.top_k.toolTip()
    window.close()


def test_actual_ma_ranking_with_silicon_off_and_on(qtbot):
    """Reproduce the GUI settings, including tau >= .97, without changing sources."""
    from glass_workbench.catalogs.loader import discover_catalogs, load_catalog

    paths = discover_catalogs(Path(__file__).resolve().parents[1])
    if len(paths) < 2:
        pytest.skip("Official workbooks are external and not distributed with the application")
    source_hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
    catalogs = [load_catalog(path) for path in paths]
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.imported((catalogs, []))
    window.melt.setCurrentText("MA")
    window.supplement_controls["Corning:HPFS 7980"].setChecked(True)
    window.supplement_controls["Infrared:Silicon"].setChecked(False)
    page = window.triplet
    page.extrapolate.setChecked(True)
    page.unknown_transmission.setChecked(True)
    page.transmission.setValue(.97)
    assert page.wavelength.value() == 1550
    assert page.temperature.value() == 20
    assert page.efl.value() == 90
    assert page.housing.value() == 23.6
    assert page.max_power.value() == 8
    assert page.signs.currentText() == "Cooke + - +"
    assert not page.names.text()
    assert "Corning:HPFS 7980" in {g.uid for g in page.glasses}
    assert "Infrared:Silicon" not in {g.uid for g in page.glasses}

    def search(top_k):
        page.top_k.setValue(top_k)
        with qtbot.waitSignal(page.job.completed, timeout=30000):
            page.search()
        qtbot.waitUntil(lambda: not page.job.busy, timeout=5000)
        assert page.last_metadata["settings"]["min_transmission"] == .97
        return list(page.table.model.rows), page.last_metadata["screening"]

    rows50, meta50 = search(50)
    assert len(rows50) == 50
    assert not any("Corning:HPFS 7980" in row["supplemental_glasses"] for row in rows50)
    assert meta50["eligible_unknown_transmission_count"] == 1
    assert meta50["unknown_transmission_glasses"] == ("Corning:HPFS 7980",)

    rows500, meta500 = search(500)
    assert len(rows500) == 500
    assert any("Corning:HPFS 7980" in row["supplemental_glasses"] for row in rows500)
    assert all("Infrared:Silicon" not in row["supplemental_glasses"] for row in rows500)
    assert rows500[:50] == rows50
    assert meta500["eligible_glass_count"] == meta50["eligible_glass_count"]
    assert meta500["accepted_count"] == meta50["accepted_count"] > 500
    assert "500 best candidates retained" in page.status.text()

    window.supplement_controls["Infrared:Silicon"].setChecked(True)
    rows_on, meta_on = search(50)
    assert set(rows_on[0]["supplemental_glasses"]) == {"Corning:HPFS 7980", "Infrared:Silicon"}
    assert meta_on["eligible_glass_count"] == meta50["eligible_glass_count"] + 1
    window.close()
    assert {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths} == source_hashes
