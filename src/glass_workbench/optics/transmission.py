"""10-mm internal transmission; log-tau interpolation, never extrapolation.

Spectral sample coordinates are retained as nominal manufacturer um values;
bandwidth/air-vacuum convention is not documented for these transmission tables.
This is an estimate, not a measured value at an interpolated wavelength.
"""
from bisect import bisect_left
from math import exp, log, isfinite
from glass_workbench.contracts import Glass


def transmission_at(glass: Glass, wavelength_um: float) -> float | None:
    if not isfinite(wavelength_um) or wavelength_um <= 0:
        raise ValueError("Wavelength must be finite and positive")
    samples = sorted(glass.transmission)
    if not samples:
        return None
    if any(not isfinite(w) or w <= 0 or not isfinite(t) or not 0 <= t <= 1 for w,t in samples):
        raise ValueError(f"{glass.uid}: invalid internal transmission samples")
    i = bisect_left([v[0] for v in samples], wavelength_um)
    if i < len(samples) and abs(samples[i][0]-wavelength_um) < 1e-12:
        return samples[i][1]
    if i == 0 or i == len(samples):
        return None
    w0,t0 = samples[i-1]
    w1,t1 = samples[i]
    # Zero is a rounded/censored transmission; log(0) cannot be interpolated.
    if t0 <= 0 or t1 <= 0:
        return None
    q = (wavelength_um-w0)/(w1-w0)
    return exp((1-q)*log(t0)+q*log(t1))
