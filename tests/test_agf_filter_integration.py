"""Optional real-catalog regression for global AGF browser filtering."""
from pathlib import Path

import pytest

from glass_workbench.catalogs.agf import load_agf
from glass_workbench.catalogs.loader import discover_catalogs, load_catalog
from glass_workbench.ui.main_window import MainWindow


def test_real_catalog_global_filters_preserve_basket(qtbot):
    root = Path(__file__).resolve().parents[1]
    workbook_paths = discover_catalogs(root)
    agf_paths = [root / name for name in ("BERMAN.AGF", "CDGM.AGF", "MISC.AGF", "SCHOTT.AGF")]
    if len(workbook_paths) != 2 or not all(path.exists() for path in agf_paths):
        pytest.skip("Official Excel and AGF catalogs are external")
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.imported(([load_catalog(path) for path in workbook_paths], []))
    tab = window.agf
    tab.imported((tab.generation, [load_agf(path) for path in agf_paths], []))
    assert len(tab.materials) == len(tab.source_model.rows) == 1178
    imported_ids = set(tab.materials) - set(tab.workbook_glasses)
    assert len(imported_ids) == 728
    window.supplier.setCurrentText("CDGM")
    assert len(tab.source_model.rows) == 328 + 728
    window.preset.setCurrentText("Popular: (CDGM H- ∩ MA) or SCHOTT N-")
    assert len(tab.source_model.rows) == 58 + 728 == 786
    imported_row = next(i for i, row in enumerate(tab.source_model.rows) if row["identity"] in imported_ids)
    tab.source_view.selectRow(imported_row)
    selected = set(tab.selected_ids)
    tab.add_selected()
    snapshot = dict(tab.basket)
    assert len(snapshot) == 1
    window.search.setText("nonexistent-name")
    qtbot.waitUntil(lambda: len(tab.source_model.rows) == 728, timeout=3000)
    assert {row["identity"] for row in tab.source_model.rows} == imported_ids
    assert tab.selected_ids == selected
    assert tab.basket == snapshot
    window.search.clear()
    window.supplier.setCurrentText("All suppliers")
    assert len(tab.source_model.rows) == 144 + 728 == 872
    window.melt.setCurrentText("MA")
    assert len(tab.source_model.rows) == 58 + 728 == 786
    assert tab.basket == snapshot
    window.close()
