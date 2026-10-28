"""SCHOTT Preferred-glasses first-sheet adapter; grouped B/C and SI CTE."""
from openpyxl.utils.cell import column_index_from_string
from glass_workbench.contracts import AgfMetadata, Glass
from glass_workbench.optics.dispersion import air_to_vacuum, SPECTRAL_LINES_AIR
from .models import cell, number, text, coefficients, family, require_headers

PROVENANCE_WARNING = (
    "SCHOTT thermal equation/range: official TIE-19 Aug2023, 0.365..1.014um vacuum/-100..140C; 1550nm is extrapolation. "
    "TIE-29 dispersion uses tabulated reference-air spectral wavelengths. Dry Ciddor reference20C/101325Pa/450ppm approximates unspecified catalog humidity/CO2."
)


def parse(rows,path,sheet,digest):
    require_headers(rows,[(1,"A","SCHOTT, Optical Glass"),(4,"A","Glass"),(4,"B","nd"),(4,"D","vd"),
                         (4,"G","B1"),(4,"H","B2"),(4,"I","B3"),(4,"J","C1"),(4,"K","C2"),(4,"L","C3"),
                         (4,"M","D0"),(4,"R","lambda"),(4,"DF","alpha -30/70"),(4,"FC","Glascode")])
    glasses,notices = [],[PROVENANCE_WARNING]
    for index,row in enumerate(rows[4:],5):
        name = text(cell(row,"A"))
        if not name:
            continue
        nd,vd = number(cell(row,"B")),number(cell(row,"D"))
        if nd is None or vd is None:
            notices.append(f"Row {index} {name}: skipped; not a glass record with nd/Vd")
            continue
        issues = [PROVENANCE_WARNING]
        coeff = coefficients(row,("G","H","I","J","K","L"))
        thermal = coefficients(row,("M","N","O","P","Q","R"))
        if coeff is None:
            issues.append("Missing/incomplete dispersion coefficients")
        if thermal is None:
            issues.append("Missing/incomplete thermal coefficients")
        points = []
        air_wavelengths = []
        for c in range(column_index_from_string("DM"),column_index_from_string("EI")+1):
            label = text(rows[3][c-1])[1:]
            value = number(row[c-1])
            wave = SPECTRAL_LINES_AIR.get(label)
            # Workbook abbreviated NIR labels refer to TIE-29 standard lines.
            overrides = {"2325.4":2.32542,"1970.1":1.97009,"1529.6":1.529582,
                         "334.1":.3341478,"312.6":.3125663,"296.7":.2967278}
            if wave is None:
                nm = number(label)
                wave = overrides.get(label,nm/1000 if nm else None)
            if wave and value is not None:
                points.append((air_to_vacuum(wave),value))
                air_wavelengths.append(wave)
        lo,hi = ((min(w for w,n in points),max(w for w,n in points))
                 if points else (air_to_vacuum(.365),air_to_vacuum(1.014)))
        tau = []
        for c,label in enumerate(rows[3]):
            label = text(label)
            if label.startswith("TAUI10/"):
                w,t = number(label.split("/")[1]),number(row[c])
                if w and t is not None and 0 <= t <= 1:
                    tau.append((w/1000,t))
        cte = number(cell(row,"DF"))
        if cte is None:
            issues.append("Missing low-temperature CTE")
        # Workbook headers omit units. Retain the existing SCHOTT ppm/K
        # convention explicitly, rather than claiming a unit is in the header.
        metadata_values = {}
        provenance = {"cte1": f"{sheet}!DF{index}; alpha -30/70 C; source 1e-6/K -> SI 1/K; existing SCHOTT unit convention"}
        for key, column, header, scale, unit in (
            ("cte2", "DG", "alpha 20/300", 1e-6, "source 1e-6/K -> SI 1/K; existing SCHOTT unit convention; 20/300 C, not 100/300 C"),
            ("density", "CZ", "Density", 1.0, "g/cm3; SCHOTT catalog convention, unit not in workbook header"),
            ("dpgf", "FA", "DP g,F", 1.0, "dimensionless; direct source deviation, not PgF"),
        ):
            if text(cell(rows[3], column)) == header:
                value = number(cell(row, column))
                metadata_values[key] = None if value is None else value * scale
                provenance[key] = f"{sheet}!{column}{index}; {header}; {unit}"
            else:
                provenance[key] = f"Unavailable: expected {header!r} at {sheet}!{column}4"
        provenance["wavelength_range_air"] = (
            f"{sheet}!DM{index}:EI{index}, row 4 labels with existing TIE-29 spectral-line mapping; "
            "supplied reference-air index coverage in um, not transmission coverage or manufacturer-certified validity"
        )
        metadata = AgfMetadata(
            cte1=None if cte is None else cte*1e-6,
            **metadata_values,
            cte2_temperature_range=(20.0, 300.0) if "cte2" in metadata_values else None,
            wavelength_range_air=(min(air_wavelengths), max(air_wavelengths)) if air_wavelengths else None,
            provenance=provenance,
        )
        glasses.append(Glass(supplier="SCHOTT",name=name,code=text(cell(row,"FC")),nd=nd,vd=vd,
            pgf=number(cell(row,"EP")),family=family(name),dispersion_model="sellmeier",dispersion=coeff or (),
            thermal=thermal,cte=None if cte is None else cte*1e-6,
            price=number(cell(row,"FF")),transmission=tuple(sorted(tau)),source_file=str(path),source_sheet=sheet,
            source_row=index,source_hash=digest,remarks=text(cell(row,"FD")),wavelength_range=(lo,hi),
            warnings=tuple(issues),checkpoints=tuple(points),agf_metadata=metadata))
    return glasses,notices
