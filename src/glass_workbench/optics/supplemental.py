"""Source-native models for HPFS 7980 and CHARMS silicon.

All wavelengths here are VACUUM micrometers. See model_notes.txt for provenance
and the explicitly unverified Corning nitrogen/thermo-optic convention.
No generic fused-silica coefficients or silicon visible-index extrapolation.
"""
from math import isfinite, sqrt
from glass_workbench.contracts import Environment, Glass
from .air import _index, _derivative

SUPPLEMENTAL_MODELS = frozenset({"corning_7980", "silicon_charms"})
# Corning HPFS 7980 section, not the adjacent 7979/8655 table.
CORNING_7980_SELLMEIER = (.68374049400, .42032361300, .58502748000,
                         .00460352869, .01339688560, 64.49327320000)
CORNING_7980_DN = (9.390590, .235290, -1.318560e-3, 3.028870e-4)  # ppm/K
CORNING_RANGE = (.184950, 1.128950)
# Frey, Leviton & Madison (2006), Table 5. Rows are S1,S2,S3,L1,L2,L3;
# columns multiply T**0 through T**4 with T in kelvin. Li is in um, NOT um^2.
SILICON_CHARMS_COEFFICIENTS = (
    (10.4907, -2.08020e-4, 4.21694e-6, -5.82298e-9, 3.44688e-12),
    (-1346.61, 29.1664, -.278724, 1.05939e-3, -1.35089e-6),
    (4.42827e7, -1.76213e6, -7.61575e4, 678.414, 103.243),
    (.299713, -1.14234e-5, 1.67134e-7, -2.51049e-10, 2.32484e-14),
    (-3.51710e3, 42.3892, -.357957, 1.17504e-3, -1.13212e-6),
    (1.71400e6, -1.44984e5, -6.90744e3, -39.3699, 23.5770),
)
SILICON_RANGE = (1.1, 5.6)


def _inputs(wavelength_um: float, temperature_c: float) -> None:
    if not isfinite(wavelength_um) or wavelength_um <= 0:
        raise ValueError("Wavelength must be finite and positive")
    if not isfinite(temperature_c) or temperature_c <= -273.15:
        raise ValueError("Absolute temperature must be finite and positive")


def corning_7980_native(wavelength_um: float, temperature_c: float = 22.) -> tuple[float, float]:
    """Return source-convention n and dn/dT (1/K); no domain extrapolation gate.

    Linear temperature extension of the published 20..25 C derivative, anchored
    at 22 C. The caller must check domain; source n/dn reference is not explicit.
    """
    _inputs(wavelength_um, temperature_c)
    q = wavelength_um**2
    c = CORNING_7980_SELLMEIER
    if any(abs(q-x) < 1e-14 for x in c[3:]):
        raise ValueError("Corning HPFS 7980: Sellmeier pole")
    n2 = 1 + sum(c[i]*q/(q-c[i+3]) for i in range(3))
    if not isfinite(n2) or n2 <= 0:
        raise ValueError("Corning HPFS 7980: nonphysical squared index")
    dn = 1e-6*sum(cj/q**j for j, cj in enumerate(CORNING_7980_DN))
    return sqrt(n2)+(temperature_c-22.)*dn, dn


def silicon_charms_native(wavelength_um: float, temperature_c: float) -> tuple[float, float]:
    """CHARMS absolute n and analytic dn/dT (1/K); hard reject lambda <1.1 um.

    The source-native function permits scientific evaluation over the full
    cryogenic model without invoking atmospheric air outside its valid domain.
    source_absolute supplies the wavelength/temperature extrapolation policy.
    """
    _inputs(wavelength_um, temperature_c)
    if wavelength_um < 1.1:
        raise ValueError("Silicon: visible/short-wave use is physically excluded below 1.1 um, even with extrapolation")
    t = temperature_c+273.15
    values = [sum(cj*t**j for j, cj in enumerate(row)) for row in SILICON_CHARMS_COEFFICIENTS]
    derivatives = [sum(j*row[j]*t**(j-1) for j in range(1, 5)) for row in SILICON_CHARMS_COEFFICIENTS]
    q = wavelength_um**2
    n2, d_n2 = 1., 0.
    for i in range(3):
        s, l, ds, dl = values[i], values[i+3], derivatives[i], derivatives[i+3]
        den = q-l*l
        if abs(den) < 1e-14:
            raise ValueError("Silicon CHARMS: Sellmeier pole")
        n2 += s*q/den
        d_n2 += ds*q/den + 2*s*q*l*dl/den**2
    if not isfinite(n2) or n2 <= 0:
        raise ValueError("Silicon CHARMS: nonphysical squared index")
    n = sqrt(n2)
    return n, d_n2/(2*n)


def source_absolute(glass: Glass, wavelength_um: float, temperature_c: float,
                    allow_extrapolation: bool = False) -> tuple[float, float, tuple[str, ...]]:
    """Return absolute n, dn/dT and domain warnings before user-air conversion."""
    _inputs(wavelength_um, temperature_c)
    model = glass.dispersion_model
    if model not in SUPPLEMENTAL_MODELS:
        raise ValueError(f"Unsupported supplemental model {model}")
    messages = []
    if model == "silicon_charms" and wavelength_um < 1.1:
        raise ValueError("Silicon: visible/short-wave use is physically excluded below 1.1 um, even with extrapolation")
    lo, hi = CORNING_RANGE if model == "corning_7980" else SILICON_RANGE
    if not lo-1e-12 <= wavelength_um <= hi+1e-12:
        messages.append(f"{glass.uid}: dispersion extrapolation outside source fit {lo:g}..{hi:g} um vacuum")
    if model == "corning_7980":
        if not 20 <= temperature_c <= 25:
            messages.append("Corning HPFS 7980 thermal extrapolation: dn/dT fit is stated for 20..25 C only")
        if not .3 <= wavelength_um <= 1.7:
            messages.append("Corning reference-medium air approximation extrapolation beyond Ciddor 0.3..1.7 um")
    elif model == "silicon_charms":
        if not 20-1e-10 <= temperature_c+273.15 <= 300+1e-10:
            messages.append("Silicon CHARMS thermal extrapolation outside 20..300 K (-253.15..26.85 C)")
    else:
        raise ValueError(f"Unsupported supplemental model {model}")
    if messages and not allow_extrapolation:
        raise ValueError(messages[0])
    if model == "corning_7980":
        nr, dnr = corning_7980_native(wavelength_um, temperature_c)
        # Explicit working assumption: source n AND dn are N2-relative; N2 is
        # approximated by dry standard Ciddor air. The reference medium follows
        # temperature, independent of the USER environment. Product rule matters.
        reference = Environment()
        na = _index(wavelength_um, temperature_c, reference)
        dna = _derivative(wavelength_um, temperature_c, reference)
        n, dn = nr*na, dnr*na+nr*dna
    else:
        n, dn = silicon_charms_native(wavelength_um, temperature_c)
    if not all(isfinite(x) for x in (n, dn)) or n <= 0:
        raise ValueError(f"{glass.uid}: nonphysical supplemental result")
    return n, dn, tuple(messages)
