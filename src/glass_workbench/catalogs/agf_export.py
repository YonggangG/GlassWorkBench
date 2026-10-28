"""Verified Excel mappings, lossless AGF block merging and guarded pair output.

Only formula 1/2 are generated. This is not a model fitting/translation engine.
An export consists of a UTF-16LE/BOM catalog and a UTF-8 provenance manifest.
Two independent destination replacements cannot be atomic as a pair: failures
report which replacements completed, rather than claiming a rollback occurred.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import isfinite
from pathlib import Path
from collections.abc import Mapping, Iterable
import codecs
import json
import os
import re
import tempfile
import unicodedata
from typing import Any

from .agf import AgfMaterial, Diagnostic, parse_agf
from ..contracts import Glass
from ..optics.dispersion import REFERENCE_ENVIRONMENT
from ..optics.air import _index


DEFAULT_CATALOG_COMMENT = "Glass Workbench combined catalog; see neighboring provenance metadata"


@dataclass(frozen=True)
class ExportItem:
    material: AgfMaterial
    export_name: str | None = None
    # None preserves original GC records; an explicit empty string removes them.
    glass_comment: str | None = None


@dataclass(frozen=True)
class ExportPreview:
    text: str
    manifest: dict[str, Any]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    # Immutable validation snapshot, independent of the UI-inspectable manifest.
    _source_paths: tuple[str, ...] = ()
    _content_sha256: str = ""
    _manifest_json: str = ""

    @property
    def valid(self) -> bool:
        return not self.errors


class ExportWriteError(OSError):
    """Pair commit failed; ``written_paths`` is the exact completed prefix."""
    def __init__(self, message: str, written_paths: Iterable[Path] = ()):
        super().__init__(message)
        self.written_paths = tuple(written_paths)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and isfinite(value)


def _fmt(value: float) -> str:
    # repr retains every bit required to round-trip a Python float, unlike UI display().
    return repr(float(value))


def _comment_lines(prefix: str, text: str) -> list[str]:
    """Serialize text, never AGF input: prefix every physical line and chunk.

    Tabs and CR/LF are supported. Unicode line/paragraph separators are also
    normalized so Python's AGF line splitter cannot expose an unprefixed record.
    Other control/format characters and unpaired surrogates are rejected.
    """
    if not isinstance(text, str):
        raise ValueError("Comment must be text")
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} and c not in "\t\r\n" for c in text):
        raise ValueError("Comment contains unsupported control/format characters")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").replace(" ", "\n")
    lines: list[str] = []
    for physical in text.split("\n"):
        lines.extend(prefix + " " + physical[i:i+138] for i in range(0, len(physical), 138))
        if not physical:
            lines.append(prefix)
    return lines


def material_comment(material: AgfMaterial) -> str:
    """Return original GC payloads in source order, excluding CC and ! records."""
    return "\n".join(r.raw_text.strip()[2:].lstrip() for r in material.records if r.mnemonic == "GC")


def _metadata_value(metadata: Any, key: str, default: Any = None) -> Any:
    return metadata.get(key, default) if isinstance(metadata, Mapping) else getattr(metadata, key, default)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def glass_to_agf(glass: Glass) -> AgfMaterial:
    """Snapshot one workbook Glass without mutation; unsupported models stay visible.

    Missing optional physical records are omitted and reported, not zero-filled.
    Failed required conversions produce a material with blocking diagnostics.
    """
    diagnostics: list[Diagnostic] = []
    omissions: list[str] = []
    assumptions: list[str] = []
    source_comments: dict[str, str] = {}

    def warning(code: str, message: str) -> None:
        diagnostics.append(Diagnostic("warning", code, message))

    def error(code: str, message: str) -> None:
        diagnostics.append(Diagnostic("error", code, message))

    def source_comment(label: str, text: str) -> list[str]:
        # Workbook metadata is untrusted input too, but one bad comment must not
        # abort the entire catalog update. Keep the original in provenance and a
        # blocking diagnostic rather than silently sanitizing or losing it.
        source_comments[label] = text
        try:
            return _comment_lines("GC", text)
        except ValueError as exc:
            note = f"Source {label} GC omitted: {exc}; original retained in provenance.source_comments"
            omissions.append(note)
            error("invalid_source_comment", note)
            return []

    formula = {"polynomial": 1, "sellmeier": 2}.get(glass.dispersion_model)
    if glass.supplemental or formula is None:
        error("unsupported_conversion", "Supplemental or unsupported model cannot be directly exported; no fitting or coefficient copying was attempted")
    coefficients = tuple(glass.dispersion)
    if len(coefficients) != 6 or not all(_finite(v) for v in coefficients):
        error("invalid_coefficients", "Exactly six finite source dispersion coefficients are required")
    if not _finite(glass.nd) or not _finite(glass.vd):
        error("missing_reference", "Finite source nd and vd are required for generated NM")
    # The unused MIL slot is an explicit placeholder, not a fabricated glass code.
    # Status and melt frequency are optional and omitted rather than guessed from MA.
    fields = ["NM", glass.name, str(formula or 0), "0",
              _fmt(glass.nd) if _finite(glass.nd) else "?",
              _fmt(glass.vd) if _finite(glass.vd) else "?", "0"]
    lines = [" ".join(fields)]
    lines += source_comment("origin", f"Generated from {glass.supplier}; source {Path(glass.source_file).name}, sheet {glass.source_sheet}, row {glass.source_row}")
    assumptions.append("NM unused MIL=0 placeholder; exclude-substitution=0 export policy; manufacturer status and melt frequency unspecified")
    warning("unspecified_status", assumptions[-1])
    for note in glass.warnings:
        warning("source_warning", str(note))
    if glass.remarks:
        lines += source_comment("remarks", glass.remarks)
    if formula in (1, 2) and len(coefficients) == 6 and all(_finite(v) for v in coefficients):
        ordered = coefficients if formula == 1 else tuple(coefficients[i] for i in (0, 3, 1, 4, 2, 5))
        lines.append("CD " + " ".join(_fmt(v) for v in ordered))
    metadata = getattr(glass, "agf_metadata", None)
    cte1 = _metadata_value(metadata, "cte1", glass.cte)
    if cte1 is None:
        cte1 = glass.cte
    cte2 = _metadata_value(metadata, "cte2")
    density = _metadata_value(metadata, "density")
    dpgf = _metadata_value(metadata, "dpgf")
    if all(_finite(v) for v in (cte1, cte2, density, dpgf)):
        lines.append("ED " + " ".join(_fmt(v) for v in (cte1*1e6, cte2*1e6, density, dpgf)) + " 0")
        assumptions.append("ED Ignore Thermal Expansion=0; first source CTE used at all temperatures by AGF; source interval metadata retained in manifest")
        interval = _metadata_value(metadata, "cte2_temperature_range")
        if interval and tuple(interval) != (100, 300):
            warning("cte2_interval", f"Second CTE is from source interval {interval} C, not nominal AGF 100..300 C; this AGF field is currently unused")
    else:
        note = "ED omitted: complete verified CTE1/CTE2/density/dPgF unavailable; PgF is not dPgF. Output must not be treated as thermally complete"
        omissions.append(note)
        warning("omitted_ed", note)
    thermal = glass.thermal
    if thermal is not None and len(thermal) == 6 and all(_finite(v) for v in thermal) and _finite(glass.reference_temperature) and glass.thermal_model == "catalog_d":
        lines.append("TD " + " ".join(_fmt(v) for v in (*thermal, glass.reference_temperature)))
    else:
        note = "TD omitted: complete standard six-coefficient thermal model and reference temperature unavailable; missing is not zero dn/dT"
        omissions.append(note)
        warning("omitted_td", note)
    if glass.price is not None and not _finite(glass.price):
        error("invalid_price", "Source relative price is nonfinite")
    price = _fmt(glass.price) if _finite(glass.price) else "-1"
    lines.append(f"OD {price} -1 -1 -1 -1 -1")
    if _finite(glass.price):
        warning("supplier_price", "OD relative price is supplier-native and not comparable across suppliers")
    omissions.append("MD and BD omitted: no verified mechanical/stress-birefringence data in workbook contract")
    try:
        lo, hi = glass.wavelength_range
        if not all(_finite(v) and v > 0 for v in (lo, hi)) or hi <= lo or not _finite(glass.reference_temperature):
            raise ValueError("invalid source range or reference temperature")
        native_air_range = _metadata_value(metadata, "wavelength_range_air")
        air_range = tuple(native_air_range) if native_air_range is not None else tuple(
            v/_index(v, glass.reference_temperature, REFERENCE_ENVIRONMENT) for v in (lo, hi))
        if len(air_range) != 2 or not all(_finite(v) and v > 0 for v in air_range) or air_range[1] <= air_range[0]:
            raise ValueError("invalid source-air wavelength range")
        lines.append("LD " + " ".join(_fmt(v) for v in air_range))
        axis_note = "retained from verified source-air checkpoints" if native_air_range is not None else "converted from stored vacuum to fixed reference-air wavelength"
        note = f"LD is conservative derived spectral-checkpoint coverage, {axis_note}; not manufacturer-certified dispersion limits or validated broad NIR coverage"
        assumptions.append(note)
        warning("derived_ld", note)
        lines += _comment_lines("GC", note)
        assumptions.append("Reference air: dry Ciddor, 101325 Pa, 450 ppm CO2 at source reference temperature; source humidity/CO2 unspecified")
    except (ValueError, TypeError, OverflowError, ZeroDivisionError) as exc:
        error("invalid_ld", f"Cannot derive source-air LD: {exc}")
    if len(glass.transmission) > 100:
        error("it_point_limit", "More than 100 source transmission points; none were silently truncated")
    previous = None
    for sample in glass.transmission:
        if len(sample) != 2 or not all(_finite(v) for v in sample):
            error("invalid_transmission", "Invalid source internal transmission sample")
            continue
        wave, tau = sample
        if wave <= 0 or not 0 <= tau <= 1:
            error("invalid_transmission", "Source transmission requires wavelength>0 and tau in [0,1]")
        if previous is not None and wave <= previous:
            error("transmission_order", "Source transmission wavelengths must be strictly ascending; source order was not changed")
        previous = wave
        # Workbook loaders retain supplier transmission wavelengths on their original
        # tabulated axis, unlike Glass.wavelength_range (vacuum checkpoint coverage).
        lines.append(f"IT {_fmt(wave)} {_fmt(tau)} 10")
    assumptions.append("IT retains original source internal-transmission samples at 10 mm without interpolation or Fresnel correction")
    text = "\n".join(lines) + "\n"
    snapshot = sha256(repr(glass).encode("utf-8")).hexdigest()
    parsed = parse_agf(text, glass.source_file or "<workbook>")
    if not parsed.materials:
        # An invalid/injected name must still yield a visible, blocking basket item.
        parsed = parse_agf("NM INVALID 0 0 0 0\n", glass.source_file or "<workbook>")
    material = parsed.materials[0]
    if len(parsed.materials) != 1 or any(c.isspace() for c in glass.name):
        error("invalid_name", "Source material name cannot form a single AGF NM name")
    provenance = {
        "kind": "generated", "supplier": glass.supplier, "source_path": glass.source_file,
        "source_sha256": glass.source_hash, "source_sheet": glass.source_sheet,
        "source_row": glass.source_row, "snapshot_sha256": snapshot,
        "source_code": glass.code, "source_metadata": _json_safe(asdict(metadata) if hasattr(metadata, "__dataclass_fields__") else metadata),
        "source_warnings": list(glass.warnings), "source_remarks": glass.remarks,
        "source_comments": source_comments, "omissions": omissions, "assumptions": assumptions,
        "source_wavelength_range_vacuum_um": list(glass.wavelength_range),
        "reference_temperature_c": glass.reference_temperature,
    }
    return replace(material, identity=f"excel:{glass.source_hash}:{snapshot}:{glass.source_sheet}:{glass.source_row}",
                   name=glass.name, formula=formula, nd=glass.nd, vd=glass.vd,
                   source_sha256=glass.source_hash, source_encoding="generated", source_header="",
                   generated=True, provenance=provenance,
                   diagnostics=tuple(diagnostics) + material.diagnostics)


def _name_error(name: str, restricted: bool) -> str | None:
    if not name or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in name):
        return "AGF material name must be nonempty and contain no whitespace/control characters"
    if restricted and (len(name) > 32 or not name.isascii() or not re.fullmatch(r"[A-Za-z0-9_.+()\-]+", name)):
        return "Generated/renamed material uses conservative app name policy: 1..32 ASCII letters/digits or _ . + ( ) -"
    return None


def allocate_export_items(materials: Iterable[AgfMaterial],
                          existing_items: Iterable[ExportItem] = ()) -> tuple[ExportItem, ...]:
    """Allocate conservative aliases for new additions without mutating sources.

    Existing effective names and all valid incoming originals are reserved first.
    Valid duplicates remain duplicates for explicit user resolution; only repaired
    names get suffixes. Existing items/overrides are never regenerated or returned.
    """
    materials = tuple(materials)
    reserved = {(item.export_name if item.export_name is not None else item.material.name).casefold()
                for item in existing_items}
    reserved.update(m.name.casefold() for m in materials if _name_error(m.name, True) is None)
    result: list[ExportItem] = []
    for material in materials:
        if _name_error(material.name, True) is None:
            result.append(ExportItem(material))
            continue
        base = re.sub(r"[^A-Za-z0-9_.+()\-]", "_", material.name.replace("*", "_ST"))[:32] or "GLASS"
        name = base
        suffix = 2
        while name.casefold() in reserved:
            ending = f"_{suffix}"
            name = base[:32-len(ending)] + ending
            suffix += 1
        reserved.add(name.casefold())
        result.append(ExportItem(material, export_name=name))
    return tuple(result)


def _crlf(text: str) -> str:
    return "\r\n".join(text.splitlines()) + "\r\n"


def _output_records(item: ExportItem, name: str, errors: list[str]) -> list[tuple[str, tuple[str, ...], str]]:
    """Explicit authorized record sequence, independently checked after reparse."""
    replacement = None
    if item.glass_comment is not None:
        try:
            replacement = _comment_lines("GC", item.glass_comment) if item.glass_comment else []
        except ValueError as exc:
            errors.append(f"{name}: invalid glass comment: {exc}")
    records = []
    inserted = False
    has_gc = any(r.mnemonic == "GC" for r in item.material.records)

    def insert_comment() -> None:
        nonlocal inserted
        for line in replacement or ():
            records.append(("GC", tuple(line.split()[1:]), line + "\r\n"))
        inserted = True

    for record in item.material.records:
        if record.mnemonic == "GC" and replacement is not None:
            if not inserted:
                insert_comment()
            continue
        raw, tokens = record.raw_text, record.tokens
        if record.mnemonic == "NM" and name != item.material.name:
            raw, count = re.subn(r"(\A[ \t]*NM[ \t]+)\S+", lambda match: match.group(1) + name,
                                 raw, count=1, flags=re.IGNORECASE)
            if count != 1:
                errors.append(f"{name}: cannot safely locate a single NM name for renaming")
            tokens = (name, *tokens[1:])
        records.append((record.mnemonic, tokens, _crlf(raw)))
        if record.mnemonic == "NM" and not has_gc and replacement is not None and not inserted:
            insert_comment()
    return records


def _encoded(text: str) -> bytes:
    return codecs.BOM_UTF16_LE + text.encode("utf-16-le")


def build_export(items: Iterable[ExportItem], acknowledge_warnings: bool = False,
                 preserve_invalid: bool = False, *,
                 catalog_comment: str | None = None) -> ExportPreview:
    """Validate a snapshot; None comments preserve defaults/original records.

    Explicit empty comment overrides remove generated CC or material GC records.
    Original source headers remain in provenance irrespective of the CC override.
    """
    items = tuple(items)
    errors: list[str] = []
    warnings: list[str] = []
    blocks: list[str] = []
    expected_records: list[list[tuple[str, tuple[str, ...], str]]] = []
    entries: list[dict[str, Any]] = []
    names: set[str] = set()
    output_names: list[str] = []
    source_paths: set[str] = set()
    if not items:
        errors.append("The export basket is empty")
    for item in items:
        m = item.material
        name = item.export_name if item.export_name is not None else m.name
        output_names.append(name)
        issue = _name_error(name, m.generated or name != m.name)
        if issue:
            errors.append(f"{name!r}: {issue}")
        if name.casefold() in names:
            errors.append(f"Duplicate output name (case-insensitive): {name}")
        names.add(name.casefold())
        archival = False
        for d in m.diagnostics:
            message = f"{name}: {d.code}: {d.message}" + (f" (source line {d.line})" if d.line is not None else "")
            if d.severity == "error":
                if preserve_invalid and not m.generated and d.code not in {"invalid_boundary", "orphan_record", "no_materials", "invalid_name"}:
                    warnings.append("ARCHIVAL ONLY — " + message)
                    archival = True
                else:
                    errors.append(message)
            elif d.severity == "warning":
                warnings.append(message)
        if m.generated and any(d.severity == "warning" for d in m.diagnostics) and not acknowledge_warnings:
            errors.append(f"{name}: generated export warnings require explicit acknowledgment")
        records = _output_records(item, name, errors)
        expected_records.append(records)
        blocks.append("".join(raw for _, _, raw in records))
        if m.source_path and not m.source_path.startswith("<"):
            source_paths.add(m.source_path)
        entries.append({
            "identity": m.identity, "original_name": m.name, "export_name": name,
            "export_name_override": item.export_name,
            "original_glass_comment": material_comment(m),
            "glass_comment_override": item.glass_comment,
            "effective_glass_comment": "\n".join(raw.strip()[2:].lstrip() for key, _, raw in records if key == "GC"),
            "renamed": name != m.name, "kind": "generated" if m.generated else "preserved",
            "source_path": m.source_path, "source_sha256": m.source_sha256,
            "source_encoding": m.source_encoding, "source_header": m.source_header,
            "source_ordinal": m.ordinal, "source_lines": [m.start_line, m.end_line],
            "diagnostics": [asdict(d) for d in m.diagnostics], "archival_only": archival,
            "provenance": m.provenance,
        })
    # Source headers are preserved exactly in provenance; short comments in AGF
    # carry useful context without inserting an accidental material boundary.
    comment = DEFAULT_CATALOG_COMMENT if catalog_comment is None else catalog_comment
    header: list[str] = []
    try:
        if comment:
            header.extend(_comment_lines("CC", comment))
    except ValueError as exc:
        errors.append(f"Invalid catalog comment: {exc}")
    effective_catalog_comment = "\n".join(line[2:].lstrip() for line in header)
    for source in sorted(source_paths):
        try:
            header.extend(_comment_lines("!", "Source: " + source))
        except ValueError as exc:
            errors.append(f"Invalid source-path comment: {exc}")
    header_text = "".join(line + "\r\n" for line in header)
    text = header_text + "".join(blocks)
    reparsed = parse_agf(text)
    if reparsed.header != header_text:
        errors.append("Output reparse changed expected catalog header")
    if len(reparsed.materials) != len(items) or [m.name for m in reparsed.materials] != output_names:
        errors.append("Output reparse did not preserve the selected material count/names; no file may be written")
    else:
        for expected, check in zip(expected_records, reparsed.materials):
            actual = [(r.mnemonic, r.tokens, r.raw_text) for r in check.records]
            if expected != actual:
                errors.append(f"{check.name}: output reparse changed expected record text/tokens/order")
    from .. import __version__
    manifest = {
        "schema_version": 1, "app_version": __version__, "encoding": "utf-16-le-bom", "newline": "CRLF",
        "output_sha256": sha256(_encoded(text)).hexdigest(), "material_count": len(items),
        "source_paths": sorted(source_paths), "materials": entries,
        "original_catalog_comment": DEFAULT_CATALOG_COMMENT,
        "catalog_comment_override": catalog_comment,
        "effective_catalog_comment": effective_catalog_comment,
        "acknowledge_warnings": bool(acknowledge_warnings), "preserve_invalid": bool(preserve_invalid),
        "validated_for_opticstudio": False,
        "validation_scope": "record/name/count preservation and formula 1/2 workbook mapping; no native OpticStudio acceptance test",
        "warnings": warnings, "errors": errors,
    }
    sealed_manifest = json.dumps(manifest, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return ExportPreview(text, manifest, tuple(errors), tuple(warnings),
                         tuple(sorted(source_paths)), manifest["output_sha256"], sealed_manifest)


def _same_path(a: Path, b: Path) -> bool:
    if str(a.resolve()).casefold() == str(b.resolve()).casefold():
        return True
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def _installed_catalog_path(path: Path) -> bool:
    # Resolve junctions/symlinks before checking; directory-name rejection is
    # intentionally conservative for vendor catalog roots, not a guessed install.
    parts = [p.casefold() for p in path.resolve().parts]
    if any(p in {"glasscat", "glasscatalogs", "glass catalogs"} for p in parts[:-1]):
        return True
    for key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = os.environ.get(key)
        if root:
            try:
                relative = path.resolve().relative_to(Path(root).resolve())
            except ValueError:
                continue
            if any("zemax" in p.casefold() or "opticstudio" in p.casefold() for p in relative.parts):
                return True
    return False


def write_export(preview: ExportPreview, path: str | Path,
                 source_paths: Iterable[str | Path] = (), overwrite: bool = False) -> tuple[Path, Path]:
    """Stage both outputs before committing; never overwrite sources/installations.

    Callers must include *all loaded* AGF/Excel paths, including nonbasket sources.
    Existing outputs require explicit ``overwrite=True``. No directory is created.
    """
    if not preview.valid:
        raise ValueError("Export is blocked: " + "; ".join(preview.errors))
    output = Path(path).expanduser().absolute()
    if output.suffix.casefold() != ".agf":
        raise ValueError("Destination must have an .agf extension")
    manifest_path = output.with_suffix(".metadata.json")
    if not preview._manifest_json or not preview._content_sha256:
        raise ValueError("Export preview lacks a validation snapshot; rebuild the preview")
    sealed_manifest = json.loads(preview._manifest_json)
    if sealed_manifest.get("errors"):
        raise ValueError("Validated preview has blocking errors; rebuild the preview")
    if json.dumps(preview.manifest, sort_keys=True, ensure_ascii=False, allow_nan=False) != preview._manifest_json:
        raise ValueError("Preview manifest changed; regenerate validation before writing")
    protected = tuple(Path(p).expanduser() for p in (*tuple(source_paths), *preview._source_paths) if str(p))
    destinations = (output, manifest_path)
    for destination in destinations:
        if _installed_catalog_path(destination):
            raise ValueError(f"Refusing installed/vendor catalog directory: {destination}")
        if any(_same_path(destination, source) for source in protected):
            raise ValueError(f"Refusing to overwrite a loaded source or alias: {destination}")
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Output already exists; explicit replacement required: {destination}")
        if not destination.parent.is_dir():
            raise FileNotFoundError(f"Output directory does not exist: {destination.parent}")
    data = _encoded(preview.text)
    if sha256(data).hexdigest() != preview._content_sha256:
        raise ValueError("Preview content/hash changed; regenerate validation before writing")
    manifest = dict(sealed_manifest, output_path=str(output), manifest_path=str(manifest_path))
    payloads = (data, (json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
    staged: list[Path] = []
    written: list[Path] = []
    try:
        for destination, payload in zip(destinations, payloads):
            fd, temporary = tempfile.mkstemp(prefix=".agf-stage-", suffix=".tmp", dir=destination.parent)
            staged.append(Path(temporary))
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, destination in zip(staged, destinations):
            if overwrite:
                os.replace(temporary, destination)
            else:
                # Hard-link publication is atomic and refuses a destination that
                # appeared after validation (unlike os.replace/check-then-write).
                os.link(temporary, destination)
            written.append(destination)
        return destinations
    except OSError as exc:
        completed = ", ".join(str(p) for p in written) or "none"
        raise ExportWriteError(f"Export pair write failed; completed destinations: {completed}. {exc}", written) from exc
    finally:
        for temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
