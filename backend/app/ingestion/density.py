import statistics
from collections import deque


class DensityTracker:
    """Rolling-window vessel-count anomaly detector.

    ASSUMPTION -> docs/04_model_assumptions_and_constants.md specifies a 30-day
    moving average baseline for X_density; a live demo cannot accumulate 30 days
    of history. This substitutes a short in-memory rolling window (default 20
    samples) as a calibrated stand-in, documented here and in docs/04.

    STUB -> AISStream PositionReport carries no vessel-type field, so this counts
    all AIS contacts in the bbox, not tankers specifically. Real tanker filtering
    requires subscribing to ShipStaticData messages (TODO: Phase 2, docs/02).
    """

    def __init__(self, window: int = 20, min_samples: int = 5, sigma_threshold: float = 1.5):
        self._samples: deque[int] = deque(maxlen=window)
        self.min_samples = min_samples
        self.sigma_threshold = sigma_threshold

    def sample(self, count: int) -> None:
        self._samples.append(count)

    def x_density(self) -> float:
        if len(self._samples) < self.min_samples:
            return 0.0
        mean = statistics.mean(self._samples)
        stdev = statistics.pstdev(self._samples)
        if stdev == 0:
            return 0.0
        latest = self._samples[-1]
        return 1.0 if latest <= mean - self.sigma_threshold * stdev else 0.0
