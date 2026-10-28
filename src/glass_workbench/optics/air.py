"""Ciddor (1996) phase index, vacuum wavelength in um, temperature in Celsius.

Full moist-air density/compressibility formulation, not a linear temperature
scaling. Constants follow Ciddor, Applied Optics 35, 1566 (1996), DOI
10.1364/AO.35.001566. NIST documentation: https://emtoolbox.nist.gov/wavelength/Documentation.asp
NIST uses slightly different saturation-pressure/gas constants (sub-ppb effects).
Public domain: 0.3..1.7 um, -40..100 C, 10..140 kPa, 0..2000 ppm CO2.
Below freezing, RH is relative to ice (Ciddor saturation equation).
"""
from math import exp, isfinite
from glass_workbench.contracts import Environment


def _validate(wavelength_um, temp_c, environment, *, domain=True):
    vals = (wavelength_um, temp_c, environment.pressure_pa,
            environment.relative_humidity, environment.co2_ppm)
    if not all(isfinite(v) for v in vals):
        raise ValueError("Air inputs must be finite")
    if wavelength_um <= 0 or temp_c <= -273.15 or environment.pressure_pa <= 0:
        raise ValueError("Wavelength, absolute temperature and pressure must be positive")
    if not 0 <= environment.relative_humidity <= 1:
        raise ValueError("Relative humidity must be a fraction from 0 to 1")
    if not 0 <= environment.co2_ppm <= 2000:
        raise ValueError("CO2 must be between 0 and 2000 ppm")
    if environment.hold not in {"relative_humidity", "water_mole_fraction"}:
        raise ValueError("Unknown air derivative hold condition")
    if domain and not (0.3 <= wavelength_um <= 1.7 and -40 <= temp_c <= 100
                       and 10000 <= environment.pressure_pa <= 140000):
        raise ValueError("Outside implemented Ciddor domain: 0.3..1.7 um, -40..100 C, 10..140 kPa")


def _water_fraction(temp_c, env):
    t = temp_c + 273.15
    saturation = (exp(1.2378847e-5*t*t - 1.9121316e-2*t + 33.93711047 - 6343.1645/t)
                  if temp_c >= 0 else 10 ** (-2663.5/t + 12.537))
    enhancement = 1.00062 + 3.14e-8 * env.pressure_pa + 5.6e-7 * temp_c**2
    x = env.relative_humidity * enhancement * saturation / env.pressure_pa
    if not 0 <= x < 1:
        raise ValueError("Water-vapor mole fraction must be below one at this pressure/temperature")
    return x


def _compressibility(temp_c, pressure, x):
    t = temp_c + 273.15
    a = 1.58123e-6 - 2.9331e-8*temp_c + 1.1043e-10*temp_c**2
    b = (5.707e-6 - 2.051e-8*temp_c)*x + (1.9898e-4 - 2.376e-6*temp_c)*x*x
    return 1 - pressure/t*(a+b) + (pressure/t)**2*(1.83e-11 - 0.765e-8*x*x)


def _index(wavelength_um, temp_c, environment, water_fraction=None):
    """Internal equation; callers must validate and explicitly flag extrapolation."""
    x = _water_fraction(temp_c, environment) if water_fraction is None else water_fraction
    s2 = wavelength_um**-2
    nas = 1e-8*(5792105/(238.0185-s2) + 167917/(57.362-s2))
    naxs = nas*(1 + 0.534e-6*(environment.co2_ppm-450))
    nws = 1.022e-8*(295.235 + 2.6422*s2 - 0.032380*s2*s2 + 0.004028*s2**3)
    # Ratios of component densities; molar masses/R cancel in each ratio.
    p, t = environment.pressure_pa, temp_c+273.15
    z = _compressibility(temp_c, p, x)
    if z <= 0:
        raise ValueError("Nonphysical moist-air compressibility")
    dry_ratio = (p*(1-x)/(z*t)) / (101325/(_compressibility(15,101325,0)*288.15))
    wet_ratio = (p*x/(z*t)) / (1333/(_compressibility(20,1333,1)*293.15))
    return 1 + dry_ratio*naxs + wet_ratio*nws


def _derivative(wavelength_um, temp_c, environment):
    # Five-point derivative at fixed pressure/CO2 and the requested humidity hold.
    x = (_water_fraction(temp_c, environment)
         if environment.hold == "water_mole_fraction" else None)
    h = 0.01
    f = lambda t: _index(wavelength_um, t, environment, x)
    if abs(temp_c) < 2*h and x is None and environment.relative_humidity:
        # Ice/water saturation branches have different slopes at freezing.
        # Use the side selected by the input temperature, not a cross-branch stencil.
        direction = 1 if temp_c >= 0 else -1
        h *= direction
        return (-25*f(temp_c)+48*f(temp_c+h)-36*f(temp_c+2*h)+16*f(temp_c+3*h)-3*f(temp_c+4*h))/(12*h)
    return (f(temp_c-2*h)-8*f(temp_c-h)+8*f(temp_c+h)-f(temp_c+2*h))/(12*h)


def air_index(wavelength_um: float, temp_c: float, environment: Environment = Environment()) -> float:
    _validate(wavelength_um, temp_c, environment)
    return _index(wavelength_um, temp_c, environment)


def air_dn_dt(wavelength_um: float, temp_c: float, environment: Environment = Environment()) -> float:
    _validate(wavelength_um, temp_c, environment)
    return _derivative(wavelength_um, temp_c, environment)
