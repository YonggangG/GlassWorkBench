"""Global AGF filtering is independent of records and persistent export snapshots."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QItemSelectionModel

from glass_workbench.catalogs.agf import parse_agf
from glass_workbench.contracts import Catalog, Glass
from glass_workbench.ui.agf import AgfTab
from glass_workbench.ui.main_window import MainWindow, filtered_glasses

POPULAR = "Popular: (CDGM H- ∩ MA) or SCHOTT N-"


def glass(name, supplier="CDGM", melt="", row=2, digest="v1"):
    return Glass(supplier, name, "500600", 1.5, 60, melt_frequency=melt,
                 dispersion_model="polynomial", dispersion=(2.25, 0, 0, 0, 0, 0),
                 source_file=f"{supplier}.xlsx", source_sheet="First", source_row=row,
                 source_hash=digest)


def catalog(glasses, supplier="CDGM", digest="v1"):
    return Catalog(supplier, f"{supplier}.xlsx", "First", digest, glasses)


def document(names, path="CDGM.AGF"):
    return parse_agf("".join(f"NM {name} 1 0 1.5 60 0 0\nCD 2.25 0 0 0 0 0\nLD 0.4 0.7\nOD 1 0 1 0 0 0\n"
                             for name in names), source_path=path)


def import_docs(tab, *docs):
    tab.imported((tab.generation, docs, []))


def names(tab):
    return {row["name"] for row in tab.source_model.rows}


def select_source(tab, doc):
    key = tab.material_sources[doc.materials[0].identity]
    tab.source_filter.setCurrentIndex(tab.source_filter.findData(key))
    return key


@pytest.mark.parametrize("state", [
    {}, {"supplier": "CDGM"}, {"supplier": "SCHOTT"}, {"preset": "H- or N-"},
    {"preset": POPULAR}, {"preset": POPULAR, "melt": "MA"}, {"melt": "MA"},
    {"search": "h-a"}, {"supplier": "SCHOTT", "melt": "MA"},
])
def test_workbook_global_filter_parity(qtbot, state):
    tab = AgfTab()
    qtbot.addWidget(tab)
    cdgm = [glass("H-A", melt="MA"), glass("H-B", melt="A", row=3), glass("K9", melt="MA", row=4)]
    schott = [glass("N-A", "SCHOTT"), glass("F2", "SCHOTT", row=3)]
    tab.update_workbooks([catalog(cdgm), catalog(schott, "SCHOTT")])
    tab.set_global_filters(**state)
    assert names(tab) == {g.name for g in filtered_glasses(cdgm + schott, **state)}
    assert len(tab.workbook_glasses) == 5


def test_imported_metadata_is_informational_under_active_global_filters(qtbot):
    tab = AgfTab()
    qtbot.addWidget(tab)
    cdgm = [glass("H-MA", melt="MA"), glass("H-A", melt="A", row=3),
            glass("H-DUP", melt="MA", row=4), glass("H-DUP", melt="MA", row=5)]
    tab.update_workbooks([catalog(cdgm), catalog([glass("N-MATCH", "SCHOTT")], "SCHOTT")])
    c = document(["H-MA", "H-A", "H-DUP", "H-NO-MATCH"])
    s = document(["N-MATCH", "N-UNMATCHED"], "SCHOTT.agf")
    unknown = document(["H-MA", "N-UNMATCHED"], "mixed.agf")
    tab.set_global_filters(preset=POPULAR)
    import_docs(tab, c, s, unknown)
    imported_ids = {r["identity"] for r in tab.source_model.rows if not tab.materials[r["identity"]].generated}
    expected_imports = {m.identity for doc in (c, s, unknown) for m in doc.materials}
    assert imported_ids == expected_imports
    assert tab.filter_metadata[c.materials[2].identity]["exact_name_match_count"] == 2
    assert tab.filter_metadata[c.materials[2].identity]["melt_category"] is None
    assert tab.filter_metadata[c.materials[3].identity]["melt_category"] is None
    tab.set_global_filters(preset=POPULAR, melt="MA")
    imported_ids = {r["identity"] for r in tab.source_model.rows if not tab.materials[r["identity"]].generated}
    assert imported_ids == expected_imports
    tab.inspect(c.materials[0])
    assert '"browser_metadata"' in tab.details.toPlainText()
    assert "Informational only; imported AGF entries bypass all global filters" in tab.details.toPlainText()
    for value in ('"source_sha256": "v1"', '"source_sheet": "First"', '"source_row": 2'):
        assert value in tab.details.toPlainText()
    assert tab.raw.toPlainText() == c.materials[0].raw_text
    assert not c.materials[0].provenance.get("filter_only_metadata")
    tab.set_global_filters()
    assert len(tab.source_model.rows) == len(tab.materials)


@pytest.mark.parametrize("filename, expected", [("CDGM.AGF", "CDGM"), ("cdgm.agf", "CDGM"),
    ("SCHOTT.agf", "SCHOTT"), ("my-CDGM.agf", "Unknown"), ("CDGM-copy.agf", "Unknown"),
    ("BERMAN.AGF", "Unknown"), ("MISC.agf", "Unknown")])
def test_supplier_exact_stem_and_visible_provisional_label(qtbot, filename, expected):
    tab = AgfTab()
    qtbot.addWidget(tab)
    doc = document(["H-MA"], filename)
    import_docs(tab, doc)
    key = select_source(tab, doc)
    assert tab.source_supplier.isEnabled()
    assert tab.source_supplier.currentText() == expected
    assert tab.source_suppliers[key][0] == expected
    if expected != "Unknown":
        assert "filename-based" in tab.source_filter.currentText()
        assert "filename-based" in tab.source_model.rows[0]["source"]
    tab.set_global_filters(supplier="SCHOTT", search="nonexistent-name", melt="MA", preset=POPULAR)
    assert names(tab) == {"H-MA"}
    assert "informational" in tab.source_supplier.toolTip()
    assert "informational only" in tab.supplier_basis.text()
    assert tab.source_supplier.currentText() == expected  # Never synced to global supplier.
    tab.source_supplier.setCurrentText("Corning")
    assert tab.source_suppliers[key] == ("Corning", "explicit source assignment")
    tab.set_global_filters(supplier="Corning")
    assert names(tab) == {"H-MA"}
    tab.source_supplier.setCurrentText("Unknown")
    assert names(tab) == {"H-MA"}
    tab.set_global_filters()
    assert names(tab) == {"H-MA"}


def test_assignment_recomputes_same_supplier_exact_name_only(qtbot):
    tab = AgfTab()
    qtbot.addWidget(tab)
    tab.update_workbooks([catalog([glass("H-A", melt="MA")])])
    first = document(["H-A", "h-a", "H-A-X"], "mixed.agf")
    other = document(["H-A"], "other.agf")
    import_docs(tab, first, other)
    select_source(tab, first)
    tab.source_supplier.setCurrentText("CDGM")
    tab.set_global_filters(melt="MA")
    assert names(tab) == {"H-A", "h-a", "H-A-X"}
    assert tab.filter_metadata[first.materials[0].identity]["melt_category"] == "MA"
    assert all(tab.filter_metadata[m.identity]["melt_category"] is None for m in first.materials[1:])
    tab.source_filter.setCurrentIndex(0)
    assert len(tab.source_model.rows) == 5  # One workbook plus all four imported entries.
    assert tab.filter_metadata[other.materials[0].identity]["melt_category"] is None
    select_source(tab, first)
    tab.source_supplier.setCurrentText("SCHOTT")
    assert names(tab) == {"H-A", "h-a", "H-A-X"}
    assert tab.filter_metadata[first.materials[0].identity]["melt_category"] is None
    tab.set_global_filters()
    import_docs(tab, first)
    assert tab.source_supplier.currentText() == "SCHOTT"  # Explicit correction survives reimport.
    assert not any(m.generated for m in first.materials)


def test_current_reload_replaces_lookup_retains_basket_and_original_glasses(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    old = glass("H-MA", melt="MA")
    window.imported(([catalog([old])], []))
    tab = window.agf
    doc = document(["H-MA"])
    import_docs(tab, doc)
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    tab.rename_item(doc.materials[0].identity, "IMPORTED-H-MA")
    basket = dict(tab.basket)
    tab.acknowledge.setChecked(True)
    preview = tab.validate_export()
    assert preview.valid
    window.melt.setCurrentText("MA")
    assert len(tab.source_model.rows) == 2
    new = replace(old, melt_frequency="A", source_hash="v2")
    window.imported(([catalog([new], digest="v2")], []))
    assert len(tab.source_model.rows) == 2  # Historical MA snapshot and imported AGF remain.
    workbook_ids = {r["identity"] for r in tab.source_model.rows if r["identity"] in tab.workbook_glasses}
    assert {tab.workbook_glasses[identity].source_hash for identity in workbook_ids} == {"v1"}
    assert doc.materials[0].identity in tab.selected_ids
    meta = tab.filter_metadata[doc.materials[0].identity]
    assert meta["exact_name_match_count"] == 1
    assert meta["melt_category"] == "A"
    assert meta["workbook_match"]["source_sha256"] == "v2"
    assert tab.basket == basket
    assert tab.preview is preview
    assert tab.acknowledge.isChecked()
    window.imported(([catalog([glass("OTHER", digest="v3")], digest="v3")], []))
    assert tab.filter_metadata[doc.materials[0].identity]["workbook_match"] is None
    assert tab.basket == basket
    window.close()


def test_global_prunes_only_workbook_selection_and_add_guards(qtbot):
    tab = AgfTab()
    qtbot.addWidget(tab)
    tab.update_workbooks([catalog([glass("H-WORK"), glass("N-WORK", row=3)])])
    doc = document(["H-A", "N-B", "H-C"])
    import_docs(tab, doc)
    imported_ids = {m.identity for m in doc.materials}
    ids = set(tab.materials)
    for row in range(len(tab.source_model.rows)):
        tab.source_view.selectionModel().select(tab.source_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert tab.selected_ids == ids
    tab.search.setText("H-A")
    assert tab.selected_ids == ids
    tab.set_global_filters(search="H-")
    allowed = imported_ids | {identity for identity, g in tab.workbook_glasses.items() if g.name == "H-WORK"}
    assert tab.selected_ids == allowed
    assert names(tab) == {"H-A"}
    assert "3 hidden by local filters" in tab.selection_label.text()
    assert "4 globally eligible" in tab.selection_label.text()
    tab.selected_ids = ids  # Stale/programmatic workbook selections cannot bypass eligibility.
    tab.add_selected()
    assert set(tab.basket) == tab.selected_ids == allowed
    tab.set_global_filters(supplier="SCHOTT", search="nonexistent")
    assert tab.selected_ids == imported_ids
    assert names(tab) == {"H-A"}
    assert set(tab.basket) == allowed
    tab.search.clear()
    assert names(tab) == {"H-A", "N-B", "H-C"}
    assert len(tab.source_view.selectionModel().selectedRows()) == 3


def test_active_globals_before_import_and_assignment_leave_imports_eligible(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.supplier.setCurrentText("CDGM")
    window.search.setText("H-")
    window.preset.setCurrentText(POPULAR)
    window.melt.setCurrentText("MA")
    window.apply_filters()
    tab = window.agf
    doc = document(["H-A", "N-B"])
    import_docs(tab, doc, document(["H-UNKNOWN"], "unknown.agf"))
    assert names(tab) == {"H-A", "N-B", "H-UNKNOWN"}
    select_source(tab, doc)
    assert names(tab) == {"H-A", "N-B"}
    tab.source_view.selectRow(0)
    selected = set(tab.selected_ids)
    assert selected
    tab.source_supplier.setCurrentText("Unknown")
    assert tab.selected_ids == selected
    assert names(tab) == {"H-A", "N-B"}
    window.close()
