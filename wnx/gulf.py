"""15-day tropical outlook for the Gulf of America and NW Caribbean from the 64-member WeatherNext 2 ensemble.

Weather Lab only publishes cyclone tracks for storms that already exist (or that NHC is tracking as an invest),
so storms that haven't formed yet need the raw weather fields. Open-Meteo serves those at points, so we sample
sea-level pressure and 10 m wind on a 1.5° grid of water points and, in each of the 64 forecasts, look for a
closed low with strong winds near its center: a "storm signal". The share of forecasts that produce one is the
chance of development.

This is a simple screening method, not NHC's genesis forecast: the 1.5° grid can miss small storms and
underestimate peak winds, and an October cold front can occasionally produce a low that looks tropical.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .forecast import ENSEMBLE_URL, HEADERS, MODEL
from .nhc import _coords, _kml

CACHE = Path(__file__).resolve().parent.parent / "data" / "gulf"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
STEP = 1.5
LATS = np.round(np.arange(15.0, 30.01, STEP), 2)
LONS = np.round(np.arange(-98.0, -78.49, STEP), 2)
DAYS = 15
BATCH = 25                 # points per request; Open-Meteo's free tier allows ~600 weighted calls a minute

LOW_MAX_HPA = 1009         # a candidate low's center pressure
DEPTH_HPA = 2.0            # center at least this far below the ring ~300 km out (a closed low, not a trough)
TS_MPH, TS_HPA = 39, 1006  # tropical-storm-strength signal
TD_MPH = 25                # weaker "tropical low" signal
LINK_DEG = 4.0             # max jump between 6-hourly positions of the same system


def region(lat: float, lon: float) -> str:
    if lat < 21.8 and lon > -88.5:
        return "NW Caribbean"
    if lat < 22.5 and lon < -90:
        return "Bay of Campeche"
    if lon < -92:
        return "western Gulf"
    if lon < -87:
        return "central Gulf"
    return "eastern Gulf"


def in_domain(lat: float, lon: float) -> bool:
    """Gulf + NW Caribbean water. Leaves out the Pacific south of Mexico and the Atlantic east of Florida."""
    if lat < 18.2 and lon < -88.2:
        return False
    if lat >= 23 and lon >= -80:
        return False
    return True


def _water_points() -> list[tuple[float, float]]:
    """Grid points over water (elevation 0), looked up once and cached."""
    path = CACHE / "water_points.json"
    if path.exists():
        return [tuple(p) for p in json.loads(path.read_text())]
    pts = [(la, lo) for la in LATS for lo in LONS if in_domain(la, lo)]
    elev = []
    for i in range(0, len(pts), 100):
        chunk = pts[i:i + 100]
        r = requests.get(ELEVATION_URL, headers=HEADERS, timeout=60, params=dict(
            latitude=",".join(str(p[0]) for p in chunk), longitude=",".join(str(p[1]) for p in chunk)))
        r.raise_for_status()
        elev += r.json()["elevation"]
    water = [list(map(float, p)) for p, e in zip(pts, elev) if e <= 0]
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(water))
    return [tuple(p) for p in water]


def _get(params: dict) -> list:
    for attempt in range(6):
        r = requests.get(ENSEMBLE_URL, headers=HEADERS, timeout=180, params=params)
        body = r.json()
        if isinstance(body, dict) and body.get("error"):
            if "limit" in body.get("reason", "").lower() and attempt < 5:
                print("  waiting a minute for Open-Meteo's rate limit...", flush=True)
                time.sleep(62)
                continue
            raise RuntimeError(body.get("reason"))
        return body if isinstance(body, list) else [body]
    raise RuntimeError("Open-Meteo rate limit")


def fetch(max_age_hours: float = 3) -> dict:
    """Pressure and wind for every member at every water point, 6-hourly. Cached for a few hours, since the
    model only updates a few times a day and the free API has a daily limit."""
    path = CACHE / "fields.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return json.loads(path.read_text())
    pts = _water_points()
    out = {"points": [], "time": None, "pressure": [], "wind": [],
           "fetched": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    for i in range(0, len(pts), BATCH):
        chunk = pts[i:i + BATCH]
        print(f"  downloading grid points {i + 1}-{i + len(chunk)} of {len(pts)}...", flush=True)
        res = _get(dict(latitude=",".join(str(p[0]) for p in chunk),
                        longitude=",".join(str(p[1]) for p in chunk),
                        hourly="pressure_msl,wind_speed_10m", models=MODEL, forecast_days=DAYS,
                        wind_speed_unit="mph", temporal_resolution="hourly_6"))
        for p, loc in zip(chunk, res):
            h = loc["hourly"]
            out["time"] = out["time"] or h["time"]
            out["points"].append(p)
            for var, key in (("pressure_msl", "pressure"), ("wind_speed_10m", "wind")):
                cols = [var] + sorted(k for k in h if k.startswith(var + "_member"))
                out[key].append([h[c] for c in cols])        # [member][time]
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def _grids(data: dict) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """-> pressure, wind as [member, time, lat, lon] arrays (NaN over land), and the valid times (UTC)."""
    times = pd.to_datetime(data["time"])
    n_mem = len(data["pressure"][0])
    P = np.full((n_mem, len(times), len(LATS), len(LONS)), np.nan)
    W = np.full_like(P, np.nan)
    for (la, lo), p, w in zip(data["points"], data["pressure"], data["wind"]):
        i, j = int(round((la - LATS[0]) / STEP)), int(round((lo - LONS[0]) / STEP))
        P[:, :, i, j] = np.array(p, dtype=float)
        W[:, :, i, j] = np.array(w, dtype=float)
    return P, W, times


def _lows(P: np.ndarray, W: np.ndarray) -> list[tuple[int, int, float, float]]:
    """Closed lows in one member/time field: (i, j, center pressure, max wind within ~1.5°)."""
    found = []
    ni, nj = P.shape
    for i in range(ni):
        for j in range(nj):
            c = P[i, j]
            if not np.isfinite(c) or c > LOW_MAX_HPA:
                continue
            near = P[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]
            if np.sum(np.isfinite(near)) < 6 or c > np.nanmin(near):
                continue
            ring = [P[a, b] for a in range(i - 2, i + 3) for b in range(j - 2, j + 3)
                    if 0 <= a < ni and 0 <= b < nj and max(abs(a - i), abs(b - j)) == 2]
            ring = [x for x in ring if np.isfinite(x)]
            if len(ring) < 6 or np.mean(ring) - c < DEPTH_HPA:
                continue
            di, dj = _vertex(P, i, j, 1, 0), _vertex(P, i, j, 0, 1)
            found.append((i + di, j + dj, float(c), float(np.nanmax(W[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]))))
    return found


def _vertex(P: np.ndarray, i: int, j: int, a: int, b: int) -> float:
    """Sub-grid offset of the low's center along one axis, from a parabola through the three grid values."""
    try:
        lo, c, hi = P[i - a, j - b], P[i, j], P[i + a, j + b]
    except IndexError:
        return 0.0
    if i - a < 0 or j - b < 0 or not np.isfinite([lo, c, hi]).all() or lo - 2 * c + hi <= 0:
        return 0.0
    return float(np.clip((lo - hi) / (2 * (lo - 2 * c + hi)), -0.5, 0.5))


def detect(data: dict) -> tuple[pd.DataFrame, pd.DatetimeIndex, int]:
    """Track lows through each member's forecast. Returns one row per (member, system, time), the forecast
    times, and the member count. Columns: member, system, time, lat, lon, pressure, wind_mph, strength."""
    P, W, times = _grids(data)
    rows = []
    for m in range(P.shape[0]):
        open_tracks: list[dict] = []
        next_id = 0
        for t in range(len(times)):
            lows = _lows(P[m, t], W[m, t])
            still_open = []
            for i, j, p, w in sorted(lows, key=lambda x: x[2]):
                lat, lon = round(LATS[0] + i * STEP, 2), round(LONS[0] + j * STEP, 2)
                best = min(open_tracks, key=lambda tr: np.hypot(tr["lat"] - lat, tr["lon"] - lon), default=None)
                if best and best["t"] == t - 1 and np.hypot(best["lat"] - lat, best["lon"] - lon) <= LINK_DEG:
                    open_tracks.remove(best)
                    sid = best["id"]
                else:
                    sid, next_id = next_id, next_id + 1
                still_open.append({"id": sid, "lat": lat, "lon": lon, "t": t})
                rows.append((m, sid, times[t], lat, lon, p, w))
            open_tracks = still_open
    df = pd.DataFrame(rows, columns=["member", "system", "time", "lat", "lon", "pressure", "wind_mph"])
    if df.empty:
        return df.assign(strength=pd.Series(dtype=str)), times, P.shape[0]
    df["strength"] = np.select([(df["wind_mph"] >= TS_MPH) & (df["pressure"] <= TS_HPA),
                                df["wind_mph"] >= TD_MPH], ["storm", "low"], "weak")
    # A system counts only if it holds a signal for at least 12 hours (two 6-hourly steps).
    df["region"] = [region(a, b) for a, b in zip(df["lat"], df["lon"])]
    key = ["member", "system"]
    n_storm = df["strength"].eq("storm").groupby([df[k] for k in key]).transform("sum")
    n_low = df["strength"].isin(["storm", "low"]).groupby([df[k] for k in key]).transform("sum")
    df["peak"] = np.select([n_storm >= 2, n_low >= 2], ["storm", "low"], "none")
    df = df[df["peak"] != "none"].reset_index(drop=True)
    return df, times, P.shape[0]


def summary(df: pd.DataFrame, n_members: int, start: pd.Timestamp, gulf_only: bool = False) -> dict:
    """Chance (% of members) of a storm signal in the next 7 and 15 days, and when/where they form."""
    s = df[df["strength"] == "storm"]
    if gulf_only:
        s = s[s["region"] != "NW Caribbean"]
    first = s.sort_values("time").groupby(["member"]).head(1)
    pct = lambda d: 100 * d["member"].nunique() / n_members
    return {"pct_15": pct(s), "pct_7": pct(s[s["time"] < start + timedelta(days=7)]),
            "first": first, "regions": first["region"].value_counts()}


def daily_chance(df: pd.DataFrame, n_members: int, tz: str = "America/Chicago") -> pd.DataFrame:
    """Per local day: % of members with a storm signal, and with any tropical-low signal, that day."""
    d = df.assign(date=df["time"].dt.tz_localize("UTC").dt.tz_convert(tz).dt.date)
    days = sorted(d["date"].unique()) if not d.empty else []
    storm = d[d["strength"] == "storm"].groupby("date")["member"].nunique()
    low = d[d["strength"].isin(["storm", "low"])].groupby("date")["member"].nunique()
    out = pd.DataFrame({"date": days})
    out["storm_pct"] = [100 * storm.get(x, 0) / n_members for x in days]
    out["low_pct"] = [100 * low.get(x, 0) / n_members for x in days]
    return out


GTWO_KMZ = "https://www.nhc.noaa.gov/xgtwo/gtwo_atl.kmz"
TWO_URL = "https://www.nhc.noaa.gov/text/MIATWOAT.shtml"
NHC_AREA_COLORS = {"Low": "#f2c200", "Medium": "#eb8c00", "High": "#d00000"}


def nhc_outlook() -> dict:
    """NHC's Tropical Weather Outlook: issue time, active-systems note, and each outlined area with its
    2- and 7-day formation chances and polygon. Empty areas list when nothing is outlined."""
    out = {"issued": "", "areas": [], "active": "", "url": "https://www.nhc.noaa.gov/gtwo.php?basin=atlc"}
    try:
        html = requests.get(TWO_URL, headers=HEADERS, timeout=30).text
        m = re.search(r"\n(\d{3,4} [AP]M \w{3} \w{3} \w{3} \d{1,2} \d{4})\n", html)
        out["issued"] = m.group(1) if m else ""
        m = re.search(r"Active Systems:\s*(.*?)\n\s*\n", html, re.S)
        out["active"] = " ".join(m.group(1).split()) if m else ""
    except requests.RequestException:
        pass
    try:
        kml = _kml(GTWO_KMZ)
    except Exception:
        return out
    for pm in re.findall(r"<Placemark>.*?</Placemark>", kml, re.S):
        if "<Polygon>" not in pm:
            continue
        data = dict(re.findall(r'<Data name="([^"]+)">\s*<value>(.*?)</value>', pm, re.S))
        ring = re.search(r"<coordinates>(.*?)</coordinates>", pm, re.S)
        discussion = " ".join(data.get("Discussion", "").split())
        out["areas"].append({
            "number": data.get("Disturbance", ""), "pct_2": data.get("2day_percentage", ""),
            "pct_7": data.get("7day_percentage", ""), "category": data.get("7day_category", "Low"),
            "title": discussion.split(":")[0].lstrip("0123456789. ") if ":" in discussion else "",
            "discussion": discussion, "polygon": _coords(ring.group(1)) if ring else []})
    return out


def area_in_domain(area: dict) -> bool:
    pts = area["polygon"]
    return any(15 <= la <= 31 and -99 <= lo <= -78 for la, lo in pts) if pts else False
