"""Turn trend statistics into plain-language, statistically honest insights.

Rules of thumb baked in:
  * never say "increased" unless the Mann-Kendall test is significant (p < 0.05)
  * percentage change is only quoted when the early-period mean is > 0
  * short windows and data-quality problems always produce an explicit caveat
"""
from __future__ import annotations

METRICS = {
    "frequency": {"label": "Heatwave frequency", "unit": "events/yr", "long_unit": "heatwave events per year"},
    "days": {"label": "Heatwave days", "unit": "days/yr", "long_unit": "heatwave days per year"},
    "mean_duration": {"label": "Average duration", "unit": "days/event", "long_unit": "days per event"},
    "intensity": {"label": "Intensity", "unit": "°C", "long_unit": "°C above the threshold on heatwave days"},
}
ALPHA = 0.05


def _fmt(x: float) -> str:
    return f"{x:.1f}" if abs(x) < 100 else f"{x:.0f}"


def metric_insight(key: str, trend: dict) -> dict:
    meta = METRICS[key]
    label, unit = meta["label"], meta["long_unit"]
    mk, pc, sen = trend.get("mann_kendall"), trend.get("period_change"), trend.get("sens_slope_per_decade")
    if mk is None or pc is None or trend["n_years"] < 8:
        return {
            "metric": key,
            "direction": "insufficient",
            "significant": False,
            "text": f"Not enough valid years to assess a trend in {label.lower()}.",
        }

    significant = mk["p_value"] is not None and mk["p_value"] < ALPHA
    direction = "increase" if (mk["z"] or 0) > 0 else "decrease" if (mk["z"] or 0) < 0 else "flat"
    e0, e1 = pc["early_period"]
    l0, l1 = pc["late_period"]
    contrast = f"{_fmt(pc['early_mean'])} → {_fmt(pc['late_mean'])} {unit}, {e0}–{e1} vs {l0}–{l1}"
    pct = pc["pct_change"]
    p_txt = "p < 0.001" if mk["p_value"] < 0.001 else f"p = {mk['p_value']:.3f}"
    sen_txt = f"Sen's slope {sen:+.2f} {meta['unit']} per decade" if sen is not None else ""

    if significant and direction in ("increase", "decrease"):
        verb = "increased" if direction == "increase" else "decreased"
        change = f"by {abs(pct):.0f}%" if pct is not None else f"by {abs(pc['abs_change']):.1f} {meta['unit']}"
        text = f"{label} {verb} {change}: {contrast}. Statistically significant (Mann-Kendall {p_txt}); {sen_txt}."
    else:
        direction_word = {"increase": "an upward", "decrease": "a downward"}.get(direction, "no")
        text = (
            f"No statistically significant trend in {label.lower()} (Mann-Kendall {p_txt}). "
            f"The data lean toward {direction_word} tendency ({contrast}), but year-to-year variability is "
            f"large enough that it cannot be distinguished from chance."
        )
    return {
        "metric": key,
        "direction": direction if significant else "none",
        "significant": significant,
        "pct_change": None if pct is None else round(pct, 1),
        "text": text,
    }


def build_insights(trends: dict[str, dict], first_year: int, last_year: int) -> dict:
    items = [metric_insight(k, trends[k]) for k in METRICS]
    by_key = {i["metric"]: i for i in items}

    days = by_key["days"]
    headline = days["text"]
    if days["significant"]:
        pct = days.get("pct_change")
        if pct is not None:
            verb = "increased" if days["direction"] == "increase" else "decreased"
            pc = trends["days"]["period_change"]
            detail = f" ({_fmt(pc['early_mean'])} → {_fmt(pc['late_mean'])} days per year, {pc['early_period'][0]}–{pc['early_period'][1]} vs {pc['late_period'][0]}–{pc['late_period'][1]})"
            headline = f"Heatwave days have {verb} by {abs(pct):.0f}% in this region between {first_year} and {last_year}{detail}."
        else:
            verb = "increased" if days["direction"] == "increase" else "decreased"
            headline = f"Heatwave days have {verb} in this region between {first_year} and {last_year}."
    elif days["direction"] != "insufficient":
        headline = f"No statistically significant change in heatwave days between {first_year} and {last_year}."

    n_years = last_year - first_year + 1
    caveats = [
        "Values come from ERA5 reanalysis on a ~25 km grid, not a weather station; urban heat-island effects are not captured.",
        "Heatwave thresholds are fixed to the 1991–2020 baseline, so by construction about 5% of baseline days exceed the 95th percentile.",
        "Each event is counted in the year it started. The Mann-Kendall test assumes independent years; year-to-year autocorrelation is not corrected for.",
    ]
    if n_years < 20:
        caveats.insert(0, f"A {n_years}-year window is short for trend detection; treat results as indicative only.")
    return {"headline": headline, "items": items, "caveats": caveats}
