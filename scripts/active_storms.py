"""List every tropical cyclone in the latest WeatherNext forecast and map their predicted tracks.

    python scripts/active_storms.py            # WeatherNext 3
    python scripts/active_storms.py --model OPER
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wnx import about, maps, nhc, plots, weatherlab  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="WNV3")
    args = ap.parse_args()

    init = weatherlab.latest_init(args.model)
    if init is None:
        sys.exit("No recent forecast file found.")
    means = weatherlab.load(args.model, init)
    members = weatherlab.load(args.model, init, product="ensemble")
    print(f"{weatherlab.MODELS[args.model][0]} - init {init:%Y-%m-%d %HZ}\n")
    if means.empty:
        print("No tracked cyclones in this forecast.")
        return

    rows = []
    for storm, m in means.groupby("track_id"):
        now, peak = m.iloc[0], m.loc[m["wind_kt"].idxmax()]
        last = m.iloc[-1]
        rows.append(f"{storm:10} now {now.lat:5.1f},{now.lon:7.1f} {now.wind_kt:4.0f} kt | "
                    f"peak {peak.wind_kt:4.0f} kt / {peak.mslp_hpa:4.0f} hPa at +{peak.lead_time_hours:3d}h | "
                    f"tracked to +{last.lead_time_hours}h ({last.lat:.1f},{last.lon:.1f})")
    print("\n".join(rows))

    official = [nhc.official_forecast(s) for s in means["track_id"].unique()]
    fig = maps.track_map(members, means, None, height=700, official=official)
    out = plots.write_report([about.ABOUT_HTML, fig, maps.HOW_TO_READ], ROOT / "outputs" / f"active_storms_{args.model}.html",
                             f"Active cyclones — {args.model}, init {init:%Y-%m-%d %HZ}",
                             notes="<br>".join(rows))
    print(f"\nMap written: {out}")


if __name__ == "__main__":
    main()
