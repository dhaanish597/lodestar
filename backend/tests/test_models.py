# backend/tests/test_models.py
from datetime import datetime, timezone

from app.models import RerouteOption, RiskScore, Scenario, Vessel


def test_vessel_requires_core_ais_fields():
    v = Vessel(
        mmsi=205344990,
        lat=26.5,
        lon=56.3,
        sog=12.4,
        cog=88.0,
        true_heading=90,
        nav_status=0,
        timestamp=datetime.now(timezone.utc),
    )
    assert v.signal_lost is False
    assert v.extrapolated is False


def test_risk_score_carries_full_feature_breakdown():
    r = RiskScore(
        corridor="hormuz",
        timestamp=datetime.now(timezone.utc),
        probability=0.5,
        beta0=-3.0,
        weights={"kinetic": 0.40, "density": 0.25, "sanctions": 0.15, "weather": 0.10, "freight": 0.10},
        features={"kinetic": 0.8, "density": 0.0, "sanctions": 0.0, "weather": 0.0, "freight": 0.0},
        contributions={"kinetic": 0.32, "density": 0.0, "sanctions": 0.0, "weather": 0.0, "freight": 0.0},
    )
    assert set(r.contributions) == set(r.weights)


def test_scenario_and_reroute_contracts_instantiate():
    s = Scenario(
        corridor="hormuz",
        disruption_factor=0.30,
        substitution_rate=0.20,
        hormuz_share=0.45,
        india_imports_mbd=4.7,
        supply_gap_mbd=0.5,
        utilization_drop_pct=0.06,
        spr_fill_pct=0.64,
        days_cover_remaining=9.5,
        cpi_sensitivity=0.35,
        cpi_delta_pp=0.2,
        gdp_drag_bps=8.0,
        cad_sensitivity=0.35,
        cad_widening_pct_gdp=0.15,
        crude_price_rise_pct=30.0,
        price_sensitivity=1.0,
        brent_baseline_usd_bbl=75.0,
    )
    r = RerouteOption(
        source_grade="Urals",
        origin="Russia",
        api_gravity=31.0,
        sulfur_pct=1.3,
        landed_cost_usd_bbl=78.5,
        voyage_days=25.0,
        grade_match=1.0,
        congestion_penalty=0.1,
        score=0.81,
        best_fit_refineries=["RIL Jamnagar", "Nayara Vadinar"],
    )
    assert s.corridor == "hormuz"
    assert r.grade_match == 1.0
