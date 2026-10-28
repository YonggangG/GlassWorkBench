"""Preservation tests use synthetic fixtures, never redistribute supplier catalogs."""
from hashlib import sha256
from pathlib import Path
import codecs
import pytest

from glass_workbench.catalogs.agf import load_agf, parse_agf, integer_token

VALID = "NM TEST 2 517642.251 1.5168 64.17 0 1\nCD 1.039612120000000001 0.00600069867 .231792344 .0200179144 1.01046945 103.560653\n"


def test_raw_typed_identity_precision_and_unknown():
    raw = "CC Unicode café\r\n! header\r\n" + VALID.replace("\n", "\r\n") + "XX extra precise 1.00000000000000000001\r\nED 7 8 2.5 0 0 77\r\n"
    doc = parse_agf(raw)
    m = doc.materials[0]
    assert doc.newline == "\r\n"
    assert m.raw_text == raw[len(doc.header):]
    assert m.records[1].tokens[0] == "1.039612120000000001"
    assert m.properties["ed"]["extra_tokens"] == ("77",)
    assert m.properties["ed"]["dpgf"] == 0
    assert "77" not in {str(v) for k, v in m.properties["ed"].items() if k != "extra_tokens"}
    assert {d.code for d in m.diagnostics} >= {"unknown_record", "extra_ed"}
    assert parse_agf(raw).materials[0].identity == m.identity
    duplicate = parse_agf(VALID + VALID).materials
    assert duplicate[0].identity != duplicate[1].identity
    assert all(any(d.code == "duplicate_source_name" for d in m.diagnostics) for m in duplicate)


def test_scientific_integer_and_invalid_no_rounding():
    doc = parse_agf(VALID.replace("TEST 2", "TEST 2.0E+00").replace("0 1\n", "0e0 1e0\n"))
    assert doc.materials[0].formula == 2
    assert doc.materials[0].properties["status"] == 1
    assert integer_token("1e1") == 10
    for token in ("2.1", "2.000000000000000001", "nan", "inf", "1e999", "1e9999999"):
        with pytest.raises(ValueError):
            integer_token(token)


@pytest.mark.parametrize("record,code", [("ED 7 8 0", "incomplete_ed"), ("IT .5 .99", "incomplete_it")])
def test_ambiguous_short_fields_not_guessed(record, code):
    m = parse_agf(VALID + record).materials[0]
    typed = m.records[-1]
    assert typed.values["unassigned_tokens"] == typed.tokens
    assert "density_g_cm3" not in typed.values
    assert "internal_transmission" not in typed.values
    assert any(d.code == code for d in m.diagnostics)
    assert m.raw_text.endswith(record)


def test_empty_placeholder_zero_absent_distinguished():
    m = parse_agf(VALID + 'ED 0 "" - 0 0\n').materials[0]
    assert m.properties["ed"]["token_states"] == ("value", "empty", "placeholder", "value", "value")
    assert m.properties["ed"]["cte1_ppm_k"] == 0
    assert m.properties["ed"]["cte2_ppm_k"] is None
    assert "td" not in m.properties


def test_all_records_and_transmission_thickness_preserved():
    m = parse_agf(VALID + "TD 1e-6 2e-8 3e-10 4e-7 5e-9 .2 20\nMD 70 .2 500 800 1\nOD 0 -1 -1 -1 -1 -1\nLD .5 .5\n" +
        "".join(f"IT .{i+3} .99 {t}\n" for i,t in enumerate((1,2,5,10,25))) + "IT .7 .9 1\nBD .5 2 3 4 99\n").materials[0]
    assert [p["thickness_mm"] for p in m.properties["transmission"]] == [1,2,5,10,25,1]
    assert m.properties["md"]["young_modulus_gpa"] == 70
    assert m.properties["birefringence"][0]["extra_tokens"] == ("99",)
    assert {d.code for d in m.diagnostics} >= {"equal_ld", "it_order", "extra_bd"}
    assert m.properties["od"]["relative_cost"] == 0
    assert "cr" in m.properties["od"]["unavailable_fields"]


@pytest.mark.parametrize("encoding,bom,expected", [("utf-16-le",codecs.BOM_UTF16_LE,"utf-16-le-bom"), ("utf-16-be",codecs.BOM_UTF16_BE,"utf-16-be-bom"), ("utf-8",b"","utf-8"), ("utf-8",codecs.BOM_UTF8,"utf-8-sig"), ("cp1252",b"","cp1252")])
def test_decoding_and_source_hash(tmp_path, encoding, bom, expected):
    p = tmp_path / "catalog.agf"
    data = bom + ("CC café\r\n" + VALID).encode(encoding)
    p.write_bytes(data)
    doc = load_agf(p)
    assert doc.encoding == expected
    assert doc.sha256 == sha256(data).hexdigest()
    assert "café" in doc.header
    if encoding == "cp1252":
        assert any(d.code == "encoding_fallback" for d in doc.materials[0].diagnostics)


def test_binary_and_invalid_decode(tmp_path):
    p = tmp_path / "bad.agf"
    p.write_bytes(b"NM\x00bad")
    with pytest.raises(ValueError):
        load_agf(p)
    p.write_bytes(b"\x81")
    with pytest.raises(UnicodeDecodeError):
        load_agf(p)
    with pytest.raises(ValueError):
        load_agf(tmp_path / "input.bgf")


def test_unknown_formula_nonfinite_and_missing_cd():
    m = parse_agf("NM X 999 CODE inf 50\n").materials[0]
    assert m.formula == 999 and m.nd is None
    assert {d.code for d in m.diagnostics} >= {"unevaluated_formula", "invalid_nm_reference", "missing_cd"}


def test_orphan_and_empty_boundary_visible():
    doc = parse_agf("CD 1 2\nNM\nNM GOOD 1 0 1.5 50\nCD 1 2 3 4 5 6\n")
    assert len(doc.materials) == 2
    assert {d.code for d in doc.diagnostics} >= {"orphan_record", "invalid_boundary"}


def test_optional_placeholder_mechanical_and_short_stress_records():
    m = parse_agf(VALID + "MD 70 .2 _ - 1\nBD .5 2\n").materials[0]
    assert not [d for d in m.diagnostics if d.severity == "error"]
    assert {d.code for d in m.diagnostics} >= {"missing_md", "incomplete_bd"}
    assert m.properties["md"]["specific_heat_j_kgk"] is None
    assert m.properties["birefringence"][0]["unassigned_tokens"] == (".5", "2")
    assert "minus_k11" not in m.properties["birefringence"][0]


def test_optional_local_reference_catalogs():
    root = Path(__file__).resolve().parents[1]
    paths = [root / n for n in ("BERMAN.AGF", "CDGM.AGF", "MISC.AGF", "SCHOTT.AGF")]
    if not all(p.exists() for p in paths):
        pytest.skip("Optional four local AGF reference catalogs absent")
    documents = [load_agf(p) for p in paths]
    assert [len(d.materials) for d in documents] == [5,331,23,369]
    assert sum(len(d.materials) for d in documents) == 728
    assert any(d.code.startswith("incomplete_") for doc in documents for d in doc.diagnostics)
    assert any(d.code == "duplicate_source_name" for d in documents[-1].diagnostics)
    for doc in documents:
        source = doc.header + "".join(m.raw_text for m in doc.materials)
        assert len(parse_agf(source).materials) == len(doc.materials)
