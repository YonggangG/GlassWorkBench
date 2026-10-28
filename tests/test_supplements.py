"""Independent published checkpoints, not snapshots regenerated from our model."""
from dataclasses import replace
import warnings
import pytest
from glass_workbench.catalogs.supplemental import supplemental_glasses, _record_hash
from glass_workbench.contracts import Environment
from glass_workbench.optics.air import air_index, air_dn_dt, _water_fraction
from glass_workbench.optics.dispersion import refractive_index, catalog_index
from glass_workbench.optics.thermal import evaluate
from glass_workbench.optics.supplemental import (
    corning_7980_native, silicon_charms_native, source_absolute,
)

CORNING, SILICON = supplemental_glasses()


@pytest.mark.parametrize("w,n,dn", [
    (.184950, 1.575017, 22.7), (.365119, 1.474539, 11.2),
    (.435957, 1.466691, 10.6), (.486269, 1.463123, 10.4),
    (.587725, 1.458461, 10.1), (.656454, 1.456364, 9.9),
    (1.128950, 1.448866, 9.6),
])
def test_corning_independent_2014_7980_table(w, n, dn):
    # Complete Corning February 2014 brochure, HPFS 7980 section, not 7979.
    actual, derivative = corning_7980_native(w, 22)
    assert actual == pytest.approx(n, abs=1.1e-6, rel=0)
    assert derivative*1e6 == pytest.approx(dn, abs=.06, rel=0)


@pytest.mark.parametrize("w,kelvin,n", [
    (1.1, 295, 3.54394), (1.5, 295, 3.48314), (1.5, 100, 3.45609),
    (2, 200, 3.43863), (3, 250, 3.42572), (5.5, 30, 3.39449),
])
def test_silicon_independent_charms_table2(w, kelvin, n):
    # Frey/Leviton/Madison 2006 Table 2, absolute index, printed five places.
    assert silicon_charms_native(w, kelvin-273.15)[0] == pytest.approx(n, abs=1e-5, rel=0)


def test_silicon_table4_derivative_difference_is_disclosed():
    # Table 4's independently printed derivative does NOT equal the analytic
    # derivative of Table 5 everywhere. Do not silently tune signed constants.
    dn = silicon_charms_native(1.5, 295-273.15)[1]
    assert 8e-6 < abs(dn-1.87e-4) < 11e-6
    assert any("Table 4 differs" in w for w in SILICON.warnings)


@pytest.mark.parametrize("model,w,t", [
    (corning_7980_native, .587725, 22), (corning_7980_native, 1.55, 21),
    (silicon_charms_native, 1.1, 20), (silicon_charms_native, 1.55, 20),
    (silicon_charms_native, 5.5, -173.15),
])
def test_source_analytic_derivatives(model, w, t):
    h = .01
    fd = (model(w, t+h)[0]-model(w, t-h)[0])/(2*h)
    assert model(w, t)[1] == pytest.approx(fd, abs=2e-11, rel=0)


@pytest.mark.parametrize("glass", [CORNING, SILICON])
@pytest.mark.parametrize("env", [Environment(), Environment(90000, .6, 600)])
def test_source_absolute_then_ciddor_quotient(glass, env):
    w, t, h = 1.55, 22, .01
    a = evaluate(glass, w, t, env, True)
    default = evaluate(glass, w, t, allow_extrapolation=True)
    assert a.n_absolute == default.n_absolute
    assert a.dn_absolute == default.dn_absolute
    assert a.n_relative*a.n_air == pytest.approx(a.n_absolute, abs=1e-14)
    assert a.dn_relative*a.n_air+a.n_relative*a.dn_air == pytest.approx(a.dn_absolute, abs=1e-16)
    plus, minus = (evaluate(glass, w, temp, env, True) for temp in (t+h, t-h))
    assert a.dn_relative == pytest.approx((plus.n_relative-minus.n_relative)/(2*h), abs=3e-11)
    assert a.dn_absolute == pytest.approx((plus.n_absolute-minus.n_absolute)/(2*h), abs=3e-11)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        assert refractive_index(glass, w, True) == pytest.approx(
            evaluate(glass, w, glass.reference_temperature, allow_extrapolation=True).n_relative, abs=1e-14)
    assert not any("CDGM" in s for s in a.warnings)


@pytest.mark.parametrize("glass", [CORNING, SILICON])
def test_fixed_water_fraction_derivative(glass):
    env = Environment(90000, .6, 600, "water_mole_fraction")
    t, h, w = 22, .01, 1.55
    x = _water_fraction(t, env)
    ep = replace(env, relative_humidity=x/_water_fraction(t+h, replace(env, relative_humidity=1)))
    em = replace(env, relative_humidity=x/_water_fraction(t-h, replace(env, relative_humidity=1)))
    p, m = evaluate(glass,w,t+h,ep,True), evaluate(glass,w,t-h,em,True)
    assert evaluate(glass,w,t,env,True).dn_relative == pytest.approx((p.n_relative-m.n_relative)/(2*h), abs=3e-11)


def test_corning_reference_medium_product_rule():
    w,t = .587725,22
    nr,dnr = corning_7980_native(w,t)
    n,dn,_ = source_absolute(CORNING,w,t)
    na,dna = air_index(w,t),air_dn_dt(w,t)
    assert n == pytest.approx(nr*na, abs=1e-14)
    assert dn == pytest.approx(dnr*na+nr*dna, abs=1e-16)
    assert any("UNVERIFIED" in s for s in evaluate(CORNING,w,t).warnings)


def test_extrapolation_policy_and_hard_exclusions():
    for call in (lambda: evaluate(CORNING,1.55,20), lambda: refractive_index(CORNING,1.55),
                 lambda: evaluate(CORNING,.55,26), lambda: evaluate(SILICON,1.55,30)):
        with pytest.raises(ValueError, match="extrapolation"): call()
    assert any("extrapolation" in s for s in evaluate(CORNING,1.55,20,allow_extrapolation=True).warnings)
    for allow in (False, True):
        with pytest.raises(ValueError, match="excluded"):
            evaluate(SILICON,.587725,20,allow_extrapolation=allow)
        with pytest.raises(ValueError, match="excluded"):
            refractive_index(SILICON,.587725,allow)
    # Full source cryogenic/IR domain is accessible natively, but air is narrower.
    assert source_absolute(SILICON,5.5,-243.15)[0] > 3
    with pytest.raises(ValueError, match="Ciddor"):
        evaluate(SILICON,2,20)
    with pytest.raises(ValueError, match="Ciddor"):
        refractive_index(SILICON,2)
    for g in (CORNING,SILICON):
        with pytest.raises(ValueError, match="vacuum"):
            catalog_index(g,.55)


def test_unknown_models_never_fall_back_to_catalog_equation():
    bad = replace(CORNING,dispersion_model="typo",thermal_model="typo",thermal=(0,0,0,0,0,.1))
    for call in (lambda: evaluate(bad,.55,22,allow_extrapolation=True),
                 lambda: refractive_index(bad,.55,True), lambda: source_absolute(bad,.55,22,True),
                 lambda: evaluate(replace(CORNING,thermal_model="silicon_charms"),.55,22)):
        with pytest.raises(ValueError,match="[Uu]nsupported|inconsistent"): call()


def test_factory_identity_source_values_missing_fields_and_hashes():
    fresh = supplemental_glasses()
    assert fresh is not supplemental_glasses()
    assert [g.uid for g in fresh] == ["Corning:HPFS 7980","Infrared:Silicon"]
    assert CORNING.vd == pytest.approx((1.458461-1)/(1.463123-1.456364))
    assert CORNING.pgf == pytest.approx((1.466691-1.463123)/(1.463123-1.456364))
    assert (SILICON.nd,SILICON.vd,SILICON.pgf) == (None,None,None)
    assert not SILICON.visible_applicable
    for a,b in zip(fresh,supplemental_glasses()):
        assert a.price is None and a.transmission == ()
        assert len(a.source_hash)==64 and int(a.source_hash,16)>0
        assert a.source_hash==b.source_hash
        assert _record_hash(replace(a,cte=a.cte*2)) != a.source_hash
    assert fresh[0].source_hash != fresh[1].source_hash
