"""Visible thin cemented-triplet plus spaced singlet screening.

Powers and curvatures are normalized by target d-line EFL. The shared
interfaces are reconstructed, rather than treating cemented lenses as four
independent air lenses. Surface bending is a minimum-norm convention only.
"""
from dataclasses import dataclass
from itertools import product
import math

import numpy as np
from scipy.optimize import minimize

from ..contracts import SearchResult
from ..optics import dispersion
from .search import (unique_glasses, finite_positive, positive_integer,
                     base_metadata, finish_metadata, keep_best)


@dataclass(frozen=True)
class TelescopeSettings:
    efl_mm: float = 500.0
    gap_ratio: float = 0.1
    max_power: float = 8.0
    chromatic_weight: float = 1.0
    petzval_weight: float = 1.0
    top_k: int = 50
    candidate_limit: int = 3000
    refine_count: int = 100
    seed: int = 42
    exhaustive: bool = False
    positive_objective: bool = True
    allow_extrapolation: bool = False
    max_curvature_per_mm: float = 0.25
    regularization_weight: float = 1e-4
    exhaustive_limit: int = 10000
    refinement_iterations: int = 60


# c_i-c_(i+1) = y_i/(n_i-1); minimum Euclidean-norm surfaces.
_DIFFERENCE = np.array([[1., -1., 0., 0.], [0., 1., -1., 0.], [0., 0., 1., -1.]])
_SHARED = np.linalg.pinv(_DIFFERENCE)


def shared_curvatures(powers, indices_d):
    """Return six normalized curvatures (4 shared group + 2 singlet).

    Divide by EFL in mm for physical curvature in inverse mm. Each component
    has one unmodeled common bending degree of freedom, set to minimum norm.
    """
    y, n = np.asarray(powers, float), np.asarray(indices_d, float)
    if y.shape != (4,) or n.shape != (4,) or not np.isfinite(n).all() or np.any(n <= 1):
        raise ValueError("Four finite powers and four indices > 1 required")
    return np.r_[_SHARED @ (y[:3] / (n[:3]-1)), y[3] / (2*(n[3]-1)), -y[3] / (2*(n[3]-1))]


def system_matrix(group_power, singlet_power, gap):
    """ABCD in (height, angle), air on both ends: L_s T_gap L_g."""
    g, s = group_power, singlet_power
    return np.array([[1-gap*g, gap], [-(g+s-gap*g*s), 1-gap*s]], dtype=float)


def optical_metrics(powers, indices, gap_ratio):
    """Exact paraxial normalized C/d/F metrics for index array shape (3,4).

    bfl=-A/C is measured from the singlet to one common image plane; the
    chromatic residuals are BFL_C-BFL_d and BFL_F-BFL_d, divided by target EFL.
    """
    y, n = np.asarray(powers, float), np.asarray(indices, float)
    if y.shape != (4,) or n.shape != (3, 4):
        raise ValueError("Expected powers (4,) and indices (C,d,F)x(4,)")
    ratio = (n-1)/(n[1]-1)
    group = ratio[:, :3] @ y[:3]
    single = ratio[:, 3]*y[3]
    total = group+single-gap_ratio*group*single
    a = 1-gap_ratio*group
    with np.errstate(divide="ignore", invalid="ignore"):
        bfl, efl = a/total, 1/total
    q = shared_curvatures(y, n[1])
    # Telescoping interface sum [(n_after-n_before)/(n_before*n_after)]*c
    # equals sum_i (n_i-1)*(c_left-c_right)/n_i even at shared interfaces.
    petzval = np.sum(y*ratio/n, axis=1)
    return {"bfl": bfl, "efl": efl, "petzval": petzval,
            "curvatures": q, "group_power": group, "singlet_power": single,
            "total_power": total}


def _powers(x, gap):
    group, y1, y2 = x
    den = 1-gap*group
    if abs(den) < 1e-9:
        return None
    return np.array([y1, y2, group-y1-y2, (1-group)/den])


def _objective(y, n, s):
    m = optical_metrics(y, n, s.gap_ratio)
    b = m["bfl"]
    chromatic = float(np.sqrt(np.mean((b[[0, 2]]-b[1])**2)))
    petzval = float(m["petzval"][1])
    burden = float(np.mean((y/s.max_power)**2))
    score = math.sqrt(s.chromatic_weight*chromatic**2 + s.petzval_weight*petzval**2 + s.regularization_weight*burden)
    return score, chromatic, petzval, m


def _feasible(y, n, s):
    if y is None or not np.isfinite(y).all() or np.max(np.abs(y)) > s.max_power+1e-8:
        return False
    m = optical_metrics(y, n, s.gap_ratio)
    if s.positive_objective and m["group_power"][1] <= 1e-7:
        return False
    return (np.isfinite(m["bfl"]).all() and np.all(m["bfl"] > 1e-8)
            and np.all(m["total_power"] > 1e-8)
            and np.max(np.abs(m["curvatures"])) <= s.max_curvature_per_mm*s.efl_mm+1e-8
            and abs(m["total_power"][1]-1) < 1e-8)


def _coarse(n, s):
    """Fixed group-power grid, 2-variable regularized linear focus algebra.

    For fixed G_d and S_d, BFL_l=BFL_d is exactly the linear equation
    A_l - A_d P_l=0 in the three group-element powers. Evaluation thereafter
    uses exact ABCD BFL, not that linear surrogate.
    """
    ratio = (n-1)/(n[1]-1)
    best = None
    for group in (-4., -2., -1., -0.5, 0., 0.125, 0.25, 0.5, 1., 1.5, 2., 4.):
        if s.positive_objective and group <= 1e-7:
            continue
        y0 = _powers((group, 0., 0.), s.gap_ratio)
        if y0 is None or abs(y0[3]) > s.max_power:
            continue
        single = y0[3]*ratio[:, 3]
        ad = 1-s.gap_ratio*group
        coeff = -s.gap_ratio-ad*(1-s.gap_ratio*single)
        # R_l=(1-Ad*S_l)+coeff_l*G_l
        weights = np.sqrt(s.chromatic_weight/2)
        a = (coeff[[0, 2], None]*(ratio[[0, 2], :2]-ratio[[0, 2], 2, None]))*weights
        const = ((1-ad*single)+coeff*ratio[:, 2]*group)[[0, 2]]*weights
        p = 1/n[1]
        a = np.vstack((a, (p[:2]-p[2])*np.sqrt(s.petzval_weight)))
        const = np.r_[const, (group*p[2]+y0[3]*p[3])*np.sqrt(s.petzval_weight)]
        reg = math.sqrt(max(s.regularization_weight, 1e-14)/4)/s.max_power
        a = np.vstack((a, [[reg, 0], [0, reg], [-reg, -reg]]))
        const = np.r_[const, 0, 0, reg*group]
        v = np.linalg.lstsq(a, -const, rcond=None)[0]
        y = _powers((group, *v), s.gap_ratio)
        if _feasible(y, n, s):
            score = _objective(y, n, s)[0]
            if best is None or score < best[0]:
                best = (score, y)
    return best


def _candidate_indices(count, s):
    total = count**4  # Ordered cemented sequence + singlet, with replacement.
    if s.exhaustive:
        if total > s.exhaustive_limit:
            raise ValueError(f"Exhaustive pool has {total:,} ordered quadruples; explicit limit is {s.exhaustive_limit:,}. Select a smaller pool or bounded mode.")
        return product(range(count), repeat=4), total
    limit = min(total, s.candidate_limit)
    if total <= limit:
        return product(range(count), repeat=4), total
    rng = np.random.default_rng(s.seed)
    chosen, seen = [], set()
    # Rotating random permutations gives each glass each role before repeating
    # a cycle, when limit>=pool size. No prefix truncation of the input catalog.
    while len(chosen) < limit:
        permutations = [rng.permutation(count) for _ in range(4)]
        for i in range(count):
            t = tuple(int(p[i]) for p in permutations)
            if t not in seen:
                seen.add(t)
                chosen.append(t)
                if len(chosen) == limit:
                    break
    return iter(chosen), limit


class _Cancelled(Exception):
    pass


def _refine(y, n, s, cancelled):
    x0 = np.array([sum(y[:3]), y[0], y[1]])
    def objective(x):
        if cancelled and cancelled():
            raise _Cancelled
        trial = _powers(x, s.gap_ratio)
        if trial is None:
            return 1e12
        val = _objective(trial, n, s)[0]
        return val**2 if math.isfinite(val) else 1e12
    def bounds(x):
        trial = _powers(x, s.gap_ratio)
        if trial is None:
            return np.full(20, -1e9)
        m = optical_metrics(trial, n, s.gap_ratio)
        return np.r_[s.max_power-trial, s.max_power+trial,
                     s.max_curvature_per_mm*s.efl_mm-np.abs(m["curvatures"]),
                     m["total_power"]-1e-8, 1-s.gap_ratio*m["group_power"]-1e-7]
    group_lower = 1.01e-7 if s.positive_objective else -3*s.max_power
    result = minimize(objective, x0, method="SLSQP", bounds=[(group_lower, 3*s.max_power),
                      (-s.max_power, s.max_power), (-s.max_power, s.max_power)],
                      constraints={"type": "ineq", "fun": bounds},
                      options={"maxiter": s.refinement_iterations, "ftol": 1e-12})
    trial = _powers(result.x, s.gap_ratio)
    if _feasible(trial, n, s) and _objective(trial, n, s)[0] < _objective(y, n, s)[0]:
        return trial, bool(result.success)
    return y, bool(result.success)


def _row(ids, y, n, pool, s, refined=False):
    score, chromatic, petzval, m = _objective(y, n, s)
    names = tuple(pool[i].uid for i in ids)
    return {"glasses": " / ".join(names), "glass_ids": names, "powers": tuple(map(float, y)),
            "score": score, "chromatic_bfl_spread": float(np.ptp(m["bfl"])),
            "chromatic_bfl_rms": chromatic, "bfl_spread_mm": float(np.ptp(m["bfl"])*s.efl_mm),
            "petzval": petzval, "petzval_per_mm": petzval/s.efl_mm,
            "efl_d_mm": float(m["efl"][1]*s.efl_mm), "efl_error": float(m["efl"][1]-1),
            "bfl_c_mm": float(m["bfl"][0]*s.efl_mm), "bfl_d_mm": float(m["bfl"][1]*s.efl_mm),
            "bfl_f_mm": float(m["bfl"][2]*s.efl_mm),
            "efl_c_mm": float(m["efl"][0]*s.efl_mm), "efl_f_mm": float(m["efl"][2]*s.efl_mm),
            "group_power": float(m["group_power"][1]), "singlet_power": float(m["singlet_power"][1]),
            "power_max": float(np.max(np.abs(y))), "rms_power": float(np.sqrt(np.mean(y**2))),
            "power_residual": float(m["total_power"][1]-1),
            "curvature_max_per_mm": float(np.max(np.abs(m["curvatures"]))/s.efl_mm),
            "curvatures_per_mm": tuple(map(float, m["curvatures"]/s.efl_mm)),
            "shared_interface_residual": float(np.max(np.abs(_DIFFERENCE@m["curvatures"][:4]-y[:3]/(n[1, :3]-1)))),
            "refined": refined,
            "supplemental_glasses": tuple(pool[i].uid for i in ids if pool[i].supplemental),
            "source_urls": tuple(sorted({url for i in ids for url in pool[i].source_urls})),
            "warnings": tuple(sorted({w for i in ids for w in pool[i].warnings})),
            "extrapolation_allowed": s.allow_extrapolation}


def search_telescope(glasses, settings=TelescopeSettings(), progress=None, cancelled=None):
    s = settings
    for name in ("efl_mm", "max_power", "max_curvature_per_mm"):
        finite_positive(name, getattr(s, name))
    for name in ("gap_ratio", "chromatic_weight", "petzval_weight", "regularization_weight"):
        finite_positive(name, getattr(s, name), zero=True)
    if s.chromatic_weight+s.petzval_weight == 0:
        raise ValueError("At least one physical objective weight must be positive")
    for name in ("top_k", "candidate_limit", "exhaustive_limit", "refinement_iterations"):
        positive_integer(name, getattr(s, name))
    positive_integer("refine_count", s.refine_count, zero=True)
    positive_integer("seed", s.seed, zero=True)
    pool, duplicates = unique_glasses(glasses)
    meta = base_metadata(pool, s, duplicates)
    lines = tuple(dispersion.SPECTRAL_LINES_VACUUM[k] for k in ("C", "d", "F"))
    meta.update({"algorithm": "seeded role-balanced ordered quadruples with replacement; 12-point group-power coarse algebra; bounded SLSQP shortlist refinement",
                 "coverage": "best found within this screening search, not global optimum",
                 "spectral_lines_vacuum_um": dict(zip(("C", "d", "F"), lines)),
                 "visible_material_policy": "Materials marked visible_applicable=False are always rejected, even when dispersion extrapolation is enabled.",
                 "source_records": [{"glass_id": g.uid, "supplemental": g.supplemental,
                                     "visible_applicable": g.visible_applicable,
                                     "source_file": g.source_file, "source_sheet": g.source_sheet,
                                     "source_row": g.source_row, "source_hash": g.source_hash,
                                     "source_urls": g.source_urls} for g in pool],
                 "refined_count": 0, "refinement_converged_count": 0,
                 "assumptions": ["Visible C/d/F dispersion at catalog reference temperature; NO thermal or housing constraint",
                    "Spectral air-to-vacuum conversion follows shared dispersion model convention",
                    "Thin cemented three-glass group, air gap=gap_ratio*target_EFL, then thin singlet",
                    "Shared surfaces reconstructed with minimum-norm bending; one free bending DOF per component remains",
                    "Exact ABCD; positive target d EFL enforced by S=(1-G)/(1-gap_ratio*G); positive real BFL at all three lines",
                    "Ordered first three cemented glasses and fourth singlet; repetitions allowed, no Cooke sign restriction",
                    f"Positive d-line cemented objective required: {s.positive_objective}; corrective singlet sign unrestricted",
                    "Petzval is shared-interface-consistent sum(y_i/n_i) at d",
                    "Chromatic RMS of (BFL_C-BFL_d,BFL_F-BFL_d)/target_EFL; spread=max(BFL)-min(BFL)",
                    "score^2=chromatic_weight*chromatic_RMS^2+petzval_weight*Petzval^2+regularization_weight*mean((y/max_power)^2)",
                    "Continuous coarse/refined search is not globally complete even with exhaustive glass tuples",
                    "No spherical, astigmatism, spherochromatism, MTF, thickness or manufacturability prediction"],
                 "warnings": []})
    eligible, ns = [], []
    stopped = False
    for i, g in enumerate(pool):
        if cancelled and cancelled():
            stopped = True
            break
        if not g.visible_applicable:
            meta["glass_rejection_reasons"]["visible_material_inapplicable"] += 1
            meta["warnings"].append(f"{g.uid}: material is not applicable to visible C/d/F screening; extrapolation cannot override this restriction")
        else:
            try:
                n = [dispersion.refractive_index(g, line, allow_extrapolation=s.allow_extrapolation) for line in lines]
                if not np.isfinite(n).all() or min(n) <= 1:
                    raise ValueError("invalid visible index")
                eligible.append(g)
                ns.append(n)
                meta["warnings"].extend(g.warnings)
                if s.allow_extrapolation and any(not g.wavelength_range[0] <= line <= g.wavelength_range[1] for line in lines):
                    meta["warnings"].append(f"{g.uid}: visible dispersion extrapolation allowed outside documented range")
            except (ValueError, ArithmeticError) as exc:
                meta["glass_rejection_reasons"]["visible_dispersion_unavailable"] += 1
                meta["warnings"].append(f"{g.uid}: {exc}")
        if progress and (i % 32 == 0 or i+1 == len(pool)):
            progress(i+1, len(pool), "Checking visible glass eligibility")
    meta["warnings"] = sorted(set(meta["warnings"]))
    meta["eligible_glass_count"] = len(eligible)
    meta["rejected_glass_count"] = sum(meta["glass_rejection_reasons"].values())
    meta["unchecked_glass_count"] = len(pool)-len(eligible)-meta["rejected_glass_count"]
    meta["possible_candidate_count"] = len(eligible)**4
    if stopped or not eligible:
        return SearchResult([], finish_metadata(meta, []), stopped)
    candidates, count = _candidate_indices(len(eligible), s)
    meta["candidate_count"] = count
    meta["glass_tuple_coverage_fraction"] = count/meta["possible_candidate_count"]
    meta["all_glass_tuples"] = count == meta["possible_candidate_count"]
    ns = np.asarray(ns)
    shortlist, rows = [], []
    covered = [set() for _ in range(4)]
    for ids in candidates:
        if cancelled and cancelled():
            stopped = True
            break
        n = ns[list(ids)].T
        coarse = _coarse(n, s)
        meta["evaluated_count"] += 1
        for role, idx in enumerate(ids):
            covered[role].add(idx)
        if coarse is None:
            meta["rejected_count"] += 1
            meta["candidate_rejection_reasons"]["no_feasible_coarse_seed"] += 1
        else:
            meta["accepted_count"] += 1
            score, y = coarse
            rows = keep_best(rows, [_row(ids, y, n, eligible, s)], s.top_k)
            shortlist.append((score, ids, y))
            # bounded storage, deterministic ties; no numpy-array comparisons
            if len(shortlist) > max(2*s.refine_count, 128):
                shortlist = sorted(shortlist, key=lambda item: (item[0], item[1]))[:s.refine_count]
        if progress and (meta["evaluated_count"] % 32 == 0 or meta["evaluated_count"] == count):
            progress(meta["evaluated_count"], count, "Telescope coarse glass exploration")
    shortlist = sorted(shortlist, key=lambda item: (item[0], item[1]))[:s.refine_count]
    if not stopped:
        for _, ids, y in shortlist:
            if cancelled and cancelled():
                stopped = True
                break
            n = ns[list(ids)].T
            try:
                refined, converged = _refine(y, n, s, cancelled)
            except _Cancelled:
                stopped = True
                break
            meta["refined_count"] += 1
            meta["refinement_converged_count"] += int(converged)
            names = tuple(eligible[i].uid for i in ids)
            rows = [r for r in rows if r["glass_ids"] != names]
            rows = keep_best(rows, [_row(ids, refined, n, eligible, s, True)], s.top_k)
            if progress:
                progress(meta["refined_count"], len(shortlist), "Refining telescope shortlist")
    meta["evaluated_unique_glasses_by_role"] = [len(c) for c in covered]
    meta["refinement_note"] = "Rejected means no feasible tested coarse seed, not proof that a glass tuple cannot work. Refinement counts are additional continuous solves, not new tuples."
    # Non-dominated among returned candidates only, not an unsearched global front.
    for row in rows:
        row["pareto_in_returned"] = not any(
            (other["chromatic_bfl_rms"] <= row["chromatic_bfl_rms"] and abs(other["petzval"]) <= abs(row["petzval"]))
            and (other["chromatic_bfl_rms"] < row["chromatic_bfl_rms"] or abs(other["petzval"]) < abs(row["petzval"]))
            for other in rows)
    return SearchResult(rows, finish_metadata(meta, rows), stopped)
