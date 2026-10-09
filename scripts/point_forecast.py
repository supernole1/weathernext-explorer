"""Ensemble point forecast (WeatherNext 2 via Open-Meteo) for any location: fan of all 64 members.

    python scripts/point_forecast.py 27.95 -82.46 --var wind_speed_10m   # Tampa
    python scripts/point_forecast.py 27.95 -82.46 --var precipitation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.graph_objects as go  # noqa: E402

from wnx import openmeteo, plots  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--var", default="wind_speed_10m")
    ap.add_argument("--days", type=int, default=10)
    args = ap.parse_args()

    df = openmeteo.point_ensemble(args.lat, args.lon, args.var, args.days)
    q = df.groupby("time")["value"].quantile([0.1, 0.5, 0.9]).unstack()
    fig = go.Figure()
    xs, ys = [], []
    for _, m in df.groupby("member"):
        xs += list(m["time"]) + [None]
        ys += list(m["value"]) + [None]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=1, color=plots.MEMBER_COLOR),
                             hoverinfo="skip", name=f"{df['member'].nunique()} members"))
    fig.add_trace(go.Scatter(x=q.index, y=q[0.5], mode="lines", line=dict(width=2, color="#2a78d6"),
                             name="Median"))
    fig.add_trace(go.Scatter(x=q.index, y=q[0.9], mode="lines", line=dict(width=1.5, dash="dash",
                             color="#1c5cab"), name="90th percentile"))
    unit = "kt" if "wind" in args.var else ""
    plots._style(fig, f"WeatherNext 2 ensemble — {args.var} at {args.lat}, {args.lon}").update_layout(
        hovermode="x unified", yaxis_title=f"{args.var} {unit}".strip(), height=450)
    print(q.round(1).to_string())
    out = plots.write_report([fig], ROOT / "outputs" / f"point_{args.lat}_{args.lon}_{args.var}.html",
                             f"Point ensemble — {args.lat}, {args.lon}", refreshable=False)
    print(f"\nChart written: {out}")


if __name__ == "__main__":
    main()
