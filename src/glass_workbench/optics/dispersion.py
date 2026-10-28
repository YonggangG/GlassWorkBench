"""Reference-temperature relative dispersion with a vacuum-wavelength API.

SCHOTT TIE-29 Table 1/section 3: fit uses tabulated spectral-line wavelengths
(the conventional air values). Convert vacuum to the fixed reference atmosphere,
NOT the current user atmosphere. This also matches the CDGM workbook checkpoints.
Reference air is approximated by dry Ciddor air, 20 C, 101325 Pa, 450 ppm CO2;
manufacturer humidity/CO2 for the tabulated wavelength scale is not specified.
"""
from math import isfinite, sqrt
import warnings
from glass_workbench.contracts import Glass, Environment
from .air import _index, _validate
from .supplemental import SUPPLEMENTAL_MODELS, source_absolute

REFERENCE_ENVIRONMENT = Environment()
SPECTRAL_LINES_AIR = {"C": .6562725, "d": .5875618, "F": .4861327,
                      "e": .546074, "g": .4358343, "t": 1.01398,
                      "C'": .6438469, "F'": .4799914, "r": .7065188,
                      "s": .85211, "D": .5892938, "h": .4046561,
                      "i": .3650146}


def air_to_vacuum(wavelength_air_um: float, reference_temperature: float = 20.0) -> float:
    """Convert a catalog spectral wavelength in fixed reference air to vacuum."""
    if not isfinite(wavelength_air_um) or wavelength_air_um <= 0:
        raise ValueError("Wavelength must be finite and positive")
    vacuum = wavelength_air_um
    for _ in range(4):
        vacuum = wavelength_air_um * _index(vacuum, reference_temperature, REFERENCE_ENVIRONMENT)
    return vacuum


SPECTRAL_LINES_VACUUM = {k: air_to_vacuum(v) for k,v in SPECTRAL_LINES_AIR.items()}


def catalog_index(glass: Glass, wavelength_air_um: float) -> float:
    """Evaluate coefficients on the catalog air-wavelength axis (for audit only)."""
    if glass.dispersion_model in SUPPLEMENTAL_MODELS:
        raise ValueError(f"{glass.uid}: source uses vacuum wavelengths; use refractive_index, not catalog_index")
    c = glass.dispersion
    if len(c) != 6 or not all(isfinite(v) for v in c):
        raise ValueError(f"{glass.uid}: missing or invalid dispersion coefficients")
    q = wavelength_air_um**2
    if glass.dispersion_model == "sellmeier":
        if any(abs(q-v) < 1e-14 for v in c[3:]):
            raise ValueError(f"{glass.uid}: Sellmeier pole")
        n2 = 1 + sum(c[i]*q/(q-c[i+3]) for i in range(3))
    elif glass.dispersion_model == "polynomial":
        n2 = c[0]+c[1]*q+c[2]/q+c[3]/q**2+c[4]/q**3+c[5]/q**4
    else:
        raise ValueError(f"{glass.uid}: unsupported dispersion model {glass.dispersion_model}")
    if not isfinite(n2) or n2 <= 0:
        raise ValueError(f"{glass.uid}: nonphysical squared refractive index")
    return sqrt(n2)


def refractive_index(glass: Glass, wavelength_um: float, allow_extrapolation: bool = False) -> float:
    """Index relative to fixed reference air at glass.reference_temperature."""
    if not isfinite(wavelength_um) or wavelength_um <= 0:
        raise ValueError("Wavelength must be finite and positive")
    if glass.dispersion_model in SUPPLEMENTAL_MODELS:
        n_abs, _, messages = source_absolute(glass, wavelength_um, glass.reference_temperature, allow_extrapolation)
        try:
            _validate(wavelength_um, glass.reference_temperature, REFERENCE_ENVIRONMENT)
        except ValueError as exc:
            if not allow_extrapolation:
                raise
            messages = (*messages, "Air-model extrapolation: " + str(exc))
        for message in (*glass.warnings, *messages):
            warnings.warn(message, RuntimeWarning, stacklevel=2)
        return n_abs/_index(wavelength_um, glass.reference_temperature, REFERENCE_ENVIRONMENT)
    if glass.supplemental or glass.thermal_model in SUPPLEMENTAL_MODELS:
        raise ValueError(f"{glass.uid}: unsupported supplemental model {glass.dispersion_model}")
    failures = [w for w in glass.warnings if w.startswith("DISPERSION_CHECKPOINT_MISMATCH")]
    if failures and not allow_extrapolation:
        raise ValueError(f"{glass.uid}: {failures[0]}")
    lo, hi = glass.wavelength_range  # stored on the public vacuum axis
    if not lo-1e-12 <= wavelength_um <= hi+1e-12:
        message = f"{glass.uid}: dispersion extrapolation outside {lo:.6g}..{hi:.6g} um vacuum"
        if not allow_extrapolation:
            raise ValueError(message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
    air_wave = wavelength_um/_index(wavelength_um, glass.reference_temperature, REFERENCE_ENVIRONMENT)
    return catalog_index(glass, air_wave)
