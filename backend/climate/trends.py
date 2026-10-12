"""Trend statistics with no heavy dependencies (pure stdlib).

* OLS linear regression with a two-sided t-test on the slope
* Mann-Kendall test (tie-corrected, normal approximation) + Sen's slope
* centred rolling mean
* early-vs-late period comparison

Hazard counts are zero-inflated and non-normal, which is why the non-parametric
Mann-Kendall / Sen pair is the headline test and OLS is reported alongside it.
"""
from __future__ import annotations

import math
from collections import Counter
from statistics import median
from typing import Sequence


# ----------------------------------------------------------------- special fns
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    if df <= 0:
        return float("nan")
    return _betainc(df / 2.0, 0.5, df / (df + t * t))


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


# --------------------------------------------------------------------- helpers
def _pairs(xs: Sequence[float], ys: Sequence[float | None]) -> list[tuple[float, float]]:
    return [(x, y) for x, y in zip(xs, ys) if y is not None]


def _r(x: float | None, nd: int = 4) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, nd)


# ------------------------------------------------------------------ regression
def linear_regression(xs: Sequence[float], ys: Sequence[float | None]) -> dict | None:
    pts = _pairs(xs, ys)
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    if sxx == 0:
        return None
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_res = max(syy - slope * sxy, 0.0)
    r2 = 1 - ss_res / syy if syy > 0 else 0.0
    if n > 2 and ss_res > 0:
        se = math.sqrt(ss_res / (n - 2) / sxx)
        p = t_two_sided_p(slope / se, n - 2)
    else:  # perfect fit or flat series
        se, p = 0.0, (1.0 if syy == 0 else 0.0)
    return {"slope": slope, "intercept": intercept, "r2": r2, "p_value": p, "stderr": se, "n": n}


# ---------------------------------------------------------------- Mann-Kendall
def mann_kendall(ys: Sequence[float | None]) -> dict | None:
    """Two-sided Mann-Kendall test on the ordered, non-missing values."""
    v = [y for y in ys if y is not None]
    n = len(v)
    if n < 4:
        return None
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            d = v[j] - v[i]
            s += (d > 0) - (d < 0)
    ties = Counter(v)
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties.values() if t > 1)) / 18.0
    if var <= 0:  # constant series
        return {"s": s, "z": 0.0, "p_value": 1.0, "tau": 0.0, "trend": "none", "n": n}
    z = 0.0 if s == 0 else (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var)
    p = normal_two_sided_p(z)
    return {
        "s": s,
        "z": z,
        "p_value": p,
        "tau": s / (n * (n - 1) / 2.0),
        "trend": "none" if p >= 0.05 else ("increasing" if z > 0 else "decreasing"),
        "n": n,
    }


def sens_slope(xs: Sequence[float], ys: Sequence[float | None]) -> float | None:
    pts = _pairs(xs, ys)
    if len(pts) < 3:
        return None
    slopes = [
        (pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0])
        for i in range(len(pts) - 1)
        for j in range(i + 1, len(pts))
        if pts[j][0] != pts[i][0]
    ]
    return median(slopes) if slopes else None


# -------------------------------------------------------------------- rolling
def rolling_mean(ys: Sequence[float | None], window: int = 5, min_periods: int = 3) -> list[float | None]:
    """Centred rolling mean; None where fewer than ``min_periods`` valid points."""
    half = window // 2
    out: list[float | None] = []
    for i in range(len(ys)):
        chunk = [y for y in ys[max(0, i - half): i + half + 1] if y is not None]
        out.append(round(sum(chunk) / len(chunk), 4) if len(chunk) >= min_periods else None)
    return out


# ------------------------------------------------------------ period contrast
def period_change(years: Sequence[int], ys: Sequence[float | None]) -> dict | None:
    """Compare the mean of the first and last k valid years (k = up to 10)."""
    pts = _pairs(years, ys)
    if len(pts) < 6:
        return None
    k = max(3, min(10, len(pts) // 3))
    early, late = pts[:k], pts[-k:]
    e = sum(p[1] for p in early) / k
    l = sum(p[1] for p in late) / k
    return {
        "early_period": [int(early[0][0]), int(early[-1][0])],
        "late_period": [int(late[0][0]), int(late[-1][0])],
        "early_mean": e,
        "late_mean": l,
        "abs_change": l - e,
        "pct_change": ((l - e) / e * 100.0) if e > 0 else None,
    }


def analyse_metric(years: Sequence[int], ys: Sequence[float | None]) -> dict:
    """Full trend block for one metric over a selected window."""
    xs = [float(y) for y in years]
    reg = linear_regression(xs, ys)
    mk = mann_kendall(ys)
    sen = sens_slope(xs, ys)
    valid = [(x, y) for x, y in zip(xs, ys) if y is not None]
    sen_intercept = None
    if sen is not None and valid:
        sen_intercept = median(y - sen * x for x, y in valid)

    def line(slope, intercept):
        if slope is None or intercept is None:
            return [None] * len(xs)
        return [_r(intercept + slope * x, 4) for x in xs]

    return {
        "n_years": len(valid),
        "mean": _r(sum(y for _, y in valid) / len(valid)) if valid else None,
        "linear_regression": None
        if reg is None
        else {
            "slope_per_decade": _r(reg["slope"] * 10),
            "p_value": _r(reg["p_value"]),
            "r2": _r(reg["r2"]),
            "stderr_per_decade": _r(reg["stderr"] * 10),
        },
        "mann_kendall": None
        if mk is None
        else {
            "tau": _r(mk["tau"]),
            "z": _r(mk["z"]),
            "p_value": _r(mk["p_value"]),
            "trend": mk["trend"],
        },
        "sens_slope_per_decade": _r(sen * 10) if sen is not None else None,
        "period_change": period_change(years, ys),
        "series": {
            "rolling_mean_5y": rolling_mean(ys, 5, 3),
            "regression_line": line(reg["slope"], reg["intercept"]) if reg else [None] * len(xs),
            "sen_line": line(sen, sen_intercept),
        },
    }
