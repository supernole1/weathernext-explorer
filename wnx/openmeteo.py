"""Point forecasts from the WeatherNext ensemble via Open-Meteo (free, no key for non-commercial use).

As of Oct 2026 Open-Meteo serves WeatherNext 2 (0.25°, 6-hourly native, 15 days, 64 members),
not WeatherNext 3. WeatherNext 3 point data needs the Google Cloud access (see cloud.py).
"""

from __future__ import annotations

import pandas as pd
import requests

URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODEL = "google_weathernext2_ensemble"


def point_ensemble(lat: float, lon: float, variable: str = "wind_speed_10m",
                   days: int = 10, wind_unit: str = "kn") -> pd.DataFrame:
    """Long table: time, member, value. Member 0 is the control."""
    params = dict(latitude=lat, longitude=lon, hourly=variable, forecast_days=days,
                  models=MODEL, wind_speed_unit=wind_unit, temporal_resolution="native")
    resp = requests.get(URL, params=params, timeout=60)
    resp.raise_for_status()
    hourly = resp.json()["hourly"]
    df = pd.DataFrame(hourly).melt(id_vars="time", var_name="column", value_name="value")
    df["member"] = df["column"].str.extract(r"member(\d+)$").fillna(0).astype(int)
    df["time"] = pd.to_datetime(df["time"])
    return df[["time", "member", "value"]].dropna()
