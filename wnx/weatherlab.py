"""Download and parse tropical cyclone track forecasts from Google DeepMind Weather Lab.

Weather Lab publishes cyclone forecasts as public CSV files (no login needed):

    https://deepmind.google.com/science/weatherlab/download/cyclones/
        {MODEL}/{PRODUCT}/paired/csv/{MODEL}_{YYYY_MM_DD}T{HH}_00_paired.csv

PRODUCT is ``ensemble_mean`` (sample == -1) or ``ensemble`` (one row per member,
sample 0..N-1). Licensing: data about times > 48 h ago is CC BY 4.0; fresher data
falls under https://storage.googleapis.com/weathernext-public/terms-of-use.pdf
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://deepmind.google.com/science/weatherlab/download/cyclones"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "weatherlab"

# Model codes used in Weather Lab URLs, with first available init time.
MODELS = {
    "WNV3": ("WeatherNext 3 Cyclones (64 members)", datetime(2024, 1, 1)),
    "OPER": ("WeatherNext Cyclones operational (50 members)", datetime(2025, 6, 12)),
    "FNV3P2": ("WeatherNext 2 Cyclones r2", datetime(2022, 1, 1)),
    "FNV3P1": ("WeatherNext 2 Cyclones r1", datetime(2022, 1, 1)),
    "FNV3_LARGE_ENSEMBLE": ("WeatherNext 2 Cyclones, 1000 members", datetime(2025, 10, 18)),
}
PRODUCTS = ("ensemble_mean", "ensemble")


def url_for(model: str, product: str, init_time: datetime) -> str:
    stamp = init_time.strftime("%Y_%m_%dT%H_00")
    return f"{BASE_URL}/{model}/{product}/paired/csv/{model}_{stamp}_paired.csv"


def download(model: str, product: str, init_time: datetime, refresh: bool = False) -> Path | None:
    """Fetch one forecast file into the local cache. Returns None if it doesn't exist."""
    dest = DATA_DIR / model / product / Path(url_for(model, product, init_time)).name
    if dest.exists() and not refresh:
        return dest
    resp = requests.get(url_for(model, product, init_time), timeout=60,
                        headers={"User-Agent": "weathernext-explorer/0.1"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def parse(path: Path) -> pd.DataFrame:
    """Parse a Weather Lab CSV (skipping its '#' license header)."""
    text = path.read_text(encoding="utf-8")
    df = pd.read_csv(io.StringIO(text), comment="#")
    df["init_time"] = pd.to_datetime(path.stem.split("_", 1)[1][:13], format="%Y_%m_%dT%H")
    df["valid_time"] = pd.to_datetime(df["valid_time"])
    df = df.drop(columns=["lead_time"]).rename(columns={
        "minimum_sea_level_pressure_hpa": "mslp_hpa",
        "maximum_sustained_wind_speed_knots": "wind_kt",
    })
    return df


def load(model: str, init_time: datetime, product: str = "ensemble_mean",
         storm: str | None = None) -> pd.DataFrame:
    """Download (if needed) and load one forecast. Empty DataFrame if unavailable."""
    path = download(model, product, init_time)
    if path is None:
        return pd.DataFrame()
    df = parse(path)
    df["model"] = model
    if storm:
        df = df[df["track_id"] == storm.upper()]
    return df


def load_range(model: str, start: datetime, end: datetime, product: str = "ensemble_mean",
               storm: str | None = None, step_hours: int = 6) -> pd.DataFrame:
    """Load every init time from start to end (inclusive). Missing inits are skipped."""
    frames, t = [], start
    while t <= end:
        frames.append(load(model, t, product, storm))
        t += timedelta(hours=step_hours)
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def latest_init(model: str = "WNV3", lookback_hours: int = 72) -> datetime | None:
    """Most recent init time with a published file (files appear a few hours after init)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    t = now - timedelta(hours=now.hour % 6)
    for _ in range(lookback_hours // 6 + 1):
        if download(model, "ensemble_mean", t) is not None:
            return t
        t -= timedelta(hours=6)
    return None
