from dataclasses import replace
from math import sqrt
from pathlib import Path
import pytest
from glass_workbench.contracts import Glass, Environment
from glass_workbench.optics.air import air_index, air_dn_dt, _water_fraction
from glass_workbench.optics.dispersion import refractive_index, catalog_index, air_to_vacuum, SPECTRAL_LINES_VACUUM
from glass_workbench.optics.thermal import evaluate
from glass_workbench.optics.transmission import transmission_at
from glass_workbench.catalogs.loader import load_catalog, discover_catalogs

BK7 = Glass("SCHOTT","fixture","",1.5168,64.17,
    dispersion=(1.03961212,.231792344,1.01046945,.00600069867,.0200179144,103.560653),
    thermal=(1.86e-6,1.31e-8,-1.37e-11,4.34e-7,6.27e-10,.17),cte=7.1e-6,
    wavelength_range=(.3,2.4))

# Independent NIST Engineering Metrology Toolbox Documentation, section VII,
# Table1, https://emtoolbox.nist.gov/wavelength/Documentation.asp. NIST uses
# IAPWS saturation rather than Ciddor/Davis; allow 2e-9 including table rounding.
@pytest.mark.parametrize("t,rh,p,w,n",[
 (20,0,101325,.633,1.000271800),(20,0,60000,.633,1.000160924),
 (20,0,120000,.633,1.000321916),(50,0,100000,.633,1.000243285),
 (5,0,100000,.633,1.000282756),(-40,0,100000,.633,1.000337580),
 (50,1,120000,.633,1.000287924),(40,.75,120000,.633,1.000299418),
 (20,1,100000,.633,1.000267394),(40,1,110000,1.7,1.000270247),
 (20,0,101325,1.7,1.000268479),(40,1,110000,.3,1.000289000),
 (20,0,101325,.3,1.000286581),(-40,0,120000,.3,1.000427233)])
def test_ciddor_published_nist_table(t,rh,p,w,n):
    assert air_index(w,t,Environment(p,rh)) == pytest.approx(n,abs=2e-9,rel=0)


def test_air_derivatives_hold_conditions_and_convergence():
    env = Environment(relative_humidity=.7)
    fixed = replace(env,hold="water_mole_fraction")
    assert air_index(.633,30,env) == air_index(.633,30,fixed)
    assert abs(air_dn_dt(.633,30,env)-air_dn_dt(.633,30,fixed)) > 1e-8
    for h in [.1,.01,.001]:
        fd = (air_index(.633,30+h,env)-air_index(.633,30-h,env))/(2*h)
        assert air_dn_dt(.633,30,env) == pytest.approx(fd,abs=2e-12)
    # Keep x_water constant by changing RH for the finite difference.
    x = _water_fraction(30,env);h=.01
    ep = replace(fixed,relative_humidity=x/_water_fraction(30+h,replace(env,relative_humidity=1)))
    em = replace(fixed,relative_humidity=x/_water_fraction(30-h,replace(env,relative_humidity=1)))
    fd = (air_index(.633,30+h,ep)-air_index(.633,30-h,em))/(2*h)
    assert air_dn_dt(.633,30,fixed) == pytest.approx(fd,abs=2e-12)


@pytest.mark.parametrize("w,t,env",[(.2,20,Environment()),(.5,-100,Environment()),
 (.5,20,Environment(relative_humidity=50)),(.5,20,Environment(pressure_pa=-1)),
 (.5,100,Environment(pressure_pa=10000,relative_humidity=1)),
 (.5,20,Environment(hold="unknown")),(float("nan"),20,Environment())])
def test_invalid_air(w,t,env):
    with pytest.raises(ValueError): air_index(w,t,env)


def test_reference_and_quotient_derivative():
    w = SPECTRAL_LINES_VACUUM["d"]
    a = evaluate(BK7,w,20)
    assert a.n_relative == pytest.approx(refractive_index(BK7,w),abs=1e-14)
    humid = evaluate(BK7,w,20,Environment(90000,.6,600))
    assert humid.n_absolute == a.n_absolute
    for t in [0,20,50]:
        for env in [Environment(),Environment(90000,.6,600)]:
            if t == 0 and env.relative_humidity: continue  # ice/water boundary derivative is one-sided
            a = evaluate(BK7,w,t,env);h=.02
            plus,minus = evaluate(BK7,w,t+h,env),evaluate(BK7,w,t-h,env)
            assert a.n_relative*a.n_air == pytest.approx(a.n_absolute,abs=1e-14)
            assert a.dn_relative*a.n_air+a.n_relative*a.dn_air == pytest.approx(a.dn_absolute,abs=1e-16)
            assert a.dn_relative == pytest.approx((plus.n_relative-minus.n_relative)/(2*h),abs=2e-12)
            assert a.dn_absolute == pytest.approx((plus.n_absolute-minus.n_absolute)/(2*h),abs=2e-12)


def test_thermal_interval_not_point_and_range():
    # N-BK7 official workbook / TIE19 table 20..40C e-line relative 3.0ppm/K;
    # workbook absolute1.6ppm/K. This is independent tabulated evidence.
    w = SPECTRAL_LINES_VACUUM["e"]
    a,b=evaluate(BK7,w,20),evaluate(BK7,w,40)
    assert (b.n_relative-a.n_relative)/20*1e6 == pytest.approx(3.0,abs=.07)
    assert (b.n_absolute-a.n_absolute)/20*1e6 == pytest.approx(1.6,abs=.07)
    assert abs((b.n_relative-a.n_relative)/20-a.dn_relative) > 1e-8
    with pytest.raises(ValueError,match="thermal extrapolation"):
        evaluate(BK7,1.55,20)
    assert any("thermal extrapolation" in w for w in evaluate(BK7,1.55,20,allow_extrapolation=True).warnings)
    with pytest.raises(ValueError,match="unavailable"):
        evaluate(replace(BK7,thermal=None),.55,20)


def test_dispersion_and_transmission_failures():
    p = replace(BK7,supplier="CDGM",dispersion_model="polynomial",dispersion=(2.25,0,.01,0,0,0),wavelength_range=(.4,1.014))
    assert catalog_index(p,.5) == pytest.approx(sqrt(2.29))
    with pytest.raises(ValueError,match="extrapolation"): refractive_index(p,1.55)
    with pytest.warns(RuntimeWarning): assert refractive_index(p,1.55,True)>1
    with pytest.raises(ValueError): refractive_index(replace(BK7,dispersion=()),.55)
    g=replace(BK7,transmission=((1.4,.81),(1.6,1)))
    assert transmission_at(g,1.5) == pytest.approx(.9)
    assert transmission_at(g,1.4) == .81
    assert transmission_at(g,2) is None
    assert transmission_at(replace(g,transmission=((1.4,0),(1.6,1))),1.5) is None
    assert transmission_at(replace(g,transmission=()),1.5) is None


def test_independent_source_thermal_tables_and_conflict_guard():
    paths = discover_catalogs(Path(__file__).resolve().parents[1])
    if len(paths)!=2: pytest.skip("External licensed source workbooks absent")
    from openpyxl import load_workbook
    from openpyxl.utils.cell import column_index_from_string as col
    catalogs={c.supplier:c for c in map(load_catalog,paths)}
    for supplier in catalogs:
        cat=catalogs[supplier]
        wb=load_workbook(cat.path,read_only=True,data_only=True)
        rows=list(wb.worksheets[0].values);wb.close()
        if supplier=="SCHOTT":
            # Independent cells are interval means, NOT derivatives at20C.
            for g in cat.glasses:
                for wave,rc,ac in [(.546074,"Z","AC"),(.4358343,"AA","AD"),(1.06,"Y","AB")]:
                    if not any(isinstance(rows[g.source_row-1][col(c)-1],(int,float)) for c in (rc,ac)):
                        continue
                    a,b=evaluate(g,air_to_vacuum(wave),20,allow_extrapolation=True),evaluate(g,air_to_vacuum(wave),40,allow_extrapolation=True)
                    for attr,column in [("n_relative",rc),("n_absolute",ac)]:
                        target=rows[g.source_row-1][col(column)-1]
                        if not isinstance(target,(int,float)):
                            continue  # blanks are missing data, never zero
                        # Rounded table and fitted coefficients are not exact: P-SK60
                        # absolute e-line residual is0.0897ppm/K (documented, not tuned).
                        tolerance = .1 if attr == "n_absolute" else .08
                        assert (getattr(b,attr)-getattr(a,attr))/20*1e6 == pytest.approx(target,abs=tolerance)
        else:
            g=next(g for g in cat.glasses if g.name=="H-K9L")
            a,b=evaluate(g,air_to_vacuum(.54607),20),evaluate(g,air_to_vacuum(.54607),40)
            assert (b.n_relative-a.n_relative)/20*1e6 == pytest.approx(1.7,abs=.06)
            bad=next(g for g in cat.glasses if g.name=="F13")
            with pytest.raises(ValueError,match="THERMAL_TABLE_MISMATCH"):evaluate(bad,.55,20)
            assert any("THERMAL_TABLE_MISMATCH" in w for w in evaluate(bad,.55,20,allow_extrapolation=True).warnings)
