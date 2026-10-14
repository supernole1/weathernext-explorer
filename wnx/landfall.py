"""Estimate where and when a storm came ashore from its 6-hourly observed track.

The track is interpolated to hourly points and checked against Open-Meteo's elevation data (0 m = water).
Every water-to-land crossing is a candidate; the one with the strongest wind is "the" landfall.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .forecast import HEADERS

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
CACHE = Path(__file__).resolve().parent.parent / "data" / "landfall"


def _hourly(obs: pd.DataFrame) -> pd.DataFrame:
    o = obs.set_index("valid_time")[["lat", "lon", "wind_kt"]].astype(float)
    o = o[~o.index.duplicated()]
    times = pd.date_range(o.index.min(), o.index.max(), freq="1h")
    return o.reindex(o.index.union(times)).interpolate(method="time").loc[times].reset_index(names="time")


def _elevations(lats, lons) -> list[float]:
    out = []
    for i in range(0, len(lats), 100):
        params = dict(latitude=",".join(f"{v:.3f}" for v in lats[i:i + 100]),
                      longitude=",".join(f"{v:.3f}" for v in lons[i:i + 100]))
        for attempt in range(3):   # the free API occasionally answers 503 or 429; wait and retry
            r = requests.get(ELEVATION_URL, headers=HEADERS, timeout=60, params=params)
            if r.status_code not in (429, 503) or attempt == 2:
                break
            time.sleep(20)
        r.raise_for_status()
        out += r.json()["elevation"]
    return out


def place_near(lat: float, lon: float) -> str:
    """'Destin, Florida'-style name for a point, or '' if the lookup fails."""
    try:
        r = requests.get(REVERSE_URL, headers=HEADERS, timeout=20,
                         params=dict(lat=lat, lon=lon, format="jsonv2", zoom=10))
        a = r.json().get("address", {})
    except (requests.RequestException, ValueError):
        return ""
    town = a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or a.get("county") or ""
    return ", ".join(x for x in (town, a.get("state") or a.get("country") or "") if x)


def find(storm: str, obs: pd.DataFrame) -> dict | None:
    """{'time', 'lat', 'lon', 'wind_kt', 'place'} for the strongest landfall, or None if it never came ashore.
    Cached per storm, keyed to the last observed time."""
    if obs.empty or len(obs) < 2:
        return None
    key = f"{storm}_{obs['valid_time'].max():%Y%m%d%H}"
    path = CACHE / f"{key}.json"
    if path.exists():
        hit = json.loads(path.read_text())
        return {**hit, "time": pd.Timestamp(hit["time"])} if hit else None

    h = _hourly(obs)
    try:
        land = np.array(_elevations(list(h["lat"]), list(h["lon"]))) > 0
    except requests.RequestException:
        return None   # not cached, so the next build tries again
    hit = None
    crossings = [i for i in range(1, len(h)) if land[i] and not land[i - 1]]
    if crossings:
        i = max(crossings, key=lambda j: h["wind_kt"].iloc[j - 1])   # strongest storm as it reached land
        r = h.iloc[i]
        # Wind: the last observation before landfall. Interpolating toward the next (inland) report would
        # mix in the weakening after landfall.
        before = obs[obs["valid_time"] <= r["time"]]
        wind = float(before["wind_kt"].iloc[-1]) if not before.empty else float(r["wind_kt"])
        hit = {"time": r["time"].isoformat(), "lat": round(float(r["lat"]), 2), "lon": round(float(r["lon"]), 2),
               "wind_kt": wind, "place": place_near(float(r["lat"]), float(r["lon"]))}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hit))
    return {**hit, "time": pd.Timestamp(hit["time"])} if hit else None
