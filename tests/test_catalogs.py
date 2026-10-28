from pathlib import Path
from dataclasses import replace
import pytest
from openpyxl import Workbook
from glass_workbench.catalogs.loader import load_catalog, discover_catalogs
from glass_workbench.optics.dispersion import catalog_index, refractive_index

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope="module")
def catalogs():
    paths = discover_catalogs(ROOT)
    if len(paths) != 2:
        pytest.skip("External licensed catalog workbooks not present")
    return {c.supplier:c for c in map(load_catalog,paths)}


def test_discovery_excludes_legacy(tmp_path):
    for name in ["CDGM202609.xlsx","schott-optical-glass-overview-excel-format-en 202501113.xlsx",
                 "Glasses_1550nm.xlsx","Corning_FusedSilica.csv","random.xlsx"]:
        (tmp_path/name).touch()
    assert len(discover_catalogs(tmp_path)) == 2
    assert discover_catalogs(tmp_path/"missing") == []


def test_first_sheet_only_and_reject_wrong_schema(tmp_path):
    w = Workbook();w.active.title = "wrong";w.active["A1"] = "Glasses"
    w.create_sheet("optical glass")["A1"] = "Glass"
    p = tmp_path/"renamed.xlsx";w.save(p)
    with pytest.raises(ValueError,match="first-sheet"):
        load_catalog(p)
    with pytest.raises(ValueError,match="Legacy"):
        load_catalog(tmp_path/"Glasses_1550nm.xlsx")
    with pytest.raises(ValueError,match="xlsx"):
        load_catalog(tmp_path/"Corning_FusedSilica.csv")


def test_source_counts_filters_and_first_sheet(catalogs):
    cd,sc = catalogs["CDGM"],catalogs["SCHOTT"]
    assert (len(cd.glasses),len(sc.glasses)) == (328,122)
    assert cd.sheet == "optical glass" and sc.sheet == "Preferred glasses"
    assert sum(g.name.startswith("H-") for g in cd.glasses) == 209
    assert sum(g.name.startswith("N-") for g in sc.glasses) == 86
    assert sum(g.melt_frequency == "MA" for g in cd.glasses) == 64
    assert sum(g.name.startswith("H-") and g.melt_frequency == "MA" for g in cd.glasses) == 58
    assert sum(g.dispersion_model == "sellmeier" for g in cd.glasses) == 279
    assert sum(g.thermal is not None for g in cd.glasses) == 310
    assert all(g.source_sheet == c.sheet and g.source_hash == c.sha256 for c in (cd,sc) for g in c.glasses)
    assert max(g.source_row for g in cd.glasses) == 330
    assert max(g.source_row for g in sc.glasses) == 126
    assert all(g.name != "over!" for g in cd.glasses)


def test_mapping_units_codes_and_missing(catalogs):
    cd = {g.name:g for g in catalogs["CDGM"].glasses}
    sc = {g.name:g for g in catalogs["SCHOTT"].glasses}
    assert cd["H-FK55"].dispersion == (.534931974,.839050115,.886511647,.00128059279,.0116444604,143.252236)
    assert cd["H-FK55"].cte == pytest.approx(11.4e-6)
    assert sc["N-BK7"].cte == pytest.approx(7.1e-6)
    assert sc["LASF35"].code == "022291.541"
    assert cd["H-FK55"].price == 151
    assert sc["LASF35"].price == 36.7
    assert all(isinstance(g.code,str) for c in catalogs.values() for g in c.glasses)
    assert all(g.transmission for c in catalogs.values() for g in c.glasses)
    assert sum(g.thermal is None for g in cd.values()) == 18


def test_checkpoint_audit_and_known_air_axis_benchmark(catalogs):
    sc = {g.name:g for g in catalogs["SCHOTT"].glasses}
    assert catalog_index(sc["N-BK7"],1.55) == pytest.approx(1.5006520430195947,abs=1e-13)
    assert refractive_index(sc["N-BK7"],1.55) == pytest.approx(1.5006572571349939,abs=1e-12)
    for g in catalogs["SCHOTT"].glasses:
        assert not any("MISMATCH" in w for w in g.warnings)
        for wave,n in g.checkpoints:
            assert refractive_index(g,wave) == pytest.approx(n,abs=1.1e-5)
    cd = {g.name:g for g in catalogs["CDGM"].glasses}
    assert any("DISPERSION_CHECKPOINT_MISMATCH" in w for w in cd["ZF11"].warnings)
    with pytest.raises(ValueError,match="CHECKPOINT"):
        refractive_index(cd["ZF11"],.55)
    assert refractive_index(cd["ZF11"],.55,True) > 1
    for g in cd.values():
        if any("DISPERSION_CHECKPOINT_MISMATCH" in w for w in g.warnings):
            continue
        for wave,n in g.checkpoints:
            assert refractive_index(g,wave) == pytest.approx(n,abs=1e-5)
