import math
from datetime import datetime, timezone

from app.models import RiskScore

BETA0 = -3.0
WEIGHTS = {
    "kinetic": 0.40,
    "density": 0.25,
    "sanctions": 0.15,
    "weather": 0.10,
    "freight": 0.10,
}

# Default provenance state per feature. Callers override per-request, e.g.
# density becomes NO_TERRESTRIAL_COVERAGE when the corridor's AIS box has
# received zero frames for a full coverage window (see ingestion/coverage.py).
DEFAULT_FEATURE_STATES = {
    "kinetic": "LIVE",
    "density": "LIVE",
    "sanctions": "STUB",  # STUB -> OpenSanctions vessel screening, docs/02 §4 (Phase 2)
    "weather": "STUB",  # STUB -> Open-Meteo Marine wave height, docs/02 §6 (Phase 2)
    "freight": "STUB",  # STUB -> FRED BCTI/BDI freight proxy, docs/02 §7 (Phase 2)
}

# Features in these states are EXCLUDED from the risk sum and the remaining
# weights renormalized to sum to 1.0 — a feature whose sensor has no coverage
# must never read as a genuine 0 ("all clear"). STUB features keep the original
# semantics (value pinned to 0, weight retained) so the resting probability
# stays anchored at sigmoid(β0).
EXCLUDED_STATES = {"NO_TERRESTRIAL_COVERAGE", "WARMING_UP"}


def compute_risk(
    corridor: str,
    x_kinetic: float,
    x_density: float,
    x_sanctions: float = 0.0,
    x_weather: float = 0.0,
    x_freight: float = 0.0,
    feature_states: dict[str, str] | None = None,
    now: datetime | None = None,
) -> RiskScore:
    states = {**DEFAULT_FEATURE_STATES, **(feature_states or {})}
    features = {
        "kinetic": x_kinetic,
        "density": x_density,
        "sanctions": x_sanctions,
        "weather": x_weather,
        "freight": x_freight,
    }

    excluded = {name for name, state in states.items() if state in EXCLUDED_STATES}
    # An excluded feature has no reading — force its reported value to 0.0 so
    # nothing downstream mistakes a coverage void for a measurement.
    for name in excluded:
        features[name] = 0.0

    active_weight_sum = sum(w for name, w in WEIGHTS.items() if name not in excluded)
    scale = 1.0 / active_weight_sum if active_weight_sum > 0 else 0.0

    contributions = {
        name: 0.0 if name in excluded else WEIGHTS[name] * scale * value
        for name, value in features.items()
    }
    logit = BETA0 + sum(contributions.values())
    probability = 1 / (1 + math.exp(-logit))

    return RiskScore(
        corridor=corridor,
        timestamp=now or datetime.now(timezone.utc),
        probability=probability,
        beta0=BETA0,
        weights=WEIGHTS,
        features=features,
        contributions=contributions,
        feature_states=states,
    )
