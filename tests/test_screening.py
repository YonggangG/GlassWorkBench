"""Independent small-pool numerical oracles; no proprietary files required."""
from dataclasses import replace
from itertools import combinations_with_replacement, product
import math

import numpy as np
import pytest

from glass_workbench.contracts import Glass, ThermalResult
from glass_workbench.screening import triplet, telescope
from glass_workbench.screening.triplet import TripletSettings, search_triplets
from glass_workbench.screening.telescope import (TelescopeSettings, search_telescope,
    optical_metrics, shared_curvatures, system_matrix)


def make_glass(name, n=1.6, v=60):
    return Glass("TEST", name, name, n, v, cte=0., transmission=((.4, .995), (2., .99)))


@pytest.fixture
def triplet_pool(monkeypatch):
    pool = [make_glass("a", 1.8), make_glass("b", 1.5), make_glass("c", 1.9), make_glass("d", 1.7)]
    psis = dict(a=1e-6, b=8e-6, c=3.536842105263158e-6, d=-2e-6)
    def evaluate(g, *args, **kwargs):
        dn = psis[g.name]*(g.nd-1)
        return ThermalResult(g.nd, g.nd, dn, dn, 1., 0., ("synthetic warning",))
    monkeypatch.setattr(triplet.thermal, "evaluate", evaluate)
    monkeypatch.setattr(triplet.transmission, "transmission_at", lambda *args: .99)
    return pool, psis


@pytest.fixture
def visible_pool(monkeypatch):
    pool = [make_glass("a", 1.52, 64), make_glass("b", 1.67, 32), make_glass("c", 1.75, 50)]
    lines = telescope.dispersion.SPECTRAL_LINES_VACUUM
    def index(g, line, **kwargs):
        delta = (g.nd-1)/g.vd
        return g.nd + {lines["C"]: -.4, lines["d"]: 0., lines["F"]: .6}[line]*delta
    monkeypatch.setattr(telescope.dispersion, "refractive_index", index)
    return pool


def test_defaults_and_validation():
    s = TripletSettings()
    assert (s.wavelength_um, s.temperature_c, s.efl_mm, s.housing_cte_ppm) == (1.55, 20, 90, 23.6)
    assert TelescopeSettings().candidate_limit == 3000
    for settings in (replace(s, max_power=0), replace(s, batch_size=0), replace(s, sign_pattern="- + -"), replace(s, min_transmission=2)):
        with pytest.raises(ValueError):
            search_triplets([], settings)
    for settings in (TelescopeSettings(gap_ratio=-1), TelescopeSettings(chromatic_weight=0, petzval_weight=0), TelescopeSettings(seed=-1)):
        with pytest.raises(ValueError):
            search_telescope([], settings)


@pytest.mark.parametrize("housing_cte_ppm", [23.6, 0., -8.25, 12.34])
def test_triplet_matches_independent_exhaustive_oracle(triplet_pool, housing_cte_ppm):
    pool, psi = triplet_pool
    settings = TripletSettings(sign_pattern="unrestricted", top_k=100, max_power=100, batch_size=3,
                               housing_cte_ppm=housing_cte_ppm)
    result = search_triplets(pool, settings)
    oracle = []
    for glasses in combinations_with_replacement(pool, 3):
        if len({g.uid for g in glasses}) < 3:
            continue
        a = np.array([[1., 1., 1.], [psi[g.name]*1e6 for g in glasses], [1/g.nd for g in glasses]])
        y = np.linalg.solve(a, [1, -housing_cte_ppm, 0])
        if np.max(np.abs(y)) <= settings.max_power:
            oracle.append((float(np.sqrt(np.mean(y*y))), tuple(g.uid for g in glasses), y))
    oracle.sort(key=lambda t: (t[0], t[1]))
    assert len(result.rows) == len(oracle)
    for row, expected in zip(result.rows, oracle):
        assert row["glass_ids"] == expected[1]
        np.testing.assert_allclose(row["powers"], expected[2], rtol=1e-12, atol=1e-12)
        assert abs(row["thermal_residual_per_k"]) < 1e-16
        assert abs(row["petzval_residual"]) < 1e-12
        by_uid = {g.uid: psi[g.name] for g in pool}
        actual_thermal_sum = sum(y * by_uid[uid] for y, uid in zip(row["powers"], row["glass_ids"]))
        assert actual_thermal_sum == pytest.approx(-housing_cte_ppm * 1e-6, abs=1e-16)
    m = result.metadata
    assert m["settings"]["housing_cte_ppm"] == housing_cte_ppm
    assert m["candidate_count"] == m["evaluated_count"] == 20
    assert m["rejected_count"]+m["accepted_count"] == 20
    assert m["candidate_rejection_reasons"]["repeated_glass_singular"] == 16
    assert "synthetic warning" in m["warnings"]


def test_cooke_reordering_separate_unrestricted(triplet_pool):
    pool, _ = triplet_pool
    result = search_triplets(pool[:3], TripletSettings())
    assert len(result.rows) == 1
    y = result.rows[0]["powers"]
    np.testing.assert_allclose(y, [3., -4.375, 2.375], atol=1e-10)
    assert y[0] > 0 and y[1] < 0 and y[2] > 0
    # Change UID order; geometry reorders negatives to the middle, not tuple order.
    changed = [replace(pool[0], supplier="Z"), pool[1], pool[2]]
    assert search_triplets(changed, TripletSettings()).rows[0]["powers"][1] < 0
    unrestricted = search_triplets(changed, TripletSettings(sign_pattern="unrestricted"))
    assert unrestricted.rows[0]["powers"][0] < 0


def test_triplet_bounds_duplicates_singular_and_rejection(triplet_pool, monkeypatch):
    pool, _ = triplet_pool
    bounded = search_triplets(pool[:3], TripletSettings(max_power=1))
    assert bounded.rows == []
    assert bounded.metadata["candidate_rejection_reasons"]["power_bound"] == 1
    duplicates = search_triplets([pool[0], pool[0]], TripletSettings())
    assert duplicates.metadata["duplicate_input_count"] == 1
    assert duplicates.metadata["candidate_count"] == 1
    with pytest.raises(ValueError, match="Conflicting"):
        search_triplets([pool[0], replace(pool[0], nd=2)], TripletSettings())
    singular_pool = [replace(g, nd=1.6) for g in pool[:3]]
    singular = search_triplets(singular_pool, TripletSettings())
    assert not singular.rows
    assert singular.metadata["candidate_rejection_reasons"]["ill_conditioned_or_singular"] == 1
    monkeypatch.setattr(triplet.transmission, "transmission_at", lambda g, w: None if g.name == "a" else .5)
    rejected = search_triplets(pool, TripletSettings())
    assert rejected.metadata["eligible_glass_count"] == 0
    assert rejected.metadata["rejected_glass_count"] == 4


def test_triplet_batches_and_input_order_are_deterministic(triplet_pool):
    pool, _ = triplet_pool
    a = search_triplets(pool, TripletSettings(batch_size=1, sign_pattern="unrestricted"))
    b = search_triplets(pool[::-1], TripletSettings(batch_size=100, sign_pattern="unrestricted"))
    assert [r["glass_ids"] for r in a.rows] == [r["glass_ids"] for r in b.rows]
    np.testing.assert_allclose([r["powers"] for r in a.rows], [r["powers"] for r in b.rows])


def test_early_and_partial_cancellation(triplet_pool, visible_pool):
    pool, _ = triplet_pool
    for search, settings in ((search_triplets, TripletSettings()), (search_telescope, TelescopeSettings())):
        result = search(pool, settings, cancelled=lambda: True)
        assert result.cancelled and result.metadata["evaluated_count"] == 0
    stop = [False]
    def progress(done, total, stage):
        if stage == "Solving triplet combinations":
            stop[0] = True
    result = search_triplets(pool, TripletSettings(batch_size=2), progress, lambda: stop[0])
    assert result.cancelled
    assert result.metadata["evaluated_count"] == 2
    assert result.metadata["unevaluated_count"] == 18
    stop[0] = False
    def tprogress(done, total, stage):
        if "coarse" in stage:
            stop[0] = True
    result = search_telescope(visible_pool, TelescopeSettings(exhaustive=True), tprogress, lambda: stop[0])
    assert result.cancelled and result.metadata["evaluated_count"] == 32


def test_abcd_and_shared_interfaces_independent_oracle():
    y = np.array([1.8, -1.1, .6, -.2])
    n = np.array([[1.51, 1.65, 1.7, 1.55], [1.52, 1.67, 1.72, 1.56], [1.53, 1.70, 1.74, 1.57]])
    gap = .17
    m = optical_metrics(y, n, gap)
    c = shared_curvatures(y, n[1])
    assert abs(c[:4].sum()) < 1e-14
    for j in range(3):
        p = (n[j]-1)*np.r_[c[0]-c[1], c[1]-c[2], c[2]-c[3], c[4]-c[5]]
        lens_g = np.array([[1., 0.], [-sum(p[:3]), 1.]])
        space = np.array([[1., gap], [0., 1.]])
        lens_s = np.array([[1., 0.], [-p[3], 1.]])
        matrix = lens_s @ space @ lens_g
        np.testing.assert_allclose(matrix, system_matrix(sum(p[:3]), p[3], gap))
        assert np.linalg.det(matrix) == pytest.approx(1.)
        assert m["bfl"][j] == pytest.approx(-matrix[0, 0]/matrix[1, 0])
        assert m["efl"][j] == pytest.approx(-1/matrix[1, 0])
        before = np.r_[1, n[j, :3], 1, n[j, 3]]
        after = np.r_[n[j, :3], 1, n[j, 3], 1]
        surface_petzval = np.sum((after-before)/(before*after)*c)
        assert m["petzval"][j] == pytest.approx(surface_petzval, abs=1e-14)
    contact = optical_metrics(y, n, 0)
    np.testing.assert_allclose(contact["efl"], contact["bfl"])
    np.testing.assert_allclose(contact["total_power"], ((n-1)/(n[1]-1)) @ y)


def test_exhaustive_small_pool_oracle_repetitions_and_target(visible_pool):
    pool = visible_pool[:2]
    settings = TelescopeSettings(exhaustive=True, refine_count=0, top_k=20, positive_objective=False)
    result = search_telescope(pool, settings)
    assert result.metadata["candidate_count"] == result.metadata["evaluated_count"] == 16
    assert result.metadata["all_glass_tuples"]
    # Independent enumeration of ordered tuples includes 2^4-2 distinct-only cases.
    expected = {tuple(g.uid for g in choice) for choice in product(pool, repeat=4)}
    assert {r["glass_ids"] for r in result.rows} == expected
    for row in result.rows:
        y = np.asarray(row["powers"])
        g, singlet = sum(y[:3]), y[3]
        assert g+singlet-settings.gap_ratio*g*singlet == pytest.approx(1, abs=1e-12)
        assert row["efl_d_mm"] == pytest.approx(500., abs=1e-8)
        assert row["power_max"] <= settings.max_power+1e-8
        assert row["curvature_max_per_mm"] <= settings.max_curvature_per_mm+1e-8
        assert row["shared_interface_residual"] < 1e-12
        assert row["bfl_spread_mm"] == pytest.approx(max(row[f"bfl_{line}_mm"] for line in ("c", "d", "f"))-min(row[f"bfl_{line}_mm"] for line in ("c", "d", "f")))
    assert any(len(set(r["glass_ids"])) == 1 for r in result.rows)


def test_bounded_search_deterministic_diverse_no_silent_truncation(visible_pool):
    settings = TelescopeSettings(candidate_limit=20, refine_count=2, seed=31)
    a = search_telescope(visible_pool, settings)
    b = search_telescope(visible_pool[::-1], settings)
    assert a.rows == b.rows
    assert a.metadata["evaluated_count"] == 20
    assert a.metadata["possible_candidate_count"] == 81
    assert a.metadata["evaluated_unique_glasses_by_role"] == [3, 3, 3, 3]
    assert a.metadata["refined_count"] == 2
    assert all(abs(r["efl_error"]) < 1e-8 for r in a.rows)
    with pytest.raises(ValueError, match="explicit limit"):
        search_telescope(visible_pool, replace(settings, exhaustive=True, exhaustive_limit=10))


def test_refinement_never_worsens_best_and_empty(visible_pool):
    coarse = search_telescope(visible_pool, TelescopeSettings(candidate_limit=15, refine_count=0))
    refined = search_telescope(visible_pool, TelescopeSettings(candidate_limit=15, refine_count=5))
    assert refined.rows[0]["score"] <= coarse.rows[0]["score"]+1e-14
    assert search_telescope([], TelescopeSettings()).rows == []
    assert search_triplets([], TripletSettings()).rows == []


def test_positive_objective_default_and_opt_out(visible_pool):
    assert TelescopeSettings().positive_objective
    result = search_telescope(visible_pool, TelescopeSettings(candidate_limit=30, refine_count=4))
    assert result.rows
    for row in result.rows:
        assert row["group_power"] > 1e-7
        assert row["group_power"] == pytest.approx(sum(row["powers"][:3]))
        assert row["singlet_power"] == row["powers"][3]
    n = np.array([[1.51, 1.65, 1.7, 1.55], [1.52, 1.67, 1.72, 1.56], [1.53, 1.70, 1.74, 1.57]])
    y = telescope._powers((-1., -.3, -.3), .1)
    assert not telescope._feasible(y, n, TelescopeSettings())
    assert telescope._feasible(y, n, TelescopeSettings(positive_objective=False))


def test_positive_real_bfl_at_large_gap(visible_pool):
    result = search_telescope(visible_pool, TelescopeSettings(gap_ratio=2., candidate_limit=20, refine_count=3))
    assert result.rows
    assert all(min(row["bfl_c_mm"], row["bfl_d_mm"], row["bfl_f_mm"]) > 0 for row in result.rows)


def test_no_thermal_constraint_in_telescope(visible_pool, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Telescope must not call thermal calculations")
    monkeypatch.setattr(triplet.thermal, "evaluate", forbidden)
    pool = [replace(g, thermal=None, cte=None, transmission=()) for g in visible_pool]
    result = search_telescope(pool, TelescopeSettings(candidate_limit=10, refine_count=0))
    assert result.metadata["eligible_glass_count"] == 3
    assert result.rows
