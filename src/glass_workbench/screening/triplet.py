"""Presentation-equation triplets, enumerated exhaustively in bounded batches."""
from dataclasses import dataclass, field
from itertools import combinations_with_replacement
import math

import numpy as np

from ..contracts import Environment, SearchResult
from ..optics import thermal, transmission
from .search import (batches, unique_glasses, keep_best, finite_positive,
                     positive_integer, base_metadata, finish_metadata)


@dataclass(frozen=True)
class TripletSettings:
    wavelength_um: float = 1.55
    temperature_c: float = 20.0
    efl_mm: float = 90.0
    housing_cte_ppm: float = 23.6
    max_power: float = 8.0
    min_transmission: float = 0.97
    sign_pattern: str = "Cooke + - +"
    top_k: int = 50
    environment: Environment = field(default_factory=Environment)
    allow_extrapolation: bool = False
    batch_size: int = 4096
    condition_limit: float = 1e8
    residual_tolerance: float = 1e-9
    sign_tolerance: float = 1e-10
    allow_unknown_transmission: bool = False


def _transmission_bracket(glass, wavelength):
    waves = sorted({w for w, _ in glass.transmission})
    exact = [w for w in waves if abs(w-wavelength) < 1e-12]
    if exact:
        return (exact[0], exact[0])
    below, above = [w for w in waves if w < wavelength], [w for w in waves if w > wavelength]
    return (max(below), min(above)) if below and above else ()


def search_triplets(glasses, settings=TripletSettings(), progress=None, cancelled=None):
    """Solve sum(y)=1, sum(y*psi)=-CTE_h, sum(y/n)=0.

    Combinations with replacement include repeated glasses, but repeated columns
    are explicitly singular: no arbitrary pseudoinverse split is ranked. Cooke
    mode reorders a two-positive/one-negative solution into + - +. Unrestricted
    mode retains UID ordering; it does not pretend to be a Cooke prescription.
    """
    s = settings
    for name in ("wavelength_um", "efl_mm", "max_power", "condition_limit", "residual_tolerance"):
        finite_positive(name, getattr(s, name))
    finite_positive("sign_tolerance", s.sign_tolerance, zero=True)
    for name in ("batch_size", "top_k"):
        positive_integer(name, getattr(s, name))
    if not math.isfinite(s.temperature_c) or not math.isfinite(s.housing_cte_ppm):
        raise ValueError("Temperature and housing CTE must be finite")
    if not 0 <= s.min_transmission <= 1:
        raise ValueError("min_transmission must be between 0 and 1")
    if s.sign_pattern not in ("Cooke + - +", "unrestricted", "Unrestricted", "Unrestricted presentation-style"):
        raise ValueError("sign_pattern must be 'Cooke + - +' or 'unrestricted'")
    pool, duplicates = unique_glasses(glasses)
    meta = base_metadata(pool, s, duplicates)
    meta.update({
        "algorithm": "exhaustive unordered combinations with replacement; bounded batched scaled 3x3 solve",
        "coverage": "all unordered eligible triples, including explicitly rejected singular repetitions",
        "assumptions": ["Thin lenses; normalized powers y=efl/f_i; not a full prescription",
                        "psi=dn_relative/dT/(n_relative-1)-glass_CTE; all CTE in 1/K",
                        "Petzval equation follows supplied presentation: sum(y/n)=0",
                        "10-mm internal transmission; same-thickness log-interpolation; no coating/assembly loss",
                        "Row equilibration uses global eligible-pool RMS; condition number is dimensionless",
                        "Repeated glass columns and other singular systems excluded, not pseudoinverted",
                        "No thermal/ray aberration or f-number performance guarantee"],
        "transmission_policy": (
            "Unknown 10-mm internal transmission explicitly allowed; known values must still meet the threshold. "
            "Rows containing unknown values have transmission_min=None and are NOT verified to meet the transmission requirement."
            if s.allow_unknown_transmission else
            "Require known 10-mm internal transmission meeting the threshold; unknown values are rejected even at threshold zero."
        ),
        "source_records": [{"glass_id": g.uid, "supplemental": g.supplemental,
                            "source_file": g.source_file, "source_sheet": g.source_sheet,
                            "source_row": g.source_row, "source_hash": g.source_hash,
                            "source_urls": g.source_urls, "thermal_model": g.thermal_model} for g in pool],
        "warnings": (["Unknown transmission opt-in enabled: candidates with missing data are not transmission-qualified."]
                     if s.allow_unknown_transmission else []),
    })
    eligible, ns, psis, taus, glass_warnings = [], [], [], [], []
    stopped = False
    for i, g in enumerate(pool):
        if cancelled and cancelled():
            stopped = True
            break
        reason = None
        try:
            if g.cte is None or not math.isfinite(g.cte):
                reason = "missing_cte"
            else:
                tr = thermal.evaluate(g, s.wavelength_um, s.temperature_c,
                                      environment=s.environment, allow_extrapolation=s.allow_extrapolation)
                tau = transmission.transmission_at(g, s.wavelength_um)
                n = tr.n_relative
                psi = tr.dn_relative / (n - 1) - g.cte
                if not np.isfinite([n, psi]).all() or n <= 1:
                    reason = "invalid_optical_values"
                elif tau is None and not s.allow_unknown_transmission:
                    reason = "missing_transmission"
                elif tau is not None and (not math.isfinite(tau) or not 0 <= tau <= 1):
                    reason = "invalid_transmission"
                elif tau is not None and tau < s.min_transmission:
                    reason = "transmission_below_threshold"
                else:
                    eligible.append(g)
                    ns.append(n)
                    psis.append(psi)
                    taus.append(tau)
                    warnings = g.warnings + tr.warnings
                    if tau is None:
                        warnings += (f"{g.uid}: unknown 10-mm internal transmission at {s.wavelength_um:g} um; transmission requirement unverified",)
                    glass_warnings.append(tuple(sorted(set(warnings))))
                    meta["warnings"].extend(warnings)
        except (ValueError, ArithmeticError) as exc:
            reason = "optical_model_unavailable"
            meta["warnings"].append(f"{g.uid}: {exc}")
        if reason:
            meta["glass_rejection_reasons"][reason] += 1
        if progress and (i % 32 == 0 or i + 1 == len(pool)):
            progress(i + 1, len(pool), "Checking triplet glass eligibility")
    meta["warnings"] = sorted(set(meta["warnings"]))
    meta["unknown_transmission_glasses"] = tuple(g.uid for g, tau in zip(eligible, taus) if tau is None)
    meta["eligible_unknown_transmission_count"] = len(meta["unknown_transmission_glasses"])
    meta["eligible_glass_count"] = len(eligible)
    meta["rejected_glass_count"] = sum(meta["glass_rejection_reasons"].values())
    meta["unchecked_glass_count"] = len(pool) - len(eligible) - meta["rejected_glass_count"]
    total = math.comb(len(eligible) + 2, 3)
    meta["candidate_count"] = total
    if stopped or not eligible:
        return SearchResult([], finish_metadata(meta, []), stopped)
    ns, psis = map(np.asarray, (ns, psis))
    # NaN is an internal mask only; public rows preserve missing values as None.
    taus = np.asarray([np.nan if tau is None else tau for tau in taus], dtype=float)
    scale = np.array([1., max(float(np.sqrt(np.mean(psis**2))), abs(s.housing_cte_ppm)*1e-6, 1e-12),
                      float(np.sqrt(np.mean((1/ns)**2)))])
    rhs = np.array([1., -s.housing_cte_ppm*1e-6, 0.]) / scale
    meta["equation_row_scales"] = scale.tolist()
    rows = []
    for chunk in batches(combinations_with_replacement(range(len(eligible)), 3), s.batch_size):
        if cancelled and cancelled():
            stopped = True
            break
        idx = np.asarray(chunk)
        size = len(idx)
        reasons = np.full(size, "", dtype=object)
        repeated = (idx[:, 0] == idx[:, 1]) | (idx[:, 1] == idx[:, 2])
        reasons[repeated] = "repeated_glass_singular"
        a = np.stack((np.ones((size, 3)), psis[idx], 1/ns[idx]), axis=1) / scale[None, :, None]
        sv = np.linalg.svd(a, compute_uv=False)
        cond = np.divide(sv[:, 0], sv[:, -1], out=np.full(size, np.inf), where=sv[:, -1] > 0)
        bad = (cond > s.condition_limit) & ~repeated
        reasons[bad] = "ill_conditioned_or_singular"
        good = np.flatnonzero(reasons == "")
        powers = np.full((size, 3), np.nan)
        if len(good):
            powers[good] = np.linalg.solve(a[good], np.broadcast_to(rhs, (len(good), 3))[..., None])[..., 0]
            residual = np.max(np.abs(np.einsum("bij,bj->bi", a[good], powers[good]) - rhs), axis=1)
            reasons[good[~np.isfinite(powers[good]).all(axis=1) | (residual > s.residual_tolerance)]] = "unstable_residual"
            reasons[good[(np.max(np.abs(powers[good]), axis=1) > s.max_power) & (reasons[good] == "")]] = "power_bound"
        if s.sign_pattern == "Cooke + - +":
            cooke = ((powers > s.sign_tolerance).sum(axis=1) == 2) & ((powers < -s.sign_tolerance).sum(axis=1) == 1)
            reasons[(reasons == "") & ~cooke] = "sign_pattern"
        accepted = np.flatnonzero(reasons == "")
        rms = np.sqrt(np.mean(powers[accepted]**2, axis=1))
        # Build at most top_k dictionaries per batch, not millions of Python rows.
        selected = sorted(zip(rms, accepted), key=lambda p: (p[0], tuple(idx[p[1]])))[:s.top_k]
        new = []
        for score, j in selected:
            order = list(range(3))
            y = powers[j]
            if s.sign_pattern == "Cooke + - +":
                pos = np.flatnonzero(y > s.sign_tolerance)
                neg = np.flatnonzero(y < -s.sign_tolerance)
                order = [int(pos[0]), int(neg[0]), int(pos[1])]
            ids = idx[j, order]
            y = y[order]
            names = tuple(eligible[k].uid for k in ids)
            row_taus = taus[ids]
            known = np.isfinite(row_taus)
            known_min = float(row_taus[known].min()) if known.any() else None
            unknown = tuple(name for name, is_known in zip(names, known) if not is_known)
            new.append({"glasses": " / ".join(names), "glass_ids": names,
                        "powers": tuple(map(float, y)), "score": float(score), "rms_power": float(score),
                        "thermal_residual_per_k": float(y @ psis[ids] + s.housing_cte_ppm*1e-6),
                        "petzval_residual": float(y @ (1/ns[ids])), "power_residual": float(y.sum()-1),
                        "condition_scaled": float(cond[j]),
                        "transmission_min": None if unknown else known_min,
                        "transmission_known_min": known_min,
                        "transmission_values": tuple(float(tau) if is_known else None for tau, is_known in zip(row_taus, known)),
                        "transmission_complete": not unknown,
                        "unknown_transmission_glasses": unknown,
                        "transmission_estimated": bool(known.any()),
                        "supplemental_glasses": tuple(eligible[k].uid for k in ids if eligible[k].supplemental),
                        "source_urls": tuple(sorted({url for k in ids for url in eligible[k].source_urls})),
                        "transmission_source_wavelengths_um": tuple(_transmission_bracket(eligible[k], s.wavelength_um) for k in ids),
                        "warnings": tuple(sorted({w for k in ids for w in glass_warnings[k]})),
                        "extrapolation_allowed": s.allow_extrapolation,
                        "focal_lengths_mm": tuple(float(s.efl_mm/p) if p else math.inf for p in y)})
        rows = keep_best(rows, new, s.top_k)
        meta["evaluated_count"] += size
        meta["accepted_count"] += len(accepted)
        meta["rejected_count"] += size - len(accepted)
        for reason in reasons[reasons != ""]:
            meta["candidate_rejection_reasons"][reason] += 1
        if progress:
            progress(meta["evaluated_count"], total, "Solving triplet combinations")
    return SearchResult(rows, finish_metadata(meta, rows), stopped)
