"""Supplement policies tested independently of production material factories."""
from dataclasses import fields, replace
import json

import numpy as np
import pytest

from glass_workbench.contracts import Glass, ThermalResult
from glass_workbench.screening import telescope, triplet


@pytest.fixture
def synthetic_pool(monkeypatch):
    # Deliberately omit nd/vd: triplet screening must use the evaluated index.
    pool = [Glass("SYNTH", name, name, None, None, cte=0.,
                  transmission=((1.55, tau),), supplemental=True,
                  source_file="synthetic-source", source_sheet="materials", source_row=i + 1,
                  source_hash="synthetic-hash", source_urls=(f"https://example.invalid/{name}",),
                  thermal_model="synthetic", warnings=("synthetic material",))
            for i, (name, tau) in enumerate((("a", .98), ("b", .99), ("c", .995)))]
    optics = {"a": (1.8, 1e-6), "b": (1.5, 8e-6), "c": (1.9, 3.536842105263158e-6)}

    def evaluate(g, *args, **kwargs):
        n, psi = optics[g.name]
        dn = psi * (n - 1)
        return ThermalResult(n, n, dn, dn, 1., 0., ("synthetic thermal",))

    monkeypatch.setattr(triplet.thermal, "evaluate", evaluate)
    return pool


def test_unknown_setting_is_appended_and_defaults_to_false():
    assert fields(triplet.TripletSettings)[-1].name == "allow_unknown_transmission"
    assert triplet.TripletSettings().allow_unknown_transmission is False


@pytest.mark.parametrize("threshold", [0., .97, 1.])
def test_default_rejects_unknown_even_at_zero(synthetic_pool, threshold):
    g = replace(synthetic_pool[0], transmission=())
    result = triplet.search_triplets([g], triplet.TripletSettings(min_transmission=threshold))
    assert result.rows == []
    assert result.metadata["glass_rejection_reasons"] == {"missing_transmission": 1}
    assert result.metadata["eligible_glass_count"] == 0
    assert "threshold zero" in result.metadata["transmission_policy"]


@pytest.mark.parametrize("missing", [(0,), (0, 1, 2)])
@pytest.mark.parametrize("batch_size", [1, 100])
def test_opt_in_keeps_unknown_as_none_and_known_min_separate(synthetic_pool, missing, batch_size):
    pool = [replace(g, transmission=()) if i in missing else g for i, g in enumerate(synthetic_pool)]
    settings = triplet.TripletSettings(allow_unknown_transmission=True, batch_size=batch_size)
    result = triplet.search_triplets(pool, settings)
    assert len(result.rows) == 1
    row = result.rows[0]
    unknown = tuple(pool[i].uid for i in missing)
    known = [g.transmission[0][1] for g in pool if g.transmission]
    assert row["transmission_min"] is None
    assert row["transmission_known_min"] == (min(known) if known else None)
    assert row["unknown_transmission_glasses"] == unknown
    assert row["transmission_values"] == tuple(g.transmission[0][1] if g.transmission else None for g in pool)
    assert row["transmission_complete"] is False
    assert row["transmission_estimated"] is bool(known)
    np.testing.assert_allclose(row["powers"], [3., -4.375, 2.375], atol=1e-10)
    assert all(any(uid in w and "unverified" in w for w in row["warnings"]) for uid in unknown)
    meta = result.metadata
    assert meta["eligible_glass_count"] == 3
    assert meta["candidate_count"] == meta["evaluated_count"] == 10
    assert meta["accepted_count"] == 1
    assert meta["rejected_count"] == 9
    assert meta["candidate_rejection_reasons"] == {"repeated_glass_singular": 9}
    assert meta["unknown_transmission_glasses"] == unknown
    assert meta["eligible_unknown_transmission_count"] == len(missing)
    assert "NOT verified" in meta["transmission_policy"]
    assert any("opt-in enabled" in warning for warning in meta["warnings"])
    # In particular, neither rows nor metadata leak the internal NaN mask.
    json.dumps({"rows": result.rows, "metadata": meta}, allow_nan=False)


@pytest.mark.parametrize("allow_unknown", [False, True])
def test_known_below_threshold_still_rejected(synthetic_pool, allow_unknown):
    low = replace(synthetic_pool[0], transmission=((1.55, .96),))
    result = triplet.search_triplets([low], triplet.TripletSettings(allow_unknown_transmission=allow_unknown))
    assert not result.rows
    assert result.metadata["glass_rejection_reasons"] == {"transmission_below_threshold": 1}


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -.01, 1.01])
def test_opt_in_never_accepts_invalid_transmission(synthetic_pool, monkeypatch, invalid):
    monkeypatch.setattr(triplet.transmission, "transmission_at", lambda *args: invalid)
    result = triplet.search_triplets(synthetic_pool, triplet.TripletSettings(allow_unknown_transmission=True))
    assert result.metadata["eligible_glass_count"] == 0
    assert result.metadata["glass_rejection_reasons"] == {"invalid_transmission": 3}


def test_known_transmission_and_provenance_preserved(synthetic_pool):
    result = triplet.search_triplets(synthetic_pool)
    row = result.rows[0]
    assert row["transmission_min"] == row["transmission_known_min"] == .98
    assert row["transmission_complete"] is True
    assert row["unknown_transmission_glasses"] == ()
    assert row["supplemental_glasses"] == tuple(g.uid for g in synthetic_pool)
    assert row["source_urls"] == tuple(g.source_urls[0] for g in synthetic_pool)
    assert result.metadata["eligible_unknown_transmission_count"] == 0
    source = result.metadata["source_records"][0]
    assert source["glass_id"] == synthetic_pool[0].uid
    assert source["supplemental"] is True
    assert source["source_urls"] == synthetic_pool[0].source_urls
    assert source["source_row"] == 1 and source["source_hash"] == "synthetic-hash"
    assert source["thermal_model"] == "synthetic"
    assert result.metadata["sources"][0]["file"] == "synthetic-source"


def test_unbracketed_transmission_is_unknown_not_extrapolated(synthetic_pool):
    pool = [replace(g, transmission=((.5, .99),)) for g in synthetic_pool]
    result = triplet.search_triplets(pool, triplet.TripletSettings(allow_unknown_transmission=True))
    row = result.rows[0]
    assert row["transmission_min"] is row["transmission_known_min"] is None
    assert row["transmission_values"] == (None, None, None)
    assert row["transmission_source_wavelengths_um"] == ((), (), ())


@pytest.mark.parametrize("allow_extrapolation", [False, True])
def test_visible_material_guard_precedes_dispersion(synthetic_pool, monkeypatch, allow_extrapolation):
    blocked = replace(synthetic_pool[0], visible_applicable=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Visible-inapplicable material must never reach dispersion evaluation")

    monkeypatch.setattr(telescope.dispersion, "refractive_index", forbidden)
    result = telescope.search_telescope([blocked], telescope.TelescopeSettings(allow_extrapolation=allow_extrapolation))
    assert result.rows == []
    assert result.metadata["glass_rejection_reasons"] == {"visible_material_inapplicable": 1}
    assert result.metadata["eligible_glass_count"] == 0
    assert result.metadata["rejected_glass_count"] == 1
    assert result.metadata["unchecked_glass_count"] == 0
    assert "always rejected" in result.metadata["visible_material_policy"]
    assert any("cannot override" in warning for warning in result.metadata["warnings"])


def test_visible_supplement_still_eligible_and_counts_include_guard(synthetic_pool, monkeypatch):
    allowed = synthetic_pool[0]
    blocked = replace(synthetic_pool[1], visible_applicable=False)
    calls = []

    def index(g, line, **kwargs):
        calls.append(g.uid)
        return 1.6

    monkeypatch.setattr(telescope.dispersion, "refractive_index", index)
    result = telescope.search_telescope([allowed, blocked], telescope.TelescopeSettings(
        allow_extrapolation=True, exhaustive=True, refine_count=0))
    assert calls == [allowed.uid] * 3
    assert result.metadata["eligible_glass_count"] == result.metadata["rejected_glass_count"] == 1
    assert result.metadata["candidate_count"] == result.metadata["evaluated_count"] == 1
    assert result.metadata["glass_rejection_reasons"] == {"visible_material_inapplicable": 1}
    assert len(result.rows) == 1
    assert result.rows[0]["supplemental_glasses"] == (allowed.uid,) * 4
    assert result.rows[0]["source_urls"] == allowed.source_urls
    assert result.metadata["source_records"][1]["visible_applicable"] is False
