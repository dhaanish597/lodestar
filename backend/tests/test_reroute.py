import pytest

from app.config import CrudeGrade
from app.engine.reroute import rank_reroutes


def make_grade(**overrides) -> CrudeGrade:
    payload = {
        "grade": "Test", "origin": "Testland", "api_gravity": 30.0, "sulfur_pct": 1.0,
        "class": "medium_sour", "voyage_days": 30, "price_differential_usd_bbl": 0.0,
        "base_congestion_penalty": 0.05, "grade_match": 1.0, "best_fit_refineries": ["Test Refinery"],
    }
    payload.update(overrides)
    return CrudeGrade(**payload)


URALS = make_grade(grade="Urals", origin="Russia", api_gravity=31.0, sulfur_pct=1.3, voyage_days=25,
                    price_differential_usd_bbl=-15.0, base_congestion_penalty=0.10, grade_match=1.0,
                    best_fit_refineries=["RIL Jamnagar", "Nayara Vadinar"])
MEREY = make_grade(grade="Merey", origin="Venezuela", api_gravity=16.0, sulfur_pct=2.7, voyage_days=47,
                    price_differential_usd_bbl=-22.0, base_congestion_penalty=0.15, grade_match=0.0,
                    best_fit_refineries=["RIL Jamnagar (coking only)"])
BONNY = make_grade(grade="Bonny Light", origin="West Africa", api_gravity=35.0, sulfur_pct=0.15, voyage_days=27,
                    price_differential_usd_bbl=1.5, base_congestion_penalty=0.06, grade_match=1.0,
                    best_fit_refineries=["PSU refiners"])


def test_grade_match_is_read_directly_from_input_not_derived():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS, MEREY, BONNY])
    by_grade = {o.source_grade: o for o in options}
    assert by_grade["Urals"].grade_match == 1.0
    assert by_grade["Merey"].grade_match == 0.0
    assert by_grade["Bonny Light"].grade_match == 1.0


def test_incompatible_grade_scores_lower_than_compatible_grade():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS, MEREY])
    by_grade = {o.source_grade: o for o in options}
    assert by_grade["Urals"].score > by_grade["Merey"].score


def test_results_sorted_descending_by_score():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS, MEREY, BONNY])
    scores = [o.score for o in options]
    assert scores == sorted(scores, reverse=True)


def test_higher_disruption_increases_landed_cost_and_congestion_penalty():
    low = rank_reroutes(disruption_factor=0.1, brent_price_usd_bbl=75.0, grades=[URALS])[0]
    high = rank_reroutes(disruption_factor=0.9, brent_price_usd_bbl=75.0, grades=[URALS])[0]
    assert high.landed_cost_usd_bbl > low.landed_cost_usd_bbl
    assert high.congestion_penalty > low.congestion_penalty


def test_higher_disruption_changes_the_score_gap_between_grades():
    # Merey's much longer voyage (47d vs 25d) means its congestion penalty
    # grows faster with disruption_factor than Urals' -- proving the ranking
    # engine is live-reactive to the slider, not a static precomputed table.
    low = rank_reroutes(disruption_factor=0.0, brent_price_usd_bbl=75.0, grades=[URALS, MEREY])
    high = rank_reroutes(disruption_factor=1.0, brent_price_usd_bbl=75.0, grades=[URALS, MEREY])
    low_gap = low[0].score - low[1].score
    high_gap = high[0].score - high[1].score
    assert high_gap != pytest.approx(low_gap)


def test_single_grade_normalizes_without_division_by_zero():
    options = rank_reroutes(disruption_factor=0.3, brent_price_usd_bbl=75.0, grades=[URALS])
    assert len(options) == 1
    assert options[0].score > 0
