"""Optional cross-source checks; external manufacturer catalogs are not distributed."""
from hashlib import sha256
from math import sqrt
from pathlib import Path

import pytest

from glass_workbench.catalogs.agf import load_agf
from glass_workbench.catalogs.agf_export import ExportItem, build_export, glass_to_agf, write_export
from glass_workbench.catalogs.loader import discover_catalogs, load_catalog


@pytest.fixture(scope="module")
def mixed_sources():
    root = Path(__file__).resolve().parents[1]
    workbooks = discover_catalogs(root)
    reference = root / "SCHOTT.AGF"
    if len(workbooks) != 2 or not reference.exists():
        pytest.skip("Official Excel and AGF catalogs are external")
    return [load_catalog(path) for path in workbooks], load_agf(reference)


def _cd(material):
    return tuple(float(token) for record in material.records
                 if record.mnemonic == "CD" for token in record.tokens)


def test_excel_sellmeier_matches_independent_agf_record(mixed_sources):
    catalogs, document = mixed_sources
    glass = next(g for c in catalogs for g in c.glasses if g.uid == "SCHOTT:N-BK7")
    imported = next(m for m in document.materials if m.name == "N-BK7")
    generated = glass_to_agf(glass)
    assert generated.formula == imported.formula == 2
    assert _cd(generated)[:6] == pytest.approx(_cd(imported)[:6], rel=1e-12)
    coefficients = _cd(generated)
    wavelength = 1.55  # Native catalog reference-air axis, not public vacuum API.
    q = wavelength * wavelength
    index = sqrt(1 + sum(coefficients[i] * q / (q - coefficients[i + 1])
                         for i in (0, 2, 4)))
    assert index == pytest.approx(1.5006520430195947, abs=2e-14)


def test_mixed_export_preserves_sources_and_coefficients(tmp_path, mixed_sources):
    catalogs, document = mixed_sources
    glass = next(g for c in catalogs for g in c.glasses if g.uid == "CDGM:H-K9L")
    imported = next(m for m in document.materials if m.name == "N-BK7")
    paths = [Path(c.path) for c in catalogs] + [Path(document.path)]
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in paths}
    generated = glass_to_agf(glass)
    preview = build_export([ExportItem(generated), ExportItem(imported, "REFERENCE_N_BK7")],
                           acknowledge_warnings=True)
    assert preview.valid, preview.errors
    output, manifest = write_export(preview, tmp_path / "MixedCatalog.agf", source_paths=paths)
    assert manifest.exists()
    restored = load_agf(output)
    assert [m.name for m in restored.materials] == ["H-K9L", "REFERENCE_N_BK7"]
    assert _cd(restored.materials[0]) == _cd(generated)
    assert _cd(restored.materials[1]) == _cd(imported)
    assert {str(p): sha256(p.read_bytes()).hexdigest() for p in paths} == before
