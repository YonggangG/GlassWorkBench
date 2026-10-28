"""Absolute thermo-optic increment followed by exact relative/absolute quotient.

SCHOTT TIE-19 (Aug 2023), equations 2--7: T0=20C, wavelength in vacuum um,
D coefficients as supplied (no extra 1e-6 factor). Relative reference n is used
in the prefactor as explicitly permitted by TIE-19. Absolute reference n is
n_relative(T0)*n_air(T0), with reference atmosphere independent of user settings.
The SCHOTT stated coefficient range is .365..1.014 um and -100..140C.
1550nm is therefore extrapolated even for Sellmeier glasses, not just polynomial.
CDGM uses the same equation as a declared, table-tested working assumption:
manufacturer-specific range/air convention has not been independently verified.
"""
from math import isfinite
from glass_workbench.contracts import Glass, Environment, ThermalResult
from .air import _index, _derivative, _validate
from .dispersion import refractive_index, REFERENCE_ENVIRONMENT
from .supplemental import SUPPLEMENTAL_MODELS, source_absolute


def _relative_result(n_abs, dn_abs, wavelength_um, temperature_c, environment, messages):
    """Common exact quotient, shared by catalog and supplemental models."""
    na = _index(wavelength_um, temperature_c, environment)
    dna = _derivative(wavelength_um, temperature_c, environment)
    n_rel = n_abs/na
    dn_rel = (dn_abs-n_rel*dna)/na
    if not all(isfinite(v) for v in (n_abs,n_rel,dn_abs,dn_rel)) or n_abs <= 0:
        raise ValueError("Nonphysical thermal result")
    return ThermalResult(n_rel,n_abs,dn_rel,dn_abs,na,dna,tuple(dict.fromkeys(messages)))


def evaluate(glass: Glass, wavelength_um: float, temperature_c: float,
             environment: Environment = Environment(), allow_extrapolation: bool = False) -> ThermalResult:
    if not isfinite(temperature_c):
        raise ValueError("Temperature must be finite")
    _validate(wavelength_um, temperature_c, environment, domain=False)
    messages = list(glass.warnings)
    if glass.dispersion_model in SUPPLEMENTAL_MODELS or glass.thermal_model in SUPPLEMENTAL_MODELS or glass.supplemental:
        if glass.dispersion_model not in SUPPLEMENTAL_MODELS or glass.thermal_model != glass.dispersion_model:
            raise ValueError(f"{glass.uid}: unsupported or inconsistent supplemental model")
        n_abs, dn_abs, source_messages = source_absolute(
            glass, wavelength_um, temperature_c, allow_extrapolation)
        messages.extend(source_messages)
        try:
            _validate(wavelength_um, temperature_c, environment)
        except ValueError as exc:
            if not allow_extrapolation:
                raise
            messages.append("Air-model extrapolation: " + str(exc))
        return _relative_result(n_abs, dn_abs, wavelength_um, temperature_c, environment, messages)
    if glass.thermal_model != "catalog_d":
        raise ValueError(f"{glass.uid}: unsupported thermal model {glass.thermal_model}")
    if glass.thermal is None or len(glass.thermal) != 6 or not all(isfinite(x) for x in glass.thermal):
        raise ValueError(f"{glass.uid}: thermal coefficients unavailable")
    failures = [w for w in messages if w.startswith("THERMAL_TABLE_MISMATCH")]
    if failures and not allow_extrapolation:
        raise ValueError(f"{glass.uid}: {failures[0]}")
    if glass.supplier.upper() == "SCHOTT":
        outside = not (.365 <= wavelength_um <= 1.014 and -100 <= temperature_c <= 140)
        if outside:
            msg = "SCHOTT thermal extrapolation: TIE-19 states 0.365..1.014 um vacuum and -100..140 C"
            if not allow_extrapolation:
                raise ValueError(msg)
            messages.append(msg)
    else:
        messages.append("CDGM thermal model convention/range unverified: standard D0..lambdaTK equation assumed; compare source interval tables")
        if not -60 <= temperature_c <= 140:
            if not allow_extrapolation:
                raise ValueError("CDGM temperature outside supplied thermal-table coverage -60..140 C")
            messages.append("CDGM temperature extrapolation beyond supplied thermal-table coverage")
    try:
        _validate(wavelength_um, temperature_c, environment)
    except ValueError as exc:
        if not allow_extrapolation:
            raise
        messages.append("Air-model extrapolation: " + str(exc))
    n0 = refractive_index(glass, wavelength_um, allow_extrapolation)
    if not glass.wavelength_range[0] <= wavelength_um <= glass.wavelength_range[1]:
        messages.append("Dispersion extrapolated beyond supplied spectral-index coverage")
    na0 = _index(wavelength_um, glass.reference_temperature, REFERENCE_ENVIRONMENT)
    dt = temperature_c-glass.reference_temperature
    d0,d1,d2,e0,e1,ltk = glass.thermal
    den = wavelength_um*wavelength_um-ltk*ltk
    if abs(den) < 1e-14:
        raise ValueError(f"{glass.uid}: thermal resonance pole")
    prefactor = (n0*n0-1)/(2*n0)
    change = prefactor*(d0*dt+d1*dt*dt+d2*dt**3+(e0*dt+e1*dt*dt)/den)
    dn_abs = prefactor*(d0+2*d1*dt+3*d2*dt*dt+(e0+2*e1*dt)/den)
    n_abs = n0*na0+change
    return _relative_result(n_abs, dn_abs, wavelength_um, temperature_c, environment, messages)
