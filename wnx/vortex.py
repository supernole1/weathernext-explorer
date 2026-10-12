"""Stratospheric polar vortex watch: ECMWF's 51-member ensemble forecast of the 10 hPa wind around 60°N.

The standard measure of the vortex's strength is the west-to-east (zonal) wind at 10 hPa (about 19 miles up),
averaged all the way around the 60°N latitude circle. When it reverses to easterly between November and March,
that is a sudden stratospheric warming (SSW), the vortex "disruption" that can send Arctic air south 1–4 weeks later.

WeatherNext stops at 50 hPa and Open-Meteo's GFS ensemble has no 10 hPa data, but its ECMWF ensemble does.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .forecast import HEADERS

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
META_URL = "https://ensemble-api.open-meteo.com/data/ecmwf_ifs025_ensemble/static/meta.json"
CACHE = Path(__file__).resolve().parent.parent / "data" / "seasonal" / "vortex.json"
LONS = list(range(-180, 180, 15))   # 24 points around the circle are plenty for a zonal mean

# Approximate long-term average 10 hPa / 60°N zonal wind (m/s) by date, from published reanalysis climatologies.
# Open-Meteo has no historical stratospheric data, so this is a rough guide (good to about ±5 m/s), not exact.
NORMAL = [("01-01", 33), ("01-15", 32), ("02-01", 29), ("02-15", 26), ("03-01", 21), ("03-15", 15), ("04-01", 9),
          ("04-15", 3), ("05-01", -3), ("06-01", -10), ("07-01", -13), ("08-01", -8), ("09-01", 0), ("10-01", 12),
          ("10-15", 17), ("11-01", 24), ("11-15", 28), ("12-01", 31), ("12-15", 33)]


def normal(t) -> float:
    """Approximate normal for a date, interpolated between the anchor dates above."""
    t = pd.Timestamp(t)
    doy = t.dayofyear
    xs = [pd.Timestamp(f"2001-{d}").dayofyear for d, _ in NORMAL]
    ys = [v for _, v in NORMAL]
    return float(np.interp(doy, xs + [xs[0] + 365], ys + [ys[0]]))


def fetch(max_age_hours: float = 6) -> dict:
    """Raw ensemble forecast (cached) plus the time of the ECMWF run it came from."""
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < max_age_hours * 3600:
        return json.loads(CACHE.read_text())
    params = dict(latitude=",".join(["60"] * len(LONS)), longitude=",".join(map(str, LONS)),
                  hourly="wind_speed_10hPa,wind_direction_10hPa", models="ecmwf_ifs025", forecast_days=15,
                  wind_speed_unit="ms", temporal_resolution="hourly_6")
    for attempt in range(3):
        body = requests.get(ENSEMBLE_URL, headers=HEADERS, params=params, timeout=120).json()
        if isinstance(body, list):
            break
        if "limit" in str(body.get("reason", "")).lower() and attempt < 2:
            time.sleep(62)
            continue
        raise RuntimeError(body.get("reason"))
    try:
        meta = requests.get(META_URL, headers=HEADERS, timeout=30).json()
    except (requests.RequestException, ValueError):
        meta = {}
    data = {"fetched": datetime.now(timezone.utc).isoformat(), "points": [b["hourly"] for b in body],
            "run": meta.get("last_run_initialisation_time"), "available": meta.get("last_run_availability_time")}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data))
    return data


def zonal_wind(data: dict) -> pd.DataFrame:
    """Zonal-mean westerly wind (m/s) at 10 hPa, 60°N: one column per ensemble member, one row per time (UTC)."""
    points = data["points"]
    keys = sorted(k for k in points[0] if k.startswith("wind_speed_10hPa"))
    cols = {}
    for k in keys:
        member = 0 if k == "wind_speed_10hPa" else int(k.rsplit("member", 1)[1])
        dkey = k.replace("wind_speed", "wind_direction")
        u = [-np.array(p[k], dtype=float) * np.sin(np.radians(np.array(p[dkey], dtype=float))) for p in points]
        cols[member] = np.mean(u, axis=0)   # NaN wherever any longitude is missing: a partial circle isn't a zonal mean
    df = pd.DataFrame(cols, index=pd.to_datetime(points[0]["time"]))
    # Keep only times where nearly every member is present (the last steps can be partly missing).
    return df[df.notna().mean(axis=1) > 0.9].dropna(axis=1, how="all")


def status(u: pd.DataFrame) -> dict:
    """Plain-language state of the vortex from the ensemble."""
    n = u.shape[1]
    mean = u.mean(axis=1)
    now, end = mean.iloc[0], mean.iloc[-5:].mean()
    norm_now, norm_end = normal(u.index[0]), normal(u.index[-1])
    reversed_ = (u < 0).any(axis=0)
    n_rev = int(reversed_.sum())
    first = u.lt(0).idxmax()[reversed_]   # first reversal time per member
    month = u.index[0].month
    in_season = month in (11, 12, 1, 2, 3)   # SSWs are defined Nov–Mar; later reversals are the spring "final warming"
    out = {"n": n, "now": now, "end": end, "normal_now": norm_now, "normal_end": norm_end, "n_rev": n_rev,
           "first_rev": first.median() if n_rev else None, "in_season": in_season}
    if not in_season and month in (4, 5, 6, 7, 8, 9):
        out.update(label="Summer pattern" if month in (5, 6, 7, 8) else "Seasonal change",
                   color="neutral", text="Between spring and early fall the stratospheric winds turn around every "
                   "year as part of the normal cycle, so there's no vortex to watch. It re-forms in September–October.")
    elif now < 0:
        out.update(label="Disrupted", color="cold", text="The vortex winds have reversed: a sudden stratospheric "
                   "warming is under way.")
    elif n_rev / n >= 0.5:
        out.update(label="Disruption likely", color="cold",
                   text=f"{n_rev} of {n} forecasts reverse the vortex winds within 15 days.")
    elif n_rev / n >= 0.1:
        out.update(label="Disruption possible", color="watch",
                   text=f"{n_rev} of {n} forecasts reverse the vortex winds within 15 days.")
    elif end < norm_end - 10:
        out.update(label="Weakening", color="watch", text="Forecast to weaken well below normal, but no forecast "
                   "reverses it within 15 days.")
    elif end > norm_end + 10:
        out.update(label="Strong", color="warm", text="Stronger than normal, with no disruption in sight. A strong "
                   "vortex tends to keep Arctic air bottled up in the far north.")
    else:
        out.update(label="Near normal", color="neutral", text="Close to its normal strength for the time of year, "
                   f"and {'no' if n_rev == 0 else f'only {n_rev} of {n}'} forecasts reverse it within 15 days.")
    return out
