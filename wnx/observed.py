"""Observed storm track: NHC's real-time best track when available, else NOAA IBTrACS.

NHC's ATCF best-track file ("b-deck") is updated with every advisory, so it is current to within ~6 hours.
It covers storms NHC tracks (Atlantic, East and Central Pacific). IBTrACS covers every basin but runs about
a day behind. Both are public domain.
"""

from __future__ import annotations

import pandas as pd
import requests

from . import ibtracs

BDECK_URL = "https://ftp.nhc.noaa.gov/atcf/btk/b{basin}{num}{year}.dat"
NHC_BASINS = {"AL": "al", "EP": "ep", "CP": "cp"}


def _coord(text: str) -> float:
    """ATCF '258N' -> 25.8, '884W' -> -88.4"""
    value = int(text[:-1]) / 10
    return -value if text[-1] in "SW" else value


def nhc_best_track(atcf_id: str) -> pd.DataFrame:
    basin, num, year = atcf_id[:2].upper(), atcf_id[2:4], atcf_id[4:]
    if basin not in NHC_BASINS:
        return pd.DataFrame()
    try:
        resp = requests.get(BDECK_URL.format(basin=NHC_BASINS[basin], num=num, year=year), timeout=30,
                            headers={"User-Agent": "weathernext-explorer/0.1"})
    except requests.RequestException:
        return pd.DataFrame()
    if resp.status_code != 200:
        return pd.DataFrame()
    rows = []
    for line in resp.text.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 10 or f[4] != "BEST":
            continue
        rows.append({"valid_time": pd.to_datetime(f[2], format="%Y%m%d%H"),
                     "name": f[27].title() if len(f) > 27 else "",
                     "lat": _coord(f[6]), "lon": _coord(f[7]),
                     "wind_kt": float(f[8]) if f[8] else None,
                     "mslp_hpa": float(f[9]) if f[9] and f[9] != "0" else None})
    # One row per wind-radii threshold (34/50/64 kt) at each time; keep one per time.
    df = pd.DataFrame(rows).drop_duplicates("valid_time", keep="last") if rows else pd.DataFrame()
    return df.reset_index(drop=True)


def load_storm(atcf_id: str) -> pd.DataFrame:
    """Observed track with df.attrs['source'] set to a short label for legends."""
    df = nhc_best_track(atcf_id)
    if not df.empty:
        df.attrs["source"] = "NHC best track"
        return df
    df = ibtracs.load_storm(atcf_id)
    df.attrs["source"] = "IBTrACS"
    return df
