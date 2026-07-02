from app.ingestion.density import DensityTracker


def test_returns_zero_with_insufficient_samples():
    t = DensityTracker(min_samples=5)
    for count in [20, 21, 19]:
        t.sample(count)
    assert t.x_density() == 0.0


def test_flags_anomaly_when_count_drops_far_below_rolling_mean():
    t = DensityTracker(min_samples=5, sigma_threshold=1.5)
    for count in [20, 21, 19, 22, 20]:
        t.sample(count)
    assert t.x_density() == 0.0  # baseline established, no drop yet

    t.sample(2)  # sharp drop
    assert t.x_density() == 1.0


def test_window_is_bounded():
    t = DensityTracker(window=3, min_samples=1)
    for count in [10, 10, 10, 10, 10]:
        t.sample(count)
    assert len(t._samples) == 3
