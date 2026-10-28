"""CDGM 202609 first-sheet adapter: interleaved K/L, CTE in 1e-7/K."""
from openpyxl.utils.cell import get_column_letter, column_index_from_string
from glass_workbench.contracts import AgfMetadata, Glass
from glass_workbench.optics.dispersion import air_to_vacuum
from .models import cell, number, text, coefficients, family, require_headers

PROVENANCE_WARNING = (
    "CDGM thermal convention/validity not manufacturer-verified; standard six-coefficient absolute-increment model assumed. "
    "Catalog wavelength scale interpreted as reference-air spectral wavelengths; dry Ciddor reference20C/101325Pa/450ppm assumed."
)


def parse(rows, path, sheet, digest):
    require_headers(rows, [(1,"A","Glass"),(1,"B","Code"),(1,"N","nd"),
                          (1,"X","νd"),(1,"AB","K1"),(1,"AC","L1"),
                          (1,"AD","K2"),(1,"AE","L2"),(1,"AF","K3"),(1,"AG","L3"),
                          (1,"AH","A0"),(1,"AM","A5"),(1,"AO","D0"),(1,"AT","λTK(μm)"),
                          (1,"BZ","α-30/70℃(10-7/K)"),(1,"EC","τ(10mm)"),
                          (1,"HV","Melt Frequency"),(1,"HW","Relative Price")])
    glasses, notices = [], [PROVENANCE_WARNING]
    for index,row in enumerate(rows[2:],3):
        name = text(cell(row,"A"))
        if not name or name.lower() == "over!":
            continue
        nd,vd = number(cell(row,"N")),number(cell(row,"X"))
        if nd is None or vd is None:
            notices.append(f"Row {index} {name}: skipped; missing nd/Vd")
            continue
        issues = [PROVENANCE_WARNING]
        sell = coefficients(row,("AB","AD","AF","AC","AE","AG"))
        poly = coefficients(row,("AH","AI","AJ","AK","AL","AM"))
        model, coeff = ("sellmeier",sell) if sell else ("polynomial",poly)
        if coeff is None:
            coeff = ()
            issues.append("Missing/incomplete dispersion coefficients")
        if model == "polynomial":
            issues.append("CDGM polynomial: no supplied NIR index checkpoints; 1550nm unsupported without extrapolation opt-in")
        thermal = coefficients(row,("AO","AP","AQ","AR","AS","AT"))
        if thermal is None:
            issues.append("Missing/incomplete thermal coefficients")
        points = []
        air_wavelengths = []
        for c in range(3,23):
            label = text(rows[0][c-1]); value = number(row[c-1])
            nm = number(rows[1][c-1]) or number(label[1:])
            if nm and value is not None:
                points.append((air_to_vacuum(nm/1000),value))
                air_wavelengths.append(nm/1000)
        lo,hi = ((min(w for w,n in points),max(w for w,n in points))
                 if points else (air_to_vacuum(.365),air_to_vacuum(1.014)))
        # Domain is supplied index coverage, never inferred from transmission.
        if model == "polynomial":
            hi = min(hi,air_to_vacuum(1.014))
        tau = []
        for c in range(column_index_from_string("EC"),column_index_from_string("FK")+1):
            w,t = number(rows[1][c-1]),number(row[c-1])
            if w and t is not None and 0 <= t <= 1:
                tau.append((w/1000,t))
        cte = number(cell(row,"BZ"))
        if cte is None:
            issues.append("Missing low-temperature CTE")
        # Optional export columns must match their verified first-sheet headers.
        # A missing/changed export-only header does not break legacy imports.
        metadata_values = {}
        provenance = {"cte1": f"{sheet}!BZ{index}; alpha -30/70 C; source 1e-7/K -> SI 1/K"}
        for key, column, header, scale, unit in (
            ("cte2", "CA", "α100/300℃(10-7/K)", 1e-7, "source 1e-7/K -> SI 1/K; 100/300 C"),
            ("density", "CK", "ρ(g/cm3)", 1.0, "g/cm3"),
            ("dpgf", "BJ", "ΔPg,F", 1.0, "dimensionless; direct source deviation, not PgF"),
        ):
            if text(cell(rows[0], column)) == header:
                value = number(cell(row, column))
                metadata_values[key] = None if value is None else value * scale
                provenance[key] = f"{sheet}!{column}{index}; {header}; {unit}"
            else:
                provenance[key] = f"Unavailable: expected {header!r} at {sheet}!{column}1"
        air_range = ((min(air_wavelengths), max(air_wavelengths)) if air_wavelengths else None)
        if air_range is not None and model == "polynomial":
            air_range = (air_range[0], min(air_range[1], 1.014))
        provenance["wavelength_range_air"] = (
            f"{sheet}!C{index}:V{index}, headers rows 1/2; supplied index coverage on assumed reference-air axis in um; "
            "not transmission coverage or manufacturer-certified validity; polynomial upper limit 1.014 um"
        )
        metadata = AgfMetadata(
            cte1=None if cte is None else cte*1e-7,
            **metadata_values,
            cte2_temperature_range=(100.0, 300.0) if "cte2" in metadata_values else None,
            wavelength_range_air=air_range, provenance=provenance,
        )
        glasses.append(Glass(supplier="CDGM",name=name,code=text(cell(row,"B")),nd=nd,vd=vd,
            pgf=number(cell(row,"AY")),family=family(name),dispersion_model=model,dispersion=coeff,
            thermal=thermal,cte=None if cte is None else cte*1e-7,
            melt_frequency=text(cell(row,"HV")),price=number(cell(row,"HW")),
            transmission=tuple(sorted(tau)),source_file=str(path),source_sheet=sheet,source_row=index,
            source_hash=digest,remarks=text(cell(row,"HZ")),wavelength_range=(lo,hi),
            warnings=tuple(issues),checkpoints=tuple(points),agf_metadata=metadata))
    return glasses,notices
