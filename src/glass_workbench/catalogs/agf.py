"""Preservation-oriented ASCII Glass Format inspection, not an optical engine.

Raw record spelling/order/precision are authoritative. Typed values are an
inspection overlay, never a repaired replacement for malformed source records.
Format reference: Ansys OpticStudio 2025 R1, The AGF & BGF File Formats.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, DecimalException
from hashlib import sha256
from math import isfinite
from pathlib import Path
import codecs
import re
from typing import Any

FORMULA_LABELS = {
    1: "Schott", 2: "Sellmeier 1", 3: "Herzberger", 4: "Sellmeier 2",
    5: "Conrady", 6: "Sellmeier 3", 7: "Handbook of Optics 1",
    8: "Handbook of Optics 2", 9: "Sellmeier 4", 10: "Extended",
    11: "Sellmeier 5", 12: "Extended 2", 13: "Extended 3",
}
STATUS_LABELS = {0: "Standard", 1: "Preferred", 2: "Obsolete", 3: "Special", 4: "Melt"}
PLACEHOLDERS = {"_", "-", "--", "?", "*", "n/a", "na", "null", '""', "''"}


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class AgfRecord:
    mnemonic: str
    tokens: tuple[str, ...]
    raw_text: str
    line: int
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgfMaterial:
    identity: str
    name: str
    formula: int | None
    nd: float | None
    vd: float | None
    records: tuple[AgfRecord, ...]
    properties: dict[str, Any]
    diagnostics: tuple[Diagnostic, ...]
    source_path: str
    source_sha256: str
    source_encoding: str
    source_header: str
    ordinal: int
    start_line: int
    end_line: int
    generated: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_text(self) -> str:
        return "".join(record.raw_text for record in self.records)


@dataclass(frozen=True)
class AgfDocument:
    path: str
    sha256: str
    encoding: str
    header: str
    materials: tuple[AgfMaterial, ...]
    diagnostics: tuple[Diagnostic, ...]
    newline: str = "\n"


def integer_token(token: str) -> int:
    """Read integer-valued scientific notation without float rounding."""
    try:
        value = Decimal(token)
        # Decimal abs() applies the ambient context and can overflow for a huge
        # exponent. Compare bounded values before integral conversion instead.
        if not value.is_finite() or value < -(2**31-1) or value > 2**31-1 or value != value.to_integral_value():
            raise ValueError(f"Not a bounded integer: {token!r}")
        return int(value)
    except DecimalException as exc:
        raise ValueError(f"Not an integer: {token!r}") from exc


def _number(token: str) -> float | None:
    if token.casefold() in PLACEHOLDERS:
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    return value if isfinite(value) else None


def _record(raw: str, line: int) -> AgfRecord:
    pieces = raw.strip().split()
    if not pieces:
        return AgfRecord("", (), raw, line)
    if pieces[0].startswith("!"):
        return AgfRecord("!", tuple(pieces), raw, line, {"text": raw.strip()[1:]})
    return AgfRecord(pieces[0].upper(), tuple(pieces[1:]), raw, line)


def _material(records: list[AgfRecord], path: str, digest: str, encoding: str,
              header: str, ordinal: int) -> AgfMaterial:
    diagnostics: list[Diagnostic] = []
    props: dict[str, Any] = {"transmission": [], "birefringence": []}
    name = ""
    formula = None
    nd = vd = None
    seen: dict[str, int] = {}
    typed: list[AgfRecord] = []

    def issue(code: str, message: str, record: AgfRecord, severity: str = "error") -> None:
        diagnostics.append(Diagnostic(severity, code, message, record.line))

    for record in records:
        key, tokens = record.mnemonic, record.tokens
        values: dict[str, Any] = {}
        if key and key not in {"!", "GC", "CC", "IT", "BD"}:
            if key in seen:
                issue("repeated_record", f"Repeated {key}; no record was discarded", record)
            seen[key] = record.line
        if key == "NM":
            name = tokens[0] if tokens else ""
            values["name"] = name
            if not name:
                issue("invalid_boundary", "NM has no identifiable material name", record)
            if len(tokens) < 5:
                issue("incomplete_nm", "NM requires name, formula, MIL placeholder, nd and vd", record)
            try:
                formula = integer_token(tokens[1])
            except (ValueError, IndexError):
                issue("invalid_formula", "NM formula must be an integer-valued number", record)
            values.update(formula=formula, mil_code=tokens[2] if len(tokens) > 2 else None)
            nd = _number(tokens[3]) if len(tokens) > 3 else None
            vd = _number(tokens[4]) if len(tokens) > 4 else None
            values.update(nd=nd, vd=vd)
            if nd is None or vd is None:
                issue("invalid_nm_reference", "NM nd/vd reference values missing or nonnumeric", record)
            for index, label, allowed in ((5, "exclude_substitution", {0, 1}),
                                          (6, "status", set(STATUS_LABELS)),
                                          (7, "melt_frequency", {1, 2, 3, 4, 5})):
                if len(tokens) > index:
                    try:
                        value = integer_token(tokens[index])
                        values[label] = value
                        if value not in allowed:
                            issue("nm_flag_range", f"NM {label}={value} outside documented range", record, "warning")
                    except ValueError:
                        values[label] = None
                        issue("invalid_nm_flag", f"NM {label} is not an integer", record)
                else:
                    values[label] = None
            values["extra_tokens"] = tokens[8:]
            props.update(values)
            props["formula_label"] = FORMULA_LABELS.get(formula, f"Unknown formula {formula}")
            props["status_label"] = STATUS_LABELS.get(values.get("status"), "Unspecified/unknown")
            if formula not in (1, 2):
                issue("unevaluated_formula", f"{props['formula_label']}: preserved, not numerically evaluated here", record, "warning")
        elif key in {"GC", "CC", "!"}:
            values["text"] = record.raw_text.strip()[1 if key == "!" else 2:].lstrip()
            props.setdefault("comments", []).append(values["text"])
        elif key in {"ED", "CD", "TD", "MD", "OD", "LD", "IT", "BD"}:
            numbers = tuple(_number(token) for token in tokens)
            values["numbers"] = numbers
            values["token_states"] = tuple("empty" if token in {'""', "''"} else
                "placeholder" if token.casefold() in PLACEHOLDERS else
                "value" if number is not None else "invalid" for token, number in zip(tokens, numbers))
            fields = {
                "ED": ("cte1_ppm_k", "cte2_ppm_k", "density_g_cm3", "dpgf", "ignore_thermal_expansion"),
                "TD": ("d0", "d1", "d2", "e0", "e1", "lambda_tk_um", "reference_temperature_c"),
                "MD": ("young_modulus_gpa", "poisson_ratio", "knoop_hardness_kgf_mm2", "specific_heat_j_kgk", "conductivity_w_mk"),
                "OD": ("relative_cost", "cr", "fr", "sr", "ar", "pr"),
                "LD": ("minimum_um", "maximum_um"),
                "IT": ("wavelength_um", "internal_transmission", "thickness_mm"),
                "BD": ("wavelength_um", "k", "minus_k11", "minus_k12"),
            }
            if key == "CD":
                values["coefficients"] = numbers
                values["coefficient_tokens"] = tokens
                if not tokens or len(tokens) > 10 or any(v is None for v in numbers):
                    issue("invalid_cd", "CD needs 1..10 finite numeric coefficients; raw values retained", record)
            else:
                names = fields[key]
                # Short records have ambiguous missing positions. Do not slide a
                # density or a transmission value into an invented field.
                if len(tokens) < len(names):
                    # Incomplete optional stress records are present in shipped
                    # catalogs. Keep them inspectable without asserting undocumented
                    # two-field syntax or inventing photoelastic coefficients.
                    severity = "warning" if key == "BD" and len(tokens) == 2 and all(v is not None for v in numbers) else "error"
                    issue("incomplete_" + key.lower(), f"{key} has {len(tokens)}/{len(names)} fields; positions are unresolved; raw optional data retained" if key == "BD" else
                          f"{key} has {len(tokens)}/{len(names)} fields; positions are unresolved", record, severity)
                    values["unassigned_tokens"] = tokens
                else:
                    values.update(zip(names, numbers))
                    values["extra_tokens"] = tokens[len(names):]
                    if len(tokens) > len(names):
                        issue("extra_" + key.lower(), f"{key} trailing fields retained without interpretation", record, "warning")
                    if any(v is None for v in numbers[:len(names)]):
                        placeholder_only = all(v is not None or t.casefold() in PLACEHOLDERS
                                               for t, v in zip(tokens[:len(names)], numbers[:len(names)]))
                        severity = "warning" if key in {"MD", "OD", "BD"} and placeholder_only else "error"
                        issue("missing_" + key.lower(), f"{key} contains placeholder/invalid fields; no zero substitution", record, severity)
                if key == "OD":
                    values["unavailable_fields"] = tuple(n for n in names if values.get(n) == -1)
                if key == "ED" and values.get("ignore_thermal_expansion") not in (None, 0, 1):
                    issue("invalid_ed_flag", "ED ignore-thermal-expansion must be 0 or 1", record)
                if key == "LD" and len(numbers) >= 2 and all(v is not None for v in numbers[:2]):
                    lo, hi = numbers[:2]
                    if lo <= 0 or hi < lo:
                        issue("invalid_ld", "LD must have positive ordered wavelength limits", record)
                    elif lo == hi:
                        issue("equal_ld", "LD endpoints are equal; not a validated finite spectral range", record, "warning")
                if key == "IT" and len(numbers) >= 3 and all(v is not None for v in numbers[:3]):
                    wave, tau, thickness = numbers[:3]
                    if wave <= 0 or not 0 <= tau <= 1 or thickness <= 0:
                        issue("invalid_it", "IT needs wavelength/thickness > 0 and transmission in [0,1]", record)
            if key == "IT":
                props["transmission"].append(values)
            elif key == "BD":
                props["birefringence"].append(values)
            else:
                props[key.lower()] = values
        elif key:
            values["uninterpreted_tokens"] = tokens
            issue("unknown_record", f"Unknown record {key} preserved verbatim", record, "warning")
        typed.append(replace(record, values=values))
    nm = records[0]
    if "CD" not in seen:
        issue("missing_cd", "No CD dispersion record present", nm)
    elif formula in (1, 2) and len(props.get("cd", {}).get("coefficients", ())) < 6:
        issue("incomplete_dispersion", "Formula 1/2 requires six coefficients", nm)
    transmission = props["transmission"]
    if len(transmission) > 100:
        issue("it_point_limit", "More than the documented 100 IT points; none truncated", nm)
    waves = [v.get("wavelength_um") for v in transmission]
    for prev, wave in zip(waves, waves[1:]):
        if prev is not None and wave is not None and wave <= prev:
            issue("it_order", "IT wavelengths repeat or are not ascending; all samples retained", nm, "warning")
            break
    identity = f"agf:{digest}:{sha256(path.encode('utf-8')).hexdigest()[:16]}:{ordinal}"
    return AgfMaterial(identity, name, formula, nd, vd, tuple(typed), props, tuple(diagnostics),
                       path, digest, encoding, header, ordinal, records[0].line, records[-1].line)


def parse_agf(text: str, source_path: str | Path = "<memory>",
              source_sha256: str | None = None, encoding: str = "utf-8") -> AgfDocument:
    """Parse already-decoded text, preserving every line and source occurrence."""
    if "\x00" in text or any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ValueError("Binary/BGF input is unsupported; expected decoded AGF text")
    text = text.removeprefix("﻿")
    digest = source_sha256 or sha256(text.encode("utf-8")).hexdigest()
    path = str(source_path)
    endings = re.findall(r"\r\n|\r|\n", text)
    newline = endings[0] if endings and len(set(endings)) == 1 else "mixed" if endings else ""
    header_lines: list[str] = []
    blocks: list[list[AgfRecord]] = []
    diagnostics: list[Diagnostic] = []
    for line, raw in enumerate(text.splitlines(keepends=True), 1):
        record = _record(raw, line)
        if record.mnemonic == "NM":
            blocks.append([])
        if blocks:
            blocks[-1].append(record)
        else:
            header_lines.append(raw)
            if record.mnemonic not in {"", "CC", "!"}:
                diagnostics.append(Diagnostic("error", "orphan_record", "Record before first NM retained in header", line))
    header = "".join(header_lines)
    materials = [_material(block, path, digest, encoding, header, n) for n, block in enumerate(blocks, 1)]
    if not materials:
        diagnostics.append(Diagnostic("error", "no_materials", "No NM material boundaries found"))
    if diagnostics:
        materials = [replace(m, diagnostics=tuple(diagnostics) + m.diagnostics) for m in materials]
    counts: dict[str, int] = {}
    for m in materials:
        counts[m.name.casefold()] = counts.get(m.name.casefold(), 0) + 1
    for i, m in enumerate(materials):
        if counts[m.name.casefold()] > 1:
            materials[i] = replace(m, diagnostics=m.diagnostics + (Diagnostic(
                "warning", "duplicate_source_name", "Same-name source occurrences remain distinct", m.start_line),))
    diagnostics.extend(d for material in materials for d in material.diagnostics if d not in diagnostics)
    return AgfDocument(path, digest, encoding, header, tuple(materials), tuple(diagnostics), newline)


def load_agf(path: str | Path, encoding: str | None = None) -> AgfDocument:
    """Load BOM Unicode or UTF-8; explicitly report a strict cp1252 fallback.

    ``encoding`` is a caller-selected override, never a lossy error policy.
    """
    path = Path(path).expanduser().resolve()
    if path.suffix.casefold() == ".bgf":
        raise ValueError("Binary BGF catalogs are unsupported; select the master AGF")
    data = path.read_bytes()
    fallback = False
    if encoding is not None:
        selected = codecs.lookup(encoding).name
        text = data.decode(selected, errors="strict")
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        selected = "utf-16-le-bom" if data.startswith(codecs.BOM_UTF16_LE) else "utf-16-be-bom"
        text = data.decode("utf-16", errors="strict")
    elif data.startswith(codecs.BOM_UTF8):
        selected, text = "utf-8-sig", data.decode("utf-8-sig", errors="strict")
    else:
        try:
            selected, text = "utf-8", data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            selected, text = "cp1252", data.decode("cp1252", errors="strict")
            fallback = True
    document = parse_agf(text, path, sha256(data).hexdigest(), selected)
    if fallback or encoding is not None:
        note = Diagnostic("warning", "encoding_fallback" if fallback else "encoding_override",
                          f"Decoded with explicit {'fallback' if fallback else 'override'} {selected}; verify source characters")
        document = replace(document, diagnostics=(note,) + document.diagnostics,
                           materials=tuple(replace(m, diagnostics=(note,) + m.diagnostics) for m in document.materials))
    return document
