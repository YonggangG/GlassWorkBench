"""Import-time validation against independent cells; never tune source coefficients."""
from dataclasses import replace
import warnings
from glass_workbench.optics.dispersion import catalog_index, air_to_vacuum, REFERENCE_ENVIRONMENT
from glass_workbench.optics.air import _index
from glass_workbench.optics.thermal import evaluate
from .models import cell, number

DISPERSION_MISMATCH = "DISPERSION_CHECKPOINT_MISMATCH"
THERMAL_MISMATCH = "THERMAL_TABLE_MISMATCH"


def audit(glasses, rows):
    result = []
    for glass in glasses:
        issues = list(glass.warnings)
        errors = []
        for wave,n in glass.checkpoints:
            if not glass.dispersion:
                break
            try:
                predicted = catalog_index(glass,wave/_index(wave,glass.reference_temperature,REFERENCE_ENVIRONMENT))
                errors.append(abs(predicted-n))
            except ValueError:
                errors.append(float("inf"))
        # Source rounding + advertised typical fit precision, not a precision claim.
        limit = 1.1e-5 if glass.supplier == "SCHOTT" else 1e-5
        if errors and max(errors) > limit:
            issues.append(f"{DISPERSION_MISMATCH}: maximum supplied-index residual {max(errors):.3g} exceeds audit threshold {limit:g}; excluded by default")
        thermal_errors = []
        entries = ([(.546074,"Z","AC"),(.4358343,"AA","AD"),(1.06,"Y","AB")]
                   if glass.supplier == "SCHOTT" else
                   [(.54607,"GU",None),(.43583,"HO",None),(1.01398,"FQ",None),(.58756,"GK",None)])
        if glass.thermal and glass.dispersion:
            row = rows[glass.source_row-1]
            for wave,relcol,abscol in entries:
                targets = [(number(cell(row,col)),attr) for col,attr in
                           [(relcol,"n_relative"),(abscol,"n_absolute")] if col]
                targets = [(raw,attr) for raw,attr in targets if raw is not None]
                if not targets:
                    continue
                try:
                    # Only import-time audit knowingly evaluates source1060-nm outside
                    # SCHOTT's stated1014-nm limit. Result flags remain intact.
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore",message=".*dispersion extrapolation.*",category=RuntimeWarning)
                        a = evaluate(glass,air_to_vacuum(wave),20,allow_extrapolation=True)
                        b = evaluate(glass,air_to_vacuum(wave),40,allow_extrapolation=True)
                    for raw,attr in targets:
                        thermal_errors.append(abs((getattr(b,attr)-getattr(a,attr))/20*1e6-raw))
                except ValueError:
                    thermal_errors.append(float("inf"))
        # 0.3 ppm/K is a disclosed screening guard, not manufacturer precision.
        if thermal_errors and max(thermal_errors) > .3:
            issues.append(f"{THERMAL_MISMATCH}: maximum 20..40C interval-table residual {max(thermal_errors):.3g} ppm/K exceeds 0.3 ppm/K audit threshold; excluded by default")
        result.append(replace(glass,warnings=tuple(issues)))
    return result
