from dataclasses import replace

from glass_workbench.contracts import Glass
from glass_workbench.ui.main_window import MainWindow, filtered_glasses
from glass_workbench.ui.maps import MapsTab


def supplemental_records():
    silica = Glass("Corning", "HPFS 7980", "7980", 1.45846, 67.8, .53,
                   supplemental=True, thermal_model="corning_7980")
    silicon = Glass("Infrared", "Silicon", "Si", None, None,
                    supplemental=True, visible_applicable=False, thermal_model="silicon_charms")
    ordinary = Glass("CDGM", "H-K9L", "517642", 1.5168, 64.2, .5359, melt_frequency="MA")
    return [ordinary, silica, silicon]


def test_supplements_union_filters_respect_supplier_and_prefix():
    records = supplemental_records()
    selected = [g.uid for g in records if g.supplemental]
    assert len(filtered_glasses(records)) == 1
    assert len(filtered_glasses(records, preset="H- or N-", melt="MA", supplements=selected)) == 3
    assert len(filtered_glasses(records, preset="Popular: (CDGM H- ∩ MA) or SCHOTT N-", supplements=selected)) == 3
    assert [g.name for g in filtered_glasses(records, supplier="Infrared", supplements=selected)] == ["Silicon"]
    assert [g.name for g in filtered_glasses(records, search="HPFS", supplements=selected)] == ["HPFS 7980"]
    assert not filtered_glasses(records, supplier="SCHOTT", supplements=selected)


def test_ir_material_in_table_not_visible_map(qtbot):
    page = MapsTab()
    qtbot.addWidget(page)
    page.update_glasses(supplemental_records(), {})
    assert len(page.table.model.rows) == 3
    assert all(g.name != "Silicon" for _, records in page.collections for g in records)
    page.highlight.setText("Silicon")
    assert all(g.name != "Silicon" for _, records in page.collections for g in records)
    row = next(r for r in page.table.model.rows if r["glass"] == "Silicon")
    assert row["nd"] is None and row["Vd"] is None
    assert "IR-only" in row["visible_map"]
    assert row["thermal_model"] == "silicon_charms"


def test_supplements_loaded_offline_and_individually_toggle(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    assert len(window.maps.glasses) == 2
    assert not window.triplet.unknown_transmission.isChecked()
    window.preset.setCurrentText("H- or N-")
    window.melt.setCurrentText("MA")
    assert len(window.maps.glasses) == 2
    window.supplement_controls["Infrared:Silicon"].setChecked(False)
    assert [g.name for g in window.maps.glasses] == ["HPFS 7980"]
    metadata = window.provenance()
    assert metadata["workbook_first_sheet_only"]
    assert metadata["filters"]["selected_supplements"] == ["Corning:HPFS 7980"]
    assert len(metadata["supplemental_sources"]) == 2
    window.supplier.setCurrentText("SCHOTT")
    assert not window.maps.glasses
    window.close()
