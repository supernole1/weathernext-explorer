"""Observed ("best track") cyclone positions from NOAA IBTrACS, used to verify forecasts."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
       "v04r01/access/csv/ibtracs.last3years.list.v04r01.csv")
CACHE = Path(__file__).resolve().parent.parent / "data" / "ibtracs_last3years.csv"
MAX_AGE_SECONDS = 12 * 3600


def _ensure_cached() -> Path:
    if not CACHE.exists() or time.time() - CACHE.stat().st_mtime > MAX_AGE_SECONDS:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(URL, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(CACHE, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    return CACHE


def load_storm(atcf_id: str) -> pd.DataFrame:
    """Observed track for an ATCF id like 'AL132025' (Weather Lab's track_id)."""
    cols = ["SID", "NAME", "ISO_TIME", "USA_ATCF_ID", "LAT", "LON", "USA_WIND", "USA_PRES",
            "WMO_WIND", "WMO_PRES"]
    # Row 2 of the file holds units, so skip it.
    df = pd.read_csv(_ensure_cached(), usecols=cols, skiprows=[1], low_memory=False,
                     keep_default_na=False, na_values=[" ", ""])
    df = df[df["USA_ATCF_ID"].str.upper() == atcf_id.upper()].copy()
    df["valid_time"] = pd.to_datetime(df["ISO_TIME"])
    for c in ["LAT", "LON", "USA_WIND", "USA_PRES", "WMO_WIND", "WMO_PRES"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["wind_kt"] = df["USA_WIND"].fillna(df["WMO_WIND"])
    df["mslp_hpa"] = df["USA_PRES"].fillna(df["WMO_PRES"])
    df = df.rename(columns={"LAT": "lat", "LON": "lon", "NAME": "name"})
    return df[["valid_time", "name", "lat", "lon", "wind_kt", "mslp_hpa"]].reset_index(drop=True)
