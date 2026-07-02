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


def compute_risk(
    corridor: str,
    x_kinetic: float,
    x_density: float,
    x_sanctions: float = 0.0,  # STUB -> OpenSanctions vessel screening, docs/02 §4 (Phase 2)
    x_weather: float = 0.0,  # STUB -> Open-Meteo Marine wave height, docs/02 §6 (Phase 2)
    x_freight: float = 0.0,  # STUB -> FRED BCTI/BDI freight proxy, docs/02 §7 (Phase 2)
    now: datetime | None = None,
) -> RiskScore:
    features = {
        "kinetic": x_kinetic,
        "density": x_density,
        "sanctions": x_sanctions,
        "weather": x_weather,
        "freight": x_freight,
    }
    contributions = {name: WEIGHTS[name] * value for name, value in features.items()}
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
    )
