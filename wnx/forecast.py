"""Local forecast for one place from the 64-member WeatherNext 2 ensemble (via Open-Meteo).

Every quantity is summarized across members: the median is the "most likely" value and the 10th-90th
percentile range is the spread of plausible outcomes. Rain chance is simply the share of members that
produce measurable rain. Native model steps are 6-hourly (0.25°, ~25 km); Open-Meteo interpolates to hourly.
"""

from __future__ import annotations

import pandas as pd
import requests

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ZIP_URL = "https://api.zippopotam.us/us/{zip}"
MODEL = "google_weathernext2_ensemble"
VARIABLES = ["temperature_2m", "precipitation", "wind_speed_10m", "wind_direction_10m",
             "relative_humidity_2m", "cloud_cover"]
RAIN_IN = 0.01   # measurable rain, inches
HEADERS = {"User-Agent": "weathernext-explorer/0.1"}


def geocode_zip(zip_code: str) -> dict:
    resp = requests.get(ZIP_URL.format(zip=zip_code), headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"ZIP {zip_code} not found")
    p = resp.json()["places"][0]
    return {"zip": zip_code, "lat": float(p["latitude"]), "lon": float(p["longitude"]),
            "place": f"{p['place name']}, {p['state abbreviation']}"}


def ensemble(lat: float, lon: float, days: int = 16) -> tuple[pd.DataFrame, str]:
    """Long table (time, member, variable columns) in local time, plus the time zone name."""
    resp = requests.get(ENSEMBLE_URL, headers=HEADERS, timeout=60, params=dict(
        latitude=lat, longitude=lon, hourly=",".join(VARIABLES), models=MODEL, forecast_days=days,
        temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch", timezone="auto"))
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(data.get("reason"))
    hourly = data["hourly"]
    frames = []
    for var in VARIABLES:
        cols = {k: v for k, v in hourly.items() if k == var or k.startswith(var + "_member")}
        wide = pd.DataFrame(cols, index=pd.to_datetime(hourly["time"]))
        wide.columns = [0 if c == var else int(c.rsplit("member", 1)[1]) for c in wide.columns]
        frames.append(wide.stack().rename(var))
    df = pd.concat(frames, axis=1).reset_index()
    df.columns = ["time", "member"] + VARIABLES
    return df.dropna(subset=["temperature_2m"]), data.get("timezone", "")


def hourly_bands(df: pd.DataFrame, var: str) -> pd.DataFrame:
    """Per hour: 10th, 50th, 90th percentile across members."""
    q = df.groupby("time")[var].quantile([0.1, 0.5, 0.9]).unstack()
    q.columns = ["p10", "p50", "p90"]
    return q.reset_index()


def upcoming(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Only hours from now on (local time), so 'today' covers the rest of today."""
    return df[df["time"] >= now.floor("h")]


def daily(df: pd.DataFrame) -> pd.DataFrame:
    """Per day: high/low (median + 10-90% range), rain chance and amounts, wind, humidity, clouds."""
    d = df.assign(date=df["time"].dt.date)
    per_member = d.groupby(["date", "member"]).agg(
        high=("temperature_2m", "max"), low=("temperature_2m", "min"), rain=("precipitation", "sum"),
        wind=("wind_speed_10m", "max"), humidity=("relative_humidity_2m", "mean"),
        clouds=("cloud_cover", "mean"), hours=("time", "size"))
    out = per_member.groupby("date").agg(
        high=("high", "median"), high_lo=("high", lambda s: s.quantile(0.1)), high_hi=("high", lambda s: s.quantile(0.9)),
        low=("low", "median"), low_lo=("low", lambda s: s.quantile(0.1)), low_hi=("low", lambda s: s.quantile(0.9)),
        rain_chance=("rain", lambda s: (s >= RAIN_IN).mean() * 100),
        rain_median=("rain", "median"), rain_hi=("rain", lambda s: s.quantile(0.9)),
        wind=("wind", "median"), wind_hi=("wind", lambda s: s.quantile(0.9)),
        humidity=("humidity", "median"), clouds=("clouds", "median"), hours=("hours", "max"))
    out = out.reset_index()
    # Keep a partial first day ("rest of today") if a few hours remain; drop a truncated last day.
    keep = (out["hours"] >= 18) | ((out.index == 0) & (out["hours"] >= 3))
    out = out[keep].reset_index(drop=True)
    out["partial"] = out["hours"] < 18
    return out


def sky(clouds: float, rain_chance: float) -> str:
    if rain_chance >= 60:
        return "Rain likely"
    if rain_chance >= 30:
        return "Chance of rain"
    if clouds >= 75:
        return "Cloudy"
    if clouds >= 40:
        return "Partly cloudy"
    return "Mostly sunny"
