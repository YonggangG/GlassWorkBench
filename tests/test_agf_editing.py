"""Pure allocation/comment editing and preservation/security regressions."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from glass_workbench.catalogs.agf import load_agf, parse_agf
from glass_workbench.catalogs.agf_export import (
    DEFAULT_CATALOG_COMMENT, ExportItem, allocate_export_items, build_export,
    glass_to_agf, material_comment, write_export,
)
from glass_workbench.contracts import Glass


RAW = "NM SAMPLE 2 517642.251 1.5168 64.17 0 1 3 EXTRA\nCD 1.039612120000000001 .00600069867 .231792344 .0200179144 1.01046945 103.560653\n"


def material(name="SAMPLE", extra="", header=""):
    return parse_agf(header + RAW.replace("SAMPLE", name) + extra).materials[0]


def effective(items):
    return [item.export_name if item.export_name is not None else item.material.name for item in items]


def test_allocation_repairs_only_new_names_and_reserves_batch_first():
    old = ExportItem(material(), "h-k9l_st", "manual comment")
    incoming = (material("H-K9L*"), material("H-K9L_ST_2"), material("h-k9l*"), material("VALID"))
    allocated = allocate_export_items(iter(incoming), iter([old]))
    assert effective(allocated) == ["H-K9L_ST_3", "H-K9L_ST_2", "h-k9l_ST_4", "VALID"]
    assert allocated == allocate_export_items(incoming, [old])
    assert old.export_name == "h-k9l_st" and old.glass_comment == "manual comment"
    assert all(item.material is source for item, source in zip(allocated, incoming))
    assert allocated[1].export_name is None and allocated[3].export_name is None
    assert len(allocated) == len(incoming)


@pytest.mark.parametrize(("name", "expected"), [
    ("H-K9L*", "H-K9L_ST"), ("A/B:中?", "A_B___"),
    ("A B\tC", "A_B_C"), ("", "GLASS"), ("中", "_"),
    ("X" * 33, "X" * 32), ("A" * 31 + "*", "A" * 31 + "_"),
    ("a-_.+()012", "a-_.+()012"),
])
def test_allocation_ascii_policy_and_fallback(name, expected):
    # An immutable source snapshot can have a bad name without constructing bad AGF.
    source = replace(material(), name=name)
    items = allocate_export_items([source])
    assert effective(items) == [expected]
    assert expected.isascii() and 0 < len(expected) <= 32
    assert source.name == name


def test_long_name_suffix_truncation_and_casefold_duplicates():
    items = allocate_export_items([material("X" * 33), material("x" * 33), material("X" * 32)])
    assert effective(items) == ["X" * 30 + "_2", "x" * 30 + "_3", "X" * 32]
    first, second = material("DUP"), material("dup")
    assert first.identity != second.identity
    items = allocate_export_items([first, second])
    assert all(item.export_name is None for item in items)
    assert any("Duplicate output name" in error for error in build_export(items).errors)


def test_lower_level_unchanged_import_policy_and_diagnostics_retained():
    source = material("H-K9L*", "ED 1 2\n")
    assert allocate_export_items([source])[0].material.diagnostics == source.diagnostics
    assert not build_export(allocate_export_items([source])).valid
    assert any("incomplete_ed" in error for error in build_export(allocate_export_items([source])).errors)
    # The lower-level exporter still permits unchanged imported nonconservative names.
    assert build_export([ExportItem(material("中*"))]).valid
    generated = glass_to_agf(Glass(
        supplier="test", name="two words", code="", nd=1.5, vd=50,
        dispersion=(1, 2, 3, 4, 5, 6), wavelength_range=(.4, .7),
    ))
    repaired = allocate_export_items([generated])
    assert effective(repaired) == ["two_words"]
    preview = build_export(repaired, acknowledge_warnings=True, preserve_invalid=True)
    assert not preview.valid
    assert any("invalid_name" in error for error in preview.errors)
    assert any("invalid_formula" in error for error in preview.errors)


@pytest.mark.parametrize(("name", "alias"), [("H-K9L*", "H-K9L_ST"), ("中/", "__")])
def test_generated_token_safe_invalid_name_exports_with_alias(name, alias):
    source = glass_to_agf(Glass(supplier="test", name=name, code="", nd=1.5, vd=50,
                               dispersion=(1, 2, 3, 4, 5, 6), wavelength_range=(.4, .7)))
    items = allocate_export_items([source])
    assert effective(items) == [alias]
    preview = build_export(items, acknowledge_warnings=True)
    assert preview.valid
    assert source.name == name and items[0].material is source
    restored = parse_agf(preview.text).materials[0]
    assert restored.name == alias
    assert restored.records[0].tokens[1:] == source.records[0].tokens[1:]


def test_untouched_comments_and_gc_only_accessor():
    source = material(extra="gc   first 中文  \nCC local catalog\n! note\nGC second\nXX unknown\n\n", header="CC source header\n")
    preview = build_export([ExportItem(source)])
    assert preview.valid
    restored = parse_agf(preview.text).materials[0]
    assert restored.raw_text == source.raw_text.replace("\n", "\r\n")
    assert material_comment(source) == "first 中文\nsecond"
    info = preview.manifest["materials"][0]
    assert info["original_glass_comment"] == info["effective_glass_comment"] == "first 中文\nsecond"
    assert info["glass_comment_override"] is None
    assert info["source_header"] == "CC source header\n"
    assert preview.manifest["catalog_comment_override"] is None
    assert preview.manifest["effective_catalog_comment"] == DEFAULT_CATALOG_COMMENT


@pytest.mark.parametrize("override", ["", "edited 中文\nNM NOT_A_MATERIAL 2 0 1.5 50\nCD not coefficients"])
def test_gc_override_replaces_at_first_position_and_preserves_all_other_records(override):
    source = material(extra="GC old one\nCC local\n! local note\nGC old two\nXX exact  unknown   tail\n")
    item = replace(ExportItem(source, "RENAMED"), glass_comment=override)
    preview = build_export([item])
    assert preview.valid
    reloaded = parse_agf(preview.text)
    assert len(reloaded.materials) == 1
    restored = reloaded.materials[0]
    assert restored.name == "RENAMED"
    original_other = [r.raw_text.replace("SAMPLE", "RENAMED").replace("\n", "\r\n") for r in source.records if r.mnemonic != "GC"]
    assert [r.raw_text for r in restored.records if r.mnemonic != "GC"] == original_other
    assert restored.records[0].tokens[1:] == source.records[0].tokens[1:]
    assert material_comment(restored) == override
    assert [r.mnemonic for r in restored.records] == ["NM", "CD"] + (["GC"] * 3 if override else []) + ["CC", "!", "XX"]
    info = preview.manifest["materials"][0]
    assert info["original_glass_comment"] == "old one\nold two"
    assert info["glass_comment_override"] == info["effective_glass_comment"] == override
    assert info["export_name_override"] == "RENAMED"
    assert replace(item, export_name="AGAIN").glass_comment == override
    assert replace(item, glass_comment=None).export_name == "RENAMED"


def test_missing_gc_inserted_after_nm_and_long_unicode_lines_prefixed():
    comment = "界" * 280 + "\r\nNM injection\rCC payload\n\nGC literal XX literal ! literal\n"
    preview = build_export([ExportItem(material(), glass_comment=comment)], catalog_comment=comment)
    assert preview.valid
    restored = parse_agf(preview.text)
    assert len(restored.materials) == 1
    records = restored.materials[0].records
    assert records[0].mnemonic == "NM" and records[-1].mnemonic == "CD"
    assert all(r.mnemonic == "GC" for r in records[1:-1])
    assert all(line == "CC" or line.startswith("CC ") for line in restored.header.splitlines())
    assert all(len(r.raw_text.rstrip("\r\n")) <= 141 for r in records[1:-1])
    assert "GC NM injection\r\n" in preview.text
    info = preview.manifest["materials"][0]
    assert info["glass_comment_override"] == comment
    assert info["effective_glass_comment"] == material_comment(restored.materials[0])


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x0b", "\x0c", "\x1c", "\x7f", "\x85", "‮", "\ud800"])
@pytest.mark.parametrize("kind", ["glass", "catalog"])
def test_unsupported_comment_controls_block_without_injection(control, kind):
    source = material(extra="GC original\n")
    text = "safe" + control + "NM INJECTED"
    preview = build_export([ExportItem(source, glass_comment=text if kind == "glass" else None)],
                           catalog_comment=text if kind == "catalog" else None)
    assert not preview.valid
    assert any("comment" in error.lower() and "control" in error for error in preview.errors)
    assert len(parse_agf(preview.text).materials) == 1


def test_empty_catalog_comment_clears_only_new_cc():
    source = material(header="CC original catalog\n", extra="CC local record\nGC original glass\n")
    preview = build_export([ExportItem(source)], catalog_comment="")
    assert preview.valid and parse_agf(preview.text).header == ""
    assert "CC local record" in preview.text and "GC original glass" in preview.text
    assert preview.manifest["materials"][0]["source_header"] == "CC original catalog\n"
    assert preview.manifest["catalog_comment_override"] == preview.manifest["effective_catalog_comment"] == ""


def test_generated_warning_ack_and_provenance_survive_comment_clear():
    source = glass_to_agf(Glass(supplier="test", name="VALID", code="", nd=1.5, vd=50,
                               dispersion=(1, 2, 3, 4, 5, 6), wavelength_range=(.4, .7)))
    item = ExportItem(source, glass_comment="")
    assert not build_export([item]).valid
    preview = build_export([item], acknowledge_warnings=True)
    assert preview.valid and not material_comment(parse_agf(preview.text).materials[0])
    assert preview.warnings and "omitted_ed" in str(preview.manifest["materials"][0]["diagnostics"])
    assert preview.manifest["materials"][0]["provenance"] == source.provenance


@pytest.mark.parametrize("target", ["GC", "NM", "CD", "XX"])
def test_explicit_expected_sequence_detects_reparse_changes(monkeypatch, target):
    import glass_workbench.catalogs.agf_export as module
    original_parse = module.parse_agf

    def altered_parse(text):
        document = original_parse(text)
        source = document.materials[0]
        records = tuple(replace(r, tokens=(*r.tokens, "TAMPERED")) if r.mnemonic == target else r for r in source.records)
        return replace(document, materials=(replace(source, records=records),))

    monkeypatch.setattr(module, "parse_agf", altered_parse)
    preview = build_export([ExportItem(material(extra="GC old\nXX tail\n"), "RENAMED", "new")])
    assert not preview.valid
    assert any("expected record" in error for error in preview.errors)


@pytest.mark.parametrize("control", ["​", "­", "\x00"])
@pytest.mark.parametrize("field", ["remarks", "supplier", "source_file", "source_sheet", "source_row"])
def test_source_comment_controls_produce_snapshot_not_catalog_update_crash(control, field):
    value = "original" + control + "text"
    glass = Glass(supplier="test", name="VALID", code="", nd=1.5, vd=50,
                  dispersion=(1, 2, 3, 4, 5, 6), wavelength_range=(.4, .7))
    glass = replace(glass, **{field: value})
    original = repr(glass)
    source = glass_to_agf(glass)
    assert repr(glass) == original
    assert source.name == "VALID"
    assert any(d.code == "invalid_source_comment" and d.severity == "error" for d in source.diagnostics)
    assert control not in material_comment(source)
    label = "remarks" if field == "remarks" else "origin"
    assert value in source.provenance["source_comments"][label]
    provenance_key = "source_remarks" if field == "remarks" else "source_path" if field == "source_file" else field
    assert source.provenance[provenance_key] == value
    assert source.provenance["omissions"]
    preview = build_export([ExportItem(source, glass_comment="safe replacement")], acknowledge_warnings=True, preserve_invalid=True)
    assert not preview.valid
    assert any("invalid_source_comment" in error for error in preview.errors)
    assert preview.manifest["materials"][0]["provenance"]["source_comments"] == source.provenance["source_comments"]
    if field == "source_file":
        assert any("source-path comment" in error for error in preview.errors)
        assert source.source_path == value


def test_edited_export_roundtrip_source_hash_and_seals(tmp_path):
    source_path = tmp_path / "original.agf"
    source_path.write_text("CC source catalog\n" + RAW + "GC source glass\nXX untouched\n", encoding="utf-8")
    original_bytes = source_path.read_bytes()
    source = load_agf(source_path).materials[0]
    preview = build_export([ExportItem(source, "RENAMED", "edited 中文\nNM harmless")], catalog_comment="新 catalog")
    assert preview.valid
    out, metadata = write_export(preview, tmp_path / "edited.agf")
    manifest = json.loads(metadata.read_text(encoding="utf-8"))
    assert manifest["output_sha256"] == sha256(out.read_bytes()).hexdigest()
    restored = load_agf(out).materials[0]
    assert restored.records[0].tokens[1:] == source.records[0].tokens[1:]
    assert next(r.tokens for r in restored.records if r.mnemonic == "CD") == source.records[1].tokens
    assert source_path.read_bytes() == original_bytes
    assert material_comment(restored) == "edited 中文\nNM harmless"
    with pytest.raises(ValueError):
        write_export(preview, source_path, overwrite=True)
    with pytest.raises(ValueError):
        write_export(replace(preview, text=preview.text.replace("harmless", "changed")), tmp_path / "bad.agf")
    preview.manifest["materials"][0]["glass_comment_override"] = "tampered"
    with pytest.raises(ValueError):
        write_export(preview, tmp_path / "bad.agf")
