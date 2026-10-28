"""Shared, GUI-independent contracts for catalog, optics and search modules.

Wavelengths are vacuum micrometers at public calculation boundaries. Catalog
spectral-line conventions must be handled explicitly by the optics module.
"""
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass(frozen=True)
class AgfMetadata:
    """Optional source data for AGF export; never used by optical calculations.

    CTEs are SI 1/K, density is g/cm3, dpgf is the directly tabulated
    deviation (not PgF). None means unavailable, not zero. The air-axis
    range is supplied index coverage, not manufacturer-certified validity.
    Provenance maps field names to source cells, units and conventions.
    """

    cte1: float | None = None
    cte2: float | None = None
    density: float | None = None
    dpgf: float | None = None
    cte2_temperature_range: tuple[float, float] | None = None  # degrees C
    wavelength_range_air: tuple[float, float] | None = None  # um
    provenance: dict[str, str] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class Glass:
    supplier: str
    name: str
    code: str
    nd: float | None
    vd: float | None
    pgf: float | None = None
    family: str = "Other"
    dispersion_model: str = "sellmeier"
    # Sellmeier: B1,B2,B3,C1,C2,C3; polynomial: A0,...,A5.
    dispersion: tuple[float, ...] = ()
    thermal: tuple[float, ...] | None = None  # D0,D1,D2,E0,E1,lambdaTK
    cte: float | None = None  # 1/K, low-temperature interval
    melt_frequency: str = ""
    price: float | None = None  # supplier-native, NOT cross-vendor comparable
    transmission: tuple[tuple[float, float], ...] = ()  # (um, internal tau at 10 mm)
    source_file: str = ""
    source_sheet: str = ""
    source_row: int = 0
    source_hash: str = ""
    remarks: str = ""
    reference_temperature: float = 20.0
    wavelength_range: tuple[float, float] = (0.365, 2.325)
    warnings: tuple[str, ...] = ()
    checkpoints: tuple[tuple[float, float], ...] = ()
    supplemental: bool = False
    visible_applicable: bool = True
    thermal_model: str = "catalog_d"
    source_urls: tuple[str, ...] = ()
    agf_metadata: AgfMetadata | None = None

    @property
    def uid(self) -> str:
        return f"{self.supplier}:{self.name}"


@dataclass
class Catalog:
    supplier: str
    path: str
    sheet: str
    sha256: str
    glasses: list[Glass]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Environment:
    pressure_pa: float = 101325.0
    relative_humidity: float = 0.0  # fraction, not percent
    co2_ppm: float = 450.0
    hold: str = "relative_humidity"  # or water_mole_fraction


@dataclass(frozen=True)
class ThermalResult:
    n_relative: float
    n_absolute: float
    dn_relative: float  # per K
    dn_absolute: float
    n_air: float
    dn_air: float
    warnings: tuple[str, ...] = ()


@dataclass
class SearchResult:
    rows: list[dict[str, Any]]
    metadata: dict[str, Any]
    cancelled: bool = False


Progress = Callable[[int, int, str], None]
Cancelled = Callable[[], bool]
