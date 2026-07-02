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
