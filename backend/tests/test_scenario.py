import pytest

from app.engine.scenario import (
    GDP_DRAG_BPS_PER_10PCT,
    OMC_COMMERCIAL_DAYS,
    SPR_DEDICATED_DAYS_AT_FULL_FILL,
    compute_scenario,
    crude_price_rise_pct,
)


def test_zero_disruption_gives_zero_gap_and_full_buffer_days():
    s = compute_scenario(corridor="hormuz", disruption_factor=0.0)
    assert s.supply_gap_mbd == 0.0
    assert s.utilization_drop_pct == 0.0
    assert s.crude_price_rise_pct == 0.0
    assert s.cpi_delta_pp == 0.0
    assert s.gdp_drag_bps == 0.0
    assert s.cad_widening_pct_gdp == 0.0
    expected_buffer_days = SPR_DEDICATED_DAYS_AT_FULL_FILL * 0.64 + OMC_COMMERCIAL_DAYS
    assert s.days_cover_remaining == pytest.approx(expected_buffer_days)


def test_supply_gap_formula():
    s = compute_scenario(
        corridor="hormuz",
        disruption_factor=0.5,
        substitution_rate=0.25,
        hormuz_share=0.40,
        india_imports_mbd=5.0,
    )
    expected = (5.0 * 0.40) * 0.5 * (1 - 0.25)
    assert s.supply_gap_mbd == pytest.approx(expected)


def test_higher_disruption_shrinks_days_cover_remaining():
    low = compute_scenario(corridor="hormuz", disruption_factor=0.1)
    high = compute_scenario(corridor="hormuz", disruption_factor=0.8)
    assert high.days_cover_remaining < low.days_cover_remaining


def test_days_cover_remaining_decreases_monotonically_near_zero_disruption():
    zero = compute_scenario(corridor="hormuz", disruption_factor=0.0)
    small = compute_scenario(corridor="hormuz", disruption_factor=0.05)
    larger = compute_scenario(corridor="hormuz", disruption_factor=0.3)
    assert zero.days_cover_remaining > small.days_cover_remaining > larger.days_cover_remaining


def test_price_rise_pct_scales_with_disruption_and_sensitivity():
    assert crude_price_rise_pct(disruption_factor=0.3, price_sensitivity=1.0) == pytest.approx(30.0)
    assert crude_price_rise_pct(disruption_factor=0.3, price_sensitivity=0.5) == pytest.approx(15.0)


def test_cpi_gdp_cad_formulas_are_internally_consistent():
    s = compute_scenario(
        corridor="hormuz",
        disruption_factor=0.4,
        cpi_sensitivity=0.35,
        cad_sensitivity=0.4,
        brent_baseline_usd_bbl=80.0,
    )
    assert s.cpi_delta_pp == pytest.approx((s.crude_price_rise_pct / 10) * 0.35)
    assert s.gdp_drag_bps == pytest.approx((s.crude_price_rise_pct / 10) * GDP_DRAG_BPS_PER_10PCT)
    crude_usd_increase = 80.0 * (s.crude_price_rise_pct / 100)
    assert s.cad_widening_pct_gdp == pytest.approx((crude_usd_increase / 10) * 0.4)


def test_all_scenario_fields_round_trip_inputs():
    s = compute_scenario(corridor="hormuz", disruption_factor=0.3, spr_fill_pct=0.5)
    assert s.corridor == "hormuz"
    assert s.disruption_factor == 0.3
    assert s.spr_fill_pct == 0.5
