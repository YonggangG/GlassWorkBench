"""Optional end-to-end export regression using the user's first-sheet catalogs."""
from hashlib import sha256
from pathlib import Path

import pytest

from glass_workbench.catalogs.agf import load_agf
from glass_workbench.catalogs.agf_export import material_comment
from glass_workbench.catalogs.loader import discover_catalogs, load_catalog
from glass_workbench.ui.main_window import MainWindow


def test_real_63_material_basket_repairs_name_and_preserves_sources(qtbot, tmp_path):
    root = Path(__file__).resolve().parents[1]
    workbooks = discover_catalogs(root)
    berman = root / "BERMAN.AGF"
    if len(workbooks) != 2 or not berman.exists():
        pytest.skip("Official Excel and AGF catalogs are external")
    sources = [*workbooks, berman]
    original_hashes = {path: sha256(path.read_bytes()).hexdigest() for path in sources}
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.imported(([load_catalog(path) for path in workbooks], []))
    tab = window.agf
    tab.imported((tab.generation, [load_agf(berman)], []))
    window.supplier.setCurrentText("CDGM")
    window.preset.setCurrentText("H- or N-")
    window.melt.setCurrentText("MA")
    assert len(tab.source_model.rows) == 63
    tab.selected_ids = {row["identity"] for row in tab.source_model.rows}
    tab.add_selected()
    assert len(tab.basket) == 63
    repaired = next(item for item in tab.basket.values() if item.material.name == "H-K9L*")
    assert repaired.export_name == "H-K9L_ST"
    assert repaired.material.name == "H-K9L*"
    tab.acknowledge.setChecked(True)
    preview = tab.validate_export()
    assert preview.valid, preview.errors
    assert tab.export_button.isEnabled()
    output, manifest = tab.save_to(tmp_path / "first_sheet_and_berman.agf")
    assert manifest.exists()
    reparsed = load_agf(output)
    assert len(reparsed.materials) == 63
    assert "H-K9L_ST" in {material.name for material in reparsed.materials}
    for item, material, entry in zip(tab.basket.values(), reparsed.materials, preview.manifest["materials"]):
        before = [(r.mnemonic, r.tokens) for r in item.material.records if r.mnemonic not in {"", "NM", "GC"}]
        after = [(r.mnemonic, r.tokens) for r in material.records if r.mnemonic not in {"", "NM", "GC"}]
        assert after == before
        assert material.records[0].tokens[1:] == item.material.records[0].tokens[1:]
        original = material_comment(item.material)
        first_line = original.splitlines()[0] if original else ""
        assert item.glass_comment == (first_line if first_line != original else None)
        assert material_comment(material) == first_line
        assert entry["original_glass_comment"] == original
        assert entry["effective_glass_comment"] == first_line
    assert {path: sha256(path.read_bytes()).hexdigest() for path in sources} == original_hashes
    window.close()
