import math

from backend.climate import trends


def test_t_pvalue_matches_reference():
    # scipy.stats.t.sf(2.0, 10) * 2 = 0.07339
    assert abs(trends.t_two_sided_p(2.0, 10) - 0.07339) < 1e-4
    assert abs(trends.t_two_sided_p(0.0, 5) - 1.0) < 1e-9


def test_linear_regression_recovers_slope():
    xs = list(range(1990, 2021))
    ys = [2 + 0.5 * (x - 1990) for x in xs]
    reg = trends.linear_regression(xs, ys)
    assert math.isclose(reg["slope"], 0.5, abs_tol=1e-9)
    assert reg["r2"] > 0.999


def test_regression_ignores_missing():
    xs = list(range(10))
    ys = [1.0, None, 3.0, None, 5.0, 6.0, 7.0, 9.0, 9.5, 11.0]
    assert trends.linear_regression(xs, ys)["n"] == 8


def test_mann_kendall_monotonic_is_significant():
    mk = trends.mann_kendall(list(range(1, 21)))
    assert mk["trend"] == "increasing" and mk["p_value"] < 0.001 and math.isclose(mk["tau"], 1.0)


def test_mann_kendall_noise_not_significant():
    mk = trends.mann_kendall([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9, 3, 2, 3, 8, 4])
    assert mk["trend"] == "none"


def test_mann_kendall_constant_series():
    assert trends.mann_kendall([2] * 12)["p_value"] == 1.0


def test_sens_slope_robust_to_outlier():
    xs = list(range(10))
    ys = [x * 2.0 for x in xs]
    ys[5] = 500.0
    assert math.isclose(trends.sens_slope(xs, ys), 2.0, abs_tol=1e-9)


def test_rolling_mean_handles_gaps_and_edges():
    out = trends.rolling_mean([1, 2, None, 4, 5, 6], window=3, min_periods=2)
    assert out[0] == 1.5 and out[2] == 3.0 and out[-1] == 5.5


def test_period_change_zero_baseline_has_no_percentage():
    ys = [0] * 10 + [2] * 10
    pc = trends.period_change(list(range(2000, 2020)), ys)
    assert pc["pct_change"] is None and pc["abs_change"] == 2


def test_period_change_pct():
    ys = [2.0] * 10 + [3.0] * 10
    pc = trends.period_change(list(range(2000, 2020)), ys)
    assert math.isclose(pc["pct_change"], 50.0)
