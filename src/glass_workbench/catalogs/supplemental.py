"""Two bundled, explicitly sourced materials; no workbook/CSV dependency.

Missing 10-mm internal transmission and prices deliberately remain unknown.
The 2014 complete Corning brochure cross-check is disclosed, not represented
as a successful full download of the user-supplied 2015 edition.
"""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from glass_workbench.contracts import Glass
from glass_workbench.optics.supplemental import (
    CORNING_7980_SELLMEIER, CORNING_7980_DN, CORNING_RANGE, SILICON_RANGE,
    SILICON_CHARMS_COEFFICIENTS,
)


def _record_hash(glass: Glass) -> str:
    """SHA256 of the bundled record and numeric model, NOT a source PDF hash."""
    record = asdict(glass)
    record.pop("source_hash")
    record["model_coefficients"] = (
        (CORNING_7980_SELLMEIER, CORNING_7980_DN) if glass.dispersion_model == "corning_7980"
        else SILICON_CHARMS_COEFFICIENTS)
    record["reference_convention"] = (
        "N2-relative approximated dry Ciddor 101325Pa 450ppm" if glass.dispersion_model == "corning_7980"
        else "absolute vacuum wavelength kelvin")
    return sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()

CORNING_URL = "https://www.corning.com/media/worldwide/csm/documents/HPFS_Product_Brochure_All_Grades_2015_07_21.pdf"
CORNING_CROSSCHECK_URL = "https://www.edmundoptics.de/ViewDocument/Corning%20Fused%20Silica%20Grades.pdf"
SILICON_URL = "https://arxiv.org/pdf/physics/0606168"
SILICON_CTE_URL = "https://www.ioffe.ru/SVA/NSM/Semicond/Si/thermal.html"


def supplemental_glasses() -> list[Glass]:
    """Fresh list: Corning:HPFS 7980 and Infrared:Silicon, in that order."""
    records = [
        Glass(
            supplier="Corning", name="HPFS 7980", code="7980",
            nd=1.458461, vd=(1.458461-1)/(1.463123-1.456364),
            pgf=(1.466691-1.463123)/(1.463123-1.456364),
            family="Fused silica", dispersion_model="corning_7980",
            dispersion=CORNING_7980_SELLMEIER, thermal_model="corning_7980",
            cte=.52e-6, reference_temperature=22., wavelength_range=CORNING_RANGE,
            supplemental=True, visible_applicable=True,
            source_file="Corning HPFS product brochure (2015 URL; complete 2014 cross-check)",
            source_sheet="Refractive Index and Dispersion: HPFS 7980; Thermal Properties",
            source_urls=(CORNING_URL, CORNING_CROSSCHECK_URL),
            checkpoints=((.587725, 1.458461), (.486269, 1.463123),
                         (.656454, 1.456364), (1.128950, 1.448866)),
            remarks="Vacuum wavelength; 22 C, 760 mmHg N2. Actual 7980 table, not 7979/8655. "
                    "CTE 0.52 ppm/K is average over 5..35 C. See model notes for unverified index reference.",
            warnings=(
                "Corning source-reference assumption UNVERIFIED: n and dn/dT treated as nitrogen-relative; nitrogen approximated by dry Ciddor air at 101325 Pa, 450 ppm CO2",
                "Corning 2015 URL partial retrieval only; constants/table cross-checked against complete Corning February 2014 brochure (Edmund copy)",
                "Corning HPFS 7980 source fit 0.184950..1.128950 um vacuum; thermal coefficient 20..25 C, linear temperature approximation",
                "Corning CTE 0.52 ppm/K is a 5..35 C average, not a temperature-dependent model",
                "Comparable 10-mm internal transmission unknown; price unknown",
            ),
        ),
        Glass(
            supplier="Infrared", name="Silicon", code="Si-CHARMS-2006",
            nd=None, vd=None, pgf=None, family="Infrared crystalline material",
            dispersion_model="silicon_charms", thermal_model="silicon_charms",
            cte=2.6e-6, reference_temperature=20., wavelength_range=SILICON_RANGE,
            supplemental=True, visible_applicable=False,
            source_file="Frey, Leviton & Madison 2006, Temperature-dependent refractive index of silicon and germanium",
            source_sheet="CHARMS Table 5 (Si); Ioffe Si thermal properties (CTE)",
            source_urls=(SILICON_URL, SILICON_CTE_URL),
            remarks="Absolute index; vacuum um and kelvin in CHARMS Table 5. "
                    "20..300 K, 1.1..5.6 um. Ioffe CTE 2.6 ppm/K is a nominal near-room-temperature screening value.",
            warnings=(
                "Silicon is IR-only: no visible nd/Vd/PgF and no visible extrapolation",
                "Silicon CHARMS absolute index fit: 20..300 K, 1.1..5.6 um vacuum; batch-specific, not a universal melt guarantee",
                "Silicon dn/dT is the analytic derivative of Table 5, not Table 4 interpolation; published Table 4 differs by about 9.5 ppm/K at 1.5 um, 295 K",
                "Silicon CTE 2.6 ppm/K is an Ioffe nominal value, not a cryogenic CTE model; source table does not specify its temperature interval",
                "Comparable 10-mm internal transmission unknown; price unknown",
            ),
        ),
    ]
    return [replace(glass, source_hash=_record_hash(glass)) for glass in records]
