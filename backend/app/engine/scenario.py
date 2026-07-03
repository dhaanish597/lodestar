"""5-step macroeconomic cascade: supply gap -> refinery utilization -> SPR days
cover -> CPI -> GDP/CAD. All formulas and sourced anchors are docs/04 §B.

Every constant below is named and commented so no assumption is hidden, per
CLAUDE.md's "no hidden constants" rule. `disruption_factor` alone drives the
whole cascade (via `crude_price_rise_pct`) so a single frontend slider
re-computes every step live.
"""
from app.models import Scenario

# --- Sourced anchors (docs/04 §B step3) ---
SPR_DEDICATED_DAYS_AT_FULL_FILL = 9.5
OMC_COMMERCIAL_DAYS = 64.5

# --- ASSUMPTION anchors (docs/04 §B step5, dossier 2019 Abqaiq anchor) ---
GDP_DRAG_BPS_PER_10PCT = 15.0

# ASSUMPTION -> no doc precedent for this mechanism; derives Step 4's
# crude_price_rise_pct directly from disruption_factor so that one slider
# cascades through all 5 steps, instead of requiring a second independent
# "price rise" slider. Calibrated 1:1 as the simplest defensible default;
# TODO: validate against a historical regression.
PRICE_SENSITIVITY = 1.0

# STUB -> no cited source, arbitrary placeholder; used only if the caller
# doesn't supply a live price (e.g. no PriceService wired). Mirrors
# prices.BRENT_FALLBACK_USD_BBL (backend/app/ingestion/prices.py).
BRENT_BASELINE_USD_BBL = 75.0


def crude_price_rise_pct(disruption_factor: float, price_sensitivity: float = PRICE_SENSITIVITY) -> float:
    """Percentage crude price rise implied by a given disruption level, e.g. 30.0 for 30%."""
    return disruption_factor * price_sensitivity * 100.0


def compute_scenario(
    corridor: str,
    disruption_factor: float = 0.30,
    substitution_rate: float = 0.20,
    hormuz_share: float = 0.45,
    india_imports_mbd: float = 4.7,
    spr_fill_pct: float = 0.64,
    cpi_sensitivity: float = 0.35,
    cad_sensitivity: float = 0.35,
    price_sensitivity: float = PRICE_SENSITIVITY,
    brent_baseline_usd_bbl: float = BRENT_BASELINE_USD_BBL,
) -> Scenario:
    # Step 1 — supply gap
    india_hormuz_volume = india_imports_mbd * hormuz_share
    supply_gap_mbd = india_hormuz_volume * disruption_factor * (1 - substitution_rate)

    # Step 2 — refinery run-rate impact.
    # ASSUMPTION -> denominator uses india_imports_mbd (India crude import
    # dependence ~90%, docs/04 SS B) rather than a separately-derived MMT/month
    # throughput figure, to avoid inventing an unsourced unit conversion.
    utilization_drop_pct = supply_gap_mbd / india_imports_mbd if india_imports_mbd else 0.0

    # Step 3 — SPR / buffer drawdown.
    # ASSUMPTION -> days_cover_remaining shrinks buffer_days proportionally to
    # utilization_drop_pct (the fraction of total national demand now unmet),
    # rather than dividing a fixed buffer volume by the raw supply gap. The
    # latter blows toward infinity as the gap shrinks (buffer/gap -> large as
    # gap -> 0), producing a discontinuity where the metric INCREASES for
    # small disruption before decreasing at high disruption -- the opposite
    # of the intended "buffer depleting" narrative. This formula is
    # monotonically decreasing in disruption_factor across the full documented
    # slider range and anchors exactly at the doc's ~74-day baseline
    # (docs/04 SS B step3) when disruption_factor=0.
    buffer_days = SPR_DEDICATED_DAYS_AT_FULL_FILL * spr_fill_pct + OMC_COMMERCIAL_DAYS
    days_cover_remaining = buffer_days * (1 - utilization_drop_pct)

    # Step 4 — fuel price / CPI
    price_rise_pct = crude_price_rise_pct(disruption_factor, price_sensitivity)
    cpi_delta_pp = (price_rise_pct / 10) * cpi_sensitivity

    # Step 5 — GDP & CAD
    gdp_drag_bps = (price_rise_pct / 10) * GDP_DRAG_BPS_PER_10PCT
    crude_usd_increase = brent_baseline_usd_bbl * (price_rise_pct / 100)
    cad_widening_pct_gdp = (crude_usd_increase / 10) * cad_sensitivity

    return Scenario(
        corridor=corridor,
        disruption_factor=disruption_factor,
        substitution_rate=substitution_rate,
        hormuz_share=hormuz_share,
        india_imports_mbd=india_imports_mbd,
        supply_gap_mbd=supply_gap_mbd,
        utilization_drop_pct=utilization_drop_pct,
        spr_fill_pct=spr_fill_pct,
        days_cover_remaining=days_cover_remaining,
        cpi_sensitivity=cpi_sensitivity,
        cpi_delta_pp=cpi_delta_pp,
        gdp_drag_bps=gdp_drag_bps,
        cad_sensitivity=cad_sensitivity,
        cad_widening_pct_gdp=cad_widening_pct_gdp,
        crude_price_rise_pct=price_rise_pct,
        price_sensitivity=price_sensitivity,
        brent_baseline_usd_bbl=brent_baseline_usd_bbl,
    )
