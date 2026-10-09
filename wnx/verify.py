"""Forecast verification: track and intensity error versus observed best track."""

from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0
KM_PER_NMI = 1.852


def great_circle_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def pair_with_obs(forecast: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """Join forecast points to observations at the same valid time and compute errors."""
    merged = forecast.merge(obs[["valid_time", "lat", "lon", "wind_kt", "mslp_hpa"]],
                            on="valid_time", suffixes=("", "_obs"))
    merged["track_error_km"] = great_circle_km(merged["lat"], merged["lon"],
                                               merged["lat_obs"], merged["lon_obs"])
    merged["wind_error_kt"] = merged["wind_kt"] - merged["wind_kt_obs"]
    merged["mslp_error_hpa"] = merged["mslp_hpa"] - merged["mslp_hpa_obs"]
    return merged


def error_by_lead(paired: pd.DataFrame, max_lead: int = 120) -> pd.DataFrame:
    """Mean errors per model and lead time (hours), plus the number of cases."""
    p = paired[paired["lead_time_hours"] <= max_lead]
    return (p.groupby(["model", "lead_time_hours"])
             .agg(track_error_km=("track_error_km", "mean"),
                  wind_mae_kt=("wind_error_kt", lambda s: s.abs().mean()),
                  wind_bias_kt=("wind_error_kt", "mean"),
                  cases=("track_error_km", "size"))
             .reset_index())
