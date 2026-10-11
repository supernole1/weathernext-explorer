"""Build an interactive HTML report for one storm: spaghetti map, intensity plume, error vs lead time.

Example (Hurricane Melissa, Jamaica landfall 28 Oct 2025):
    python scripts/storm_report.py AL132025 --start 2025-10-21 --end 2025-10-29 --spaghetti 2025-10-25T06
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wnx import about, history, maps, nhc, observed, plots, verify, weatherlab  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def history_section(storm: str, name: str, obs) -> list:
    """'How the forecasts did' map + scoreboard, comparing past forecasts with the observed track."""
    if obs.empty:
        return []
    print("Comparing past forecasts with the actual track...")
    runs = history.gather(storm, obs)
    if not runs:
        return []
    return [f"<h3 style='margin-top:28px'>How the forecasts did: {name}</h3>", maps.HISTORY_INTRO,
            maps.history_map(obs, runs), history.scoreboard_html(runs, name)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("storm", help="ATCF id, e.g. AL132025 (basin + number + year)")
    ap.add_argument("--latest", action="store_true",
                    help="show each model's newest published run, plus --days-back of earlier runs")
    ap.add_argument("--days-back", type=float, default=2,
                    help="with --latest: how many days of earlier runs to include (default 2)")
    ap.add_argument("--start", help="first init date/time, e.g. 2025-10-21 or 2025-10-21T12")
    ap.add_argument("--end", help="last init date/time")
    ap.add_argument("--models", default="WNV3,OPER", help=f"comma list from {list(weatherlab.MODELS)}")
    ap.add_argument("--spaghetti", help="init time whose full ensemble is drawn (default: --start)")
    ap.add_argument("--max-lead", type=int, default=120, help="max lead hours for error stats")
    args = ap.parse_args()

    storm = args.storm.upper()
    models = [m.strip().upper() for m in args.models.split(",")]
    if args.latest:
        # Each model publishes on its own schedule, so each gets its own newest run.
        spag_for = {m: weatherlab.latest_init(m) for m in models}
        for m, t in spag_for.items():
            print(f"Latest {m} run: {t:%Y-%m-%d %HZ}" if t else f"No {m} run in the last 72 hours")
        spag_for = {m: t for m, t in spag_for.items() if t}
        if not spag_for:
            sys.exit("No recent runs published.")
        end = max(spag_for.values())
        start = datetime.fromisoformat(args.start) if args.start else end - timedelta(days=args.days_back)
    elif args.start and args.end:
        start, end = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
        spag = datetime.fromisoformat(args.spaghetti) if args.spaghetti else start
        spag_for = {m: spag for m in models}
    else:
        ap.error("give --latest, or both --start and --end")

    print(f"Loading observed track for {storm}...")
    obs = observed.load_storm(storm)
    name = obs["name"].iloc[-1].title() if not obs.empty else storm
    print(f"  {len(obs)} observed points from {obs.attrs['source']}, latest {obs['valid_time'].max():%m-%d %HZ}"
          if not obs.empty else "  none found (storm may be too new)")

    official = nhc.official_forecast(storm)
    print(f"NHC advisory {official.advisory} issued {official.issued:%Y-%m-%d %HZ}: "
          f"{official.current_wind_kt:.0f} kt at {official.current_lat}, {official.current_lon}"
          if official else "No active NHC advisory for this storm (NHC covers Atlantic/E+C Pacific only).")

    means, members = [], []
    for model in models:
        print(f"Downloading {model} ensemble means {start:%Y-%m-%d %H}Z -> {end:%Y-%m-%d %H}Z...")
        m = weatherlab.load_range(model, start, end, storm=storm)
        print(f"  {m['init_time'].nunique() if not m.empty else 0} init times with this storm")
        means.append(m)
        if model == models[0] and model in spag_for:
            members.append(weatherlab.load(model, spag_for[model], product="ensemble", storm=storm))
    import pandas as pd
    means = [m for m in means if not m.empty]
    if not means:
        sys.exit(f"No forecasts found for {storm} in that window.")
    means = pd.concat(means, ignore_index=True)
    # Full ensemble is drawn for the first model only, to keep the map readable.
    members_first = members[0] if members else pd.DataFrame()
    spag_means = pd.concat([means[(means["model"] == m) & (means["init_time"] == t)]
                            for m, t in spag_for.items()], ignore_index=True)
    runs = ", ".join(f"{m} {t:%m-%d %HZ}" for m, t in spag_for.items())

    figs = [
        nhc.conditions_html(official),
        about.ABOUT_HTML,
        f"<h3>{name} ({storm}): newest forecast tracks ({runs})</h3>"
        "<p>Scroll to zoom, hover the dots for time and intensity. Use the box at top right to "
        "switch base maps or hide layers. County lines show for the US.</p>",
        maps.track_map(members_first, spag_means, obs, official=[official]),
        maps.HOW_TO_READ,
        *history_section(storm, name, obs),
        plots.intensity_plume(members_first, spag_means, obs,
                              f"{name}: forecast max wind ({runs})", official),
    ]
    table_html = ""
    if not obs.empty:
        paired = verify.pair_with_obs(means, obs)
        errs = verify.error_by_lead(paired, args.max_lead)
        figs += [
            plots.error_chart(errs, "track_error_mi", "Mean track error (miles)",
                              f"{name}: track error vs forecast length (runs {start:%m-%d}–{end:%m-%d}, "
                              f"checked against {obs.attrs['source']} through {obs['valid_time'].max():%m-%d %HZ})"),
            plots.error_chart(errs, "wind_mae_mph", "Mean absolute wind error (mph)",
                              f"{name}: intensity error vs forecast length"),
        ]
        pivot = errs[errs["lead_time_hours"] % 24 == 0].pivot(
            index="lead_time_hours", columns="model", values="track_error_mi").round(0)
        table_html = "<h3>Mean track error (miles) by forecast length (hours)</h3>" + pivot.to_html()
        print("\nMean track error (miles):\n" + pivot.to_string())

    out = plots.write_report(
        figs, ROOT / "outputs" / f"{storm}_report.html", f"{name} ({storm}) — WeatherNext cyclone forecasts",
        notes=f"Models: {', '.join(models)}. Ensemble means for every 6-hourly init from {start:%Y-%m-%d %HZ} "
              f"to {end:%Y-%m-%d %HZ}; newest runs shown on the map: {runs}; full ensemble drawn for {models[0]}. "
              "Hover any line for values.",
        table_html=table_html)
    print(f"\nReport written: {out}")


if __name__ == "__main__":
    main()
