from dataclasses import replace
from hashlib import sha256
from math import sqrt
from pathlib import Path
from types import SimpleNamespace
import codecs
import json
import os
import pytest

from glass_workbench.contracts import Glass
from glass_workbench.catalogs.agf import load_agf, parse_agf
from glass_workbench.catalogs.agf_export import ExportItem, ExportWriteError, build_export, glass_to_agf, write_export
from glass_workbench.optics.dispersion import air_to_vacuum


RAW = "NM SAMPLE 2 517642.251 1.5168 64.17 0 1\nCD 1.039612120000000001 .00600069867 .231792344 .0200179144 1.01046945 103.560653\n"


def glass(**kwargs):
    defaults = dict(supplier="Example", name="N-BK7", code="517642", nd=1.5168, vd=64.17,
        dispersion=(1.03961212, .231792344, 1.01046945, .00600069867, .0200179144, 103.560653),
        thermal=(1e-6,2e-8,3e-10,4e-7,5e-9,.2), cte=7.1e-6, reference_temperature=20,
        wavelength_range=(air_to_vacuum(.365), air_to_vacuum(1.014)),
        transmission=((.4,.99),(.5,.999)), price=1.2, source_file="source.xlsx", source_hash="abc", source_sheet="Sheet1", source_row=4)
    defaults.update(kwargs)
    return Glass(**defaults)


def valid_preview():
    return build_export([ExportItem(parse_agf(RAW).materials[0])])


def test_rename_only_name_preserves_precision_and_headers():
    material = parse_agf("CC Original Unicode 中文\n" + RAW + "XX unknown payload\n").materials[0]
    preview = build_export([ExportItem(material, "RENAMED")])
    assert preview.valid
    reloaded = parse_agf(preview.text).materials[0]
    assert reloaded.raw_text == material.raw_text.replace("SAMPLE", "RENAMED").replace("\n", "\r\n")
    assert preview.manifest["materials"][0]["source_header"] == "CC Original Unicode 中文\n"
    assert "unknown_record" in str(preview.manifest["materials"][0]["diagnostics"])
    assert "1.039612120000000001" in preview.text


def test_collision_and_invalid_names_always_block():
    m = parse_agf(RAW).materials[0]
    assert not build_export([ExportItem(m),ExportItem(m,"sample")], preserve_invalid=True).valid
    for name in ("", "two words", "x\nNM BAD 1 0 1 1", "X"*33):
        assert not build_export([ExportItem(m,name)], preserve_invalid=True).valid


def test_archival_does_not_bypass_boundaries_or_generated_errors():
    material = parse_agf(RAW + "ED 7 8 0\n").materials[0]
    assert not build_export([ExportItem(material)]).valid
    archival = build_export([ExportItem(material)], preserve_invalid=True)
    assert archival.valid and archival.manifest["materials"][0]["archival_only"]
    assert "ED 7 8 0" in archival.text
    assert not archival.manifest["validated_for_opticstudio"]
    orphan = parse_agf("CD 1\n" + RAW).materials[0]
    assert not build_export([ExportItem(orphan)], preserve_invalid=True).valid
    invalid = glass_to_agf(glass(dispersion=(1,)))
    assert not build_export([ExportItem(invalid)], preserve_invalid=True, acknowledge_warnings=True).valid


def test_sellmeier_pairing_independent_indices_and_no_mutation():
    source = glass()
    before = repr(source)
    material = glass_to_agf(source)
    assert repr(source) == before
    c = material.properties["cd"]["coefficients"]
    assert c == (1.03961212,.00600069867,.231792344,.0200179144,1.01046945,103.560653)
    # Independent published N-BK7 coefficients/checkpoint, not application evaluator.
    q = 1.55**2
    index = sqrt(1 + sum(c[i]*q/(q-c[i+1]) for i in (0,2,4)))
    assert index == pytest.approx(1.5006520430195947, abs=1e-14)
    assert material.properties["ld"]["minimum_um"] == pytest.approx(.365, abs=1e-12)
    assert material.properties["ld"]["maximum_um"] == pytest.approx(1.014, abs=1e-12)
    assert material.properties["td"]["reference_temperature_c"] == 20
    assert [v["thickness_mm"] for v in material.properties["transmission"]] == [10,10]
    assert not build_export([ExportItem(material)]).valid
    assert build_export([ExportItem(material)], acknowledge_warnings=True).valid


def test_polynomial_coefficients_independent_formula():
    coefficients = (2.25,.001,.002,.0003,.00004,.000005)
    m = glass_to_agf(glass(dispersion_model="polynomial",dispersion=coefficients))
    assert m.formula == 1 and m.properties["cd"]["coefficients"] == coefficients
    for wavelength in (.4,.55,.9):
        q = wavelength*wavelength
        expected = sqrt(2.25+.001*q+.002/q+.0003/q**2+.00004/q**3+.000005/q**4)
        c = m.properties["cd"]["coefficients"]
        actual = sqrt(c[0]+c[1]*q+sum(c[k+2]/q**(k+1) for k in range(4)))
        assert actual == pytest.approx(expected, abs=1e-15)


def test_optional_metadata_no_fabricated_zero_or_pgf():
    m = glass_to_agf(glass(pgf=.535,thermal=None))
    assert "ed" not in m.properties and "td" not in m.properties
    assert "-1" in next(r for r in m.records if r.mnemonic == "OD").tokens
    assert {d.code for d in m.diagnostics} >= {"omitted_ed","omitted_td","derived_ld","supplier_price"}
    source = glass()
    metadata = SimpleNamespace(cte1=7.1e-6,cte2=8.2e-6,density=2.51,dpgf=-.0009,cte2_temperature_range=(20,300))
    object.__setattr__(source,"agf_metadata",metadata)
    complete = glass_to_agf(source)
    assert complete.properties["ed"]["cte1_ppm_k"] == pytest.approx(7.1)
    assert complete.properties["ed"]["cte2_ppm_k"] == pytest.approx(8.2)
    assert complete.properties["ed"]["dpgf"] == -.0009
    assert any(d.code == "cte2_interval" for d in complete.diagnostics)


@pytest.mark.parametrize("changes", [dict(supplemental=True),dict(dispersion_model="silicon"),dict(dispersion=(float("nan"),)*6),dict(nd=None),dict(transmission=((.5,.9),(.4,.8))),dict(transmission=tuple((.3+i*.001,.9) for i in range(101)))])
def test_unsupported_or_invalid_conversion_stays_in_basket(changes):
    m = glass_to_agf(glass(**changes))
    preview = build_export([ExportItem(m)], acknowledge_warnings=True, preserve_invalid=True)
    assert not preview.valid
    assert preview.manifest["material_count"] == 1


def test_write_encoding_manifest_and_source_guard(tmp_path):
    source = tmp_path / "source.agf"
    source.write_text(RAW)
    source_bytes = source.read_bytes()
    m = load_agf(source).materials[0]
    preview = build_export([ExportItem(m)])
    out, metadata = write_export(preview,tmp_path / "merged.agf",source_paths=[source])
    assert out.read_bytes().startswith(codecs.BOM_UTF16_LE)
    assert b"\r\x00\n\x00" in out.read_bytes()
    manifest = json.loads(metadata.read_text(encoding="utf-8"))
    assert manifest["output_sha256"] == sha256(out.read_bytes()).hexdigest()
    assert len(load_agf(out).materials) == 1
    assert source.read_bytes() == source_bytes
    with pytest.raises(ValueError):
        write_export(preview,source,overwrite=True)
    with pytest.raises(FileExistsError):
        write_export(preview,out)
    write_export(preview,out,overwrite=True)


def test_all_sources_metadata_hardlink_and_installed_alias_protected(tmp_path):
    preview = valid_preview()
    extra = tmp_path / "unselected.xlsx"
    extra.write_text("must survive")
    alias = tmp_path / "alias.agf"
    os.link(extra, alias)
    with pytest.raises(ValueError):
        write_export(preview,alias,source_paths=[extra],overwrite=True)
    metadata = tmp_path / "new.metadata.json"
    os.link(extra,metadata)
    with pytest.raises(ValueError):
        write_export(preview,tmp_path / "new.agf",source_paths=[extra],overwrite=True)
    install = tmp_path / "Glasscat"
    install.mkdir()
    with pytest.raises(ValueError):
        write_export(preview,install / "new.agf")
    assert extra.read_text() == "must survive"


def test_pair_failure_reports_completed_files_and_cleans_stage(tmp_path, monkeypatch):
    import glass_workbench.catalogs.agf_export as module
    real_replace = module.os.replace
    count = 0
    def broken_replace(src,dst):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated manifest failure")
        return real_replace(src,dst)
    monkeypatch.setattr(module.os,"replace",broken_replace)
    output = tmp_path / "partial.agf"
    with pytest.raises(ExportWriteError) as info:
        write_export(valid_preview(),output,overwrite=True)
    assert info.value.written_paths == (output,)
    assert output.exists() and not output.with_suffix(".metadata.json").exists()
    assert not list(tmp_path.glob(".agf-stage-*"))


def test_mutable_manifest_cannot_bypass_source_or_validation(tmp_path):
    source = tmp_path / "source.agf"
    source.write_text(RAW)
    preview = build_export([ExportItem(load_agf(source).materials[0])])
    preview.manifest["source_paths"].clear()
    with pytest.raises(ValueError):
        write_export(preview,source,overwrite=True)
    assert source.read_text() == RAW
    preview = valid_preview()
    text = preview.text + "NM INJECTED 2 0 1.5 50\r\n"
    preview.manifest["output_sha256"] = sha256(codecs.BOM_UTF16_LE + text.encode("utf-16-le")).hexdigest()
    with pytest.raises(ValueError):
        write_export(replace(preview,text=text),tmp_path / "out.agf")


def test_tampered_preview_and_empty_basket_blocked(tmp_path):
    assert not build_export([]).valid
    preview = valid_preview()
    with pytest.raises(ValueError):
        write_export(replace(preview,text=preview.text+"! tampered\r\n"),tmp_path / "out.agf")
