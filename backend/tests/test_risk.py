import math

import pytest

from app.engine.risk import BETA0, WEIGHTS, compute_risk


def test_all_zero_features_gives_background_probability():
    r = compute_risk(corridor="hormuz", x_kinetic=0.0, x_density=0.0)
    assert r.probability == pytest.approx(1 / (1 + math.exp(3.0)), abs=1e-6)
    assert r.probability == pytest.approx(0.0474, abs=1e-3)


def test_contributions_sum_matches_logit_offset_from_beta0():
    r = compute_risk(corridor="hormuz", x_kinetic=0.8, x_density=1.0)
    logit = math.log(r.probability / (1 - r.probability))
    assert logit == pytest.approx(BETA0 + sum(r.contributions.values()), abs=1e-6)


def test_unwired_features_are_present_but_zero():
    r = compute_risk(corridor="hormuz", x_kinetic=0.5, x_density=0.5)
    for stub_feature in ("sanctions", "weather", "freight"):
        assert r.features[stub_feature] == 0.0
        assert r.contributions[stub_feature] == 0.0


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_default_feature_states_are_reported():
    r = compute_risk(corridor="hormuz", x_kinetic=0.0, x_density=0.0)
    assert r.feature_states["kinetic"] == "LIVE"
    assert r.feature_states["density"] == "LIVE"
    for stub in ("sanctions", "weather", "freight"):
        assert r.feature_states[stub] == "STUB"


def test_no_coverage_excludes_density_and_renormalizes_weights():
    r = compute_risk(
        corridor="hormuz",
        x_kinetic=0.5,
        x_density=1.0,  # a "reading" that must be ignored — there is no sensor
        feature_states={"density": "NO_TERRESTRIAL_COVERAGE"},
    )
    assert r.feature_states["density"] == "NO_TERRESTRIAL_COVERAGE"
    assert r.features["density"] == 0.0
    assert r.contributions["density"] == 0.0
    # Remaining weights renormalized: kinetic 0.40 / (1 - 0.25) applied to 0.5.
    assert r.contributions["kinetic"] == pytest.approx(0.40 / 0.75 * 0.5)
    # Logit identity still holds with the renormalized contributions.
    logit = math.log(r.probability / (1 - r.probability))
    assert logit == pytest.approx(BETA0 + sum(r.contributions.values()), abs=1e-6)


def test_no_coverage_with_zero_live_features_stays_at_background():
    covered = compute_risk(corridor="hormuz", x_kinetic=0.0, x_density=0.0)
    uncovered = compute_risk(
        corridor="hormuz",
        x_kinetic=0.0,
        x_density=0.0,
        feature_states={"density": "NO_TERRESTRIAL_COVERAGE"},
    )
    assert uncovered.probability == pytest.approx(covered.probability)


def test_warming_up_is_also_excluded():
    r = compute_risk(
        corridor="hormuz",
        x_kinetic=0.0,
        x_density=1.0,
        feature_states={"density": "WARMING_UP"},
    )
    assert r.contributions["density"] == 0.0
    assert r.features["density"] == 0.0
