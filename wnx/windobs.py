"""Measured surface wind: US airport weather stations (ASOS) and NOAA buoys / coastal stations (NDBC).

ASOS via the Iowa Environmental Mesonet's current-conditions API (updates every 5-20 minutes);
NDBC from its latest-observations file (hourly, many stations every 10 minutes). Both public, no key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

IEM_URL = "https://mesonet.agron.iastate.edu/api/1/currents.json"
NDBC_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
HEADERS = {"User-Agent": "weathernext-explorer/0.1"}
MPH_PER_KT = 1.15078
MPH_PER_MS = 2.23694
FT_PER_M = 3.28084
COLUMNS = ["id", "name", "kind", "lat", "lon", "sust_mph", "gust_mph", "dir_deg", "pressure_mb", "wave_ft", "time"]


def airports(max_age_minutes: int = 90) -> pd.DataFrame:
    try:
        rows = requests.get(IEM_URL, params={"networkclass": "ASOS", "country": "US", "minutes": max_age_minutes},
                            headers=HEADERS, timeout=60).json()["data"]
    except (requests.RequestException, ValueError, KeyError):
        return pd.DataFrame(columns=COLUMNS)
    out = []
    for r in rows:
        if r.get("sknt") is None and r.get("gust") is None:
            continue
        out.append({"id": r["station"], "name": (r.get("name") or r["station"]).title(), "kind": "airport",
                    "lat": r["lat"], "lon": r["lon"],
                    "sust_mph": r["sknt"] * MPH_PER_KT if r.get("sknt") is not None else None,
                    "gust_mph": r["gust"] * MPH_PER_KT if r.get("gust") is not None else None,
                    "dir_deg": r.get("drct"), "pressure_mb": r.get("mslp"), "wave_ft": None,
                    "time": pd.to_datetime(r["utc_valid"]).tz_convert(None)})
    return pd.DataFrame(out, columns=COLUMNS)


def buoys(max_age_hours: int = 3) -> pd.DataFrame:
    try:
        lines = requests.get(NDBC_URL, headers=HEADERS, timeout=60).text.splitlines()
    except requests.RequestException:
        return pd.DataFrame(columns=COLUMNS)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max_age_hours)

    def num(v):
        return None if v == "MM" else float(v)

    out = []
    for line in lines:
        f = line.split()
        if line.startswith("#") or len(f) < 15:
            continue
        t = datetime(int(f[3]), int(f[4]), int(f[5]), int(f[6]), int(f[7]))
        wspd, gst = num(f[9]), num(f[10])
        if t < cutoff or (wspd is None and gst is None):
            continue
        wave = num(f[11])
        out.append({"id": f[0], "name": f"NOAA buoy/station {f[0]}", "kind": "buoy",
                    "lat": float(f[1]), "lon": float(f[2]),
                    "sust_mph": wspd * MPH_PER_MS if wspd is not None else None,
                    "gust_mph": gst * MPH_PER_MS if gst is not None else None,
                    "dir_deg": num(f[8]), "pressure_mb": num(f[15]),
                    "wave_ft": wave * FT_PER_M if wave is not None else None, "time": t})
    return pd.DataFrame(out, columns=COLUMNS)


def near(points: list[tuple[float, float]], radius_km: float = 700) -> pd.DataFrame:
    """Airport and buoy wind readings within radius_km of any of the given (lat, lon) points."""
    if not points:
        return pd.DataFrame(columns=COLUMNS)
    obs = pd.concat([airports(), buoys()], ignore_index=True)
    if obs.empty:
        return obs
    import numpy as np
    lat = np.radians(obs["lat"].to_numpy(float))
    lon = np.radians(obs["lon"].to_numpy(float))
    keep = np.zeros(len(obs), bool)
    for plat, plon in points:
        a, b = np.radians(plat), np.radians(plon)
        h = np.sin((lat - a) / 2) ** 2 + np.cos(lat) * np.cos(a) * np.sin((lon - b) / 2) ** 2
        keep |= 2 * 6371 * np.arcsin(np.sqrt(h)) <= radius_km
    obs = obs[keep].reset_index(drop=True)
    obs["suspect"] = obs.apply(_suspect, axis=1)
    return obs


def _suspect(r) -> str:
    """Real-time station data isn't quality-controlled. Flag readings that are physically implausible."""
    sust, p = r["sust_mph"], r["pressure_mb"]
    if pd.notna(sust) and sust >= 40 and pd.isna(r["dir_deg"]):
        return "no wind direction reported with a high speed, a common sign of a faulty sensor"
    if pd.notna(sust) and sust >= 60 and pd.notna(p) and p >= 1000:
        return "hurricane-strength wind with near-normal pressure is physically unlikely"
    return ""
