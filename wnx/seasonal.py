"""Seasonal (winter) outlook for one place: ECMWF SEAS5 ensemble, NOAA CPC 3-month outlooks, and ENSO status.

WeatherNext only forecasts ~15 days ahead, so seasons come from other sources:

- ECMWF's seasonal system (51 members, ~7 months) via Open-Meteo's free seasonal API. Monthly anomalies are
  relative to the model's own climate, which removes most model bias; each member's monthly value is compared
  with that same model climate to get the share of forecasts that run warmer/wetter than normal.
- NOAA Climate Prediction Center official 3-month outlooks (KML polygons, looked up at the point).
- CPC's ENSO (El Niño / La Niña) diagnostic discussion.
"""

from __future__ import annotations

import html as htmllib
import io
import json
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .forecast import HEADERS

SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
CPC_KMLS = "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/seaskmls_latest.zip"
CPC_MAP = "https://www.cpc.ncep.noaa.gov/products/predictions/long_range/lead{lead:02d}/off{lead:02d}_{var}.gif"
CPC_PAGE = "https://www.cpc.ncep.noaa.gov/products/predictions/long_range/seasonal.php?lead={lead}"
ENSO_URL = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"
CACHE = Path(__file__).resolve().parent.parent / "data" / "seasonal"
F_PER_K = 1.8
SEASON_MONTHS = {"DJF": "December–February", "NDJ": "November–January", "JFM": "January–March",
                 "OND": "October–December", "FMA": "February–April", "SON": "September–November",
                 "MAM": "March–May", "AMJ": "April–June", "MJJ": "May–July", "JJA": "June–August",
                 "JAS": "July–September", "ASO": "August–October"}


def _cached(name: str, max_age_hours: float, fetch) -> bytes:
    path = CACHE / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return path.read_bytes()
    data = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _get(params: dict) -> dict:
    r = requests.get(SEASONAL_URL, headers=HEADERS, timeout=120, params=params)
    body = r.json()
    if body.get("error"):
        raise RuntimeError(body.get("reason"))
    return body


# --- ECMWF seasonal ensemble -------------------------------------------------------------------------------

def ecmwf(lat: float, lon: float) -> pd.DataFrame:
    """One row per month: ensemble-mean temperature/high/low/rain, the model's normal for that month, and the
    share of the 51 forecasts warmer or wetter than normal. Months the daily members don't fully cover have
    NaN member statistics."""
    key = f"ecmwf_{lat:.2f}_{lon:.2f}.json"
    base = dict(latitude=lat, longitude=lon, temperature_unit="fahrenheit", precipitation_unit="inch")

    def fetch() -> bytes:
        monthly = _get({**base, "monthly": "temperature_2m_mean,temperature_2m_anomaly,"
                        "temperature_max24h_2m_mean,temperature_max24h_2m_anomaly,"
                        "temperature_min24h_2m_mean,temperature_min24h_2m_anomaly,"
                        "precipitation_mean,precipitation_anomaly"})
        daily = _get({**base, "daily": "temperature_2m_mean,precipitation_sum", "forecast_days": 215})
        return json.dumps({"monthly": monthly["monthly"], "daily": daily["daily"]}).encode()

    data = json.loads(_cached(key, 12, fetch))
    m = pd.DataFrame(data["monthly"])
    m["month"] = pd.to_datetime(m["time"]).dt.to_period("M")
    for col in ("temperature_2m", "temperature_max24h_2m", "temperature_min24h_2m"):
        m[f"{col}_anomaly"] = m[f"{col}_anomaly"] * F_PER_K          # API returns anomalies in K
        m[f"{col}_normal"] = m[f"{col}_mean"] - m[f"{col}_anomaly"]
    m["precipitation_normal"] = m["precipitation_mean"] - m["precipitation_anomaly"]

    d = pd.DataFrame(data["daily"])
    d["month"] = pd.to_datetime(d["time"]).dt.to_period("M")
    t_cols = [c for c in d if c.startswith("temperature_2m_mean")]
    p_cols = [c for c in d if c.startswith("precipitation_sum")]
    days_in = d.groupby("month")[t_cols].count().min(axis=1)
    full = days_in[days_in == days_in.index.days_in_month].index
    temp = d.groupby("month")[t_cols].mean().loc[lambda x: x.index.isin(full)]
    rain = d.groupby("month")[p_cols].sum(min_count=1).loc[lambda x: x.index.isin(full)]

    m = m.set_index("month")
    members_t = temp.sub(m["temperature_2m_normal"], axis=0).dropna(how="all")
    members_p = rain.sub(m["precipitation_normal"], axis=0).dropna(how="all")
    m["pct_warmer"] = (members_t > 0).mean(axis=1) * 100
    m["pct_wetter"] = (members_p > 0).mean(axis=1) * 100
    m.attrs["members_t"] = members_t
    m.attrs["members_p"] = members_p
    return m.reset_index()


def winter(m: pd.DataFrame) -> dict:
    """December–February averages from the monthly table."""
    w = m[m["month"].dt.month.isin([12, 1, 2])]
    mt, mp = m.attrs["members_t"], m.attrs["members_p"]
    wt = mt[mt.index.month.isin([12, 1, 2])]
    wp = mp[mp.index.month.isin([12, 1, 2])]
    return {"months": len(w), "temp_anom": w["temperature_2m_anomaly"].mean(),
            "rain_anom": w["precipitation_anomaly"].sum(), "rain_normal": w["precipitation_normal"].sum(),
            "pct_warmer": (wt.mean() > 0).mean() * 100 if len(wt) == 3 else np.nan,
            "pct_wetter": (wp.sum() > 0).mean() * 100 if len(wp) == 3 else np.nan}


# --- NOAA CPC 3-month outlooks -----------------------------------------------------------------------------

def _inside(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray casting; ring is [(lon, lat), ...]."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _ring(text: str) -> list[tuple[float, float]]:
    return [tuple(map(float, p.split(",")[:2])) for p in text.split()]


def _category(kml: str, lat: float, lon: float) -> tuple[str, int]:
    """('Above' | 'Below' | 'Near' | 'EC', probability %) of the outlook polygon containing the point."""
    hit = ("EC", 33)
    for pm in re.findall(r"<Placemark.*?</Placemark>", kml, re.S):
        cat = re.search(r"<td>Category</td>\s*<td>([^<]*)</td>", pm)
        prob = re.search(r"<td>Probability</td>\s*<td>([^<]*)</td>", pm)
        for poly in re.findall(r"<Polygon>.*?</Polygon>", pm, re.S):
            outer = re.search(r"<outerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", poly, re.S)
            if not outer or not _inside(lat, lon, _ring(outer.group(1))):
                continue
            holes = re.findall(r"<innerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", poly, re.S)
            if any(_inside(lat, lon, _ring(h)) for h in holes):
                continue
            c = (cat.group(1).strip() if cat else "EC").upper()
            label = {"A": "Above", "B": "Below", "N": "Near"}.get(c[:1], "EC") if c != "EC" else "EC"
            hit = (label, int(float(prob.group(1)))) if prob else (label, 33)
    return hit


def cpc_outlook(lat: float, lon: float) -> tuple[pd.DataFrame, str]:
    """NOAA's official outlook at the point for each upcoming 3-month season, plus the issue date."""
    z = zipfile.ZipFile(io.BytesIO(_cached("cpc_seaskmls.zip", 24, lambda: requests.get(
        CPC_KMLS, headers=HEADERS, timeout=120).content)))
    rows, created = [], ""
    for lead in range(1, 14):
        row = {"lead": lead}
        for var in ("temp", "prcp"):
            name = f"lead{lead}_{var}.kml"
            if name not in z.namelist():
                continue
            kml = z.read(name).decode("utf-8", errors="replace")
            m = re.search(r"Created: ([\d/]+) - Valid (\w{3}) (\d{4})", kml)
            if m:
                created, row["season"], row["year"] = m.group(1), m.group(2), int(m.group(3))
            row[f"{var}_cat"], row[f"{var}_prob"] = _category(kml, lat, lon)
        if "season" in row:
            rows.append(row)
    return pd.DataFrame(rows), created


# --- ENSO -----------------------------------------------------------------------------------------------

def enso() -> dict:
    """CPC's ENSO alert status and synopsis."""
    raw = _cached("ensodisc.html", 12, lambda: requests.get(ENSO_URL, headers=HEADERS, timeout=60).content)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace")))
    # The page's special characters arrive as replacement characters; restore the ones it uses.
    text = text.replace("Ni\ufffdo", "Niño").replace("Ni\ufffda", "Niña").replace("\ufffd", "°")
    text = re.sub(r"\s+", " ", text)
    pick = lambda pattern: (re.search(pattern, text) or [None, ""])[1].strip()
    return {"status": pick(r"ENSO Alert System Status:\s*(.*?)\s*Synopsis:"),
            "synopsis": pick(r"Synopsis:\s*(.*?\.)\s+[A-Z]"),
            "issued": pick(r"DIAGNOSTIC DISCUSSION issued by CLIMATE PREDICTION CENTER/NCEP/NWS (\d{1,2} \w+ \d{4})"),
            "next": pick(r"next ENSO Diagnostics Discussion is scheduled for (\d{1,2} \w+ \d{4})"),
            "url": ENSO_URL}
