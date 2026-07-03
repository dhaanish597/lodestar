"""Multi-criteria (MCDM) reroute ranking, constrained by the grade_match
matrix -- a hard input, not a tiebreaker. Formula and weights: docs/04 §C.
"""
from app.config import CrudeGrade
from app.engine.scenario import PRICE_SENSITIVITY, crude_price_rise_pct
from app.models import RerouteOption

# ASSUMPTION -> docs/04 §C
W_COST = 0.35
W_TIME = 0.25
W_GRADE = 0.30
W_CONG = 0.10

# STUB -> FRED BCTI/BDI freight proxy, docs/02 §7 (cut-list #2). ASSUMPTION
# ballpark tanker freight cost per voyage-day, applied uniformly across grades.
FREIGHT_PROXY_USD_BBL_PER_DAY = 0.10

# ASSUMPTION -> port congestion stress rises with corridor disruption as
# buyers scramble for the same alternative barrels; scaled by a grade's
# relative voyage exposure. STUB -> Portcast, docs/02 §8.
CONGESTION_DISRUPTION_SENSITIVITY = 0.15
_CONGESTION_VOYAGE_REFERENCE_DAYS = 30.0


def _minmax_normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def rank_reroutes(
    disruption_factor: float,
    brent_price_usd_bbl: float,
    grades: list[CrudeGrade],
    price_sensitivity: float = PRICE_SENSITIVITY,
) -> list[RerouteOption]:
    price_rise_pct = crude_price_rise_pct(disruption_factor, price_sensitivity)

    landed_costs: list[float] = []
    congestion_penalties: list[float] = []
    for grade in grades:
        landed_cost = (
            brent_price_usd_bbl * (1 + price_rise_pct / 100)
            + grade.price_differential_usd_bbl
            + FREIGHT_PROXY_USD_BBL_PER_DAY * grade.voyage_days
        )
        landed_costs.append(landed_cost)

        congestion = grade.base_congestion_penalty + disruption_factor * CONGESTION_DISRUPTION_SENSITIVITY * (
            grade.voyage_days / _CONGESTION_VOYAGE_REFERENCE_DAYS
        )
        congestion_penalties.append(congestion)

    norm_cost = _minmax_normalize([1 / c for c in landed_costs])
    norm_time = _minmax_normalize([1 / g.voyage_days for g in grades])

    options = []
    for grade, cost, cong, nc, nt in zip(grades, landed_costs, congestion_penalties, norm_cost, norm_time):
        score = W_COST * nc + W_TIME * nt + W_GRADE * grade.grade_match - W_CONG * cong
        options.append(
            RerouteOption(
                source_grade=grade.grade,
                origin=grade.origin,
                api_gravity=grade.api_gravity,
                sulfur_pct=grade.sulfur_pct,
                landed_cost_usd_bbl=round(cost, 2),
                voyage_days=grade.voyage_days,
                grade_match=grade.grade_match,
                congestion_penalty=round(cong, 4),
                score=round(score, 4),
                best_fit_refineries=grade.best_fit_refineries,
            )
        )

    options.sort(key=lambda o: o.score, reverse=True)
    return options
