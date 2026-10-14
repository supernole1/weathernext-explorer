"""This season's storms in NHC's basins (Atlantic, East and Central Pacific), from NHC's best-track files.

Used for the storm list (viewer option L and outputs/storm_list.html), so finished storms can be picked by name.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from . import weatherlab
from .forecast import HEADERS

BTK_DIR = "https://ftp.nhc.noaa.gov/atcf/btk/"
CACHE = Path(__file__).resolve().parent.parent / "data" / "season"
BASINS = {"AL": "Atlantic", "EP": "East Pacific", "CP": "Central Pacific"}
MPH_PER_KT = 1.15078


def category(kt: float) -> str:
    """Peak strength in words (Saffir-Simpson for hurricanes)."""
    if kt >= 137: return "Category 5 hurricane"
    if kt >= 113: return "Category 4 hurricane"
    if kt >= 96: return "Category 3 hurricane"
    if kt >= 83: return "Category 2 hurricane"
    if kt >= 64: return "Category 1 hurricane"
    if kt >= 34: return "Tropical storm"
    return "Tropical depression"


def _parse(storm_id: str, text: str) -> dict | None:
    rows = [[f.strip() for f in line.split(",")] for line in text.splitlines() if line.count(",") > 10]
    if not rows:
        return None
    times = [datetime.strptime(r[2], "%Y%m%d%H") for r in rows]
    winds = [float(r[8]) for r in rows if r[8]]
    names = [r[27] for r in rows if len(r) > 27 and r[27]]
    name = next((n for n in reversed(names) if n not in ("INVEST", "GENESIS")), names[-1] if names else "")
    return {"id": storm_id, "name": name.title(), "basin": BASINS[storm_id[:2]],
            "first": min(times).isoformat(), "last": max(times).isoformat(), "peak_kt": max(winds, default=0)}


def storms(year: int | None = None, max_age_hours: float = 3) -> pd.DataFrame:
    """One row per storm this season (invests excluded), newest first. Cached for a few hours."""
    year = year or datetime.now(timezone.utc).year
    path = CACHE / f"storms_{year}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        rows = json.loads(path.read_text())
    else:
        listing = requests.get(BTK_DIR, headers=HEADERS, timeout=30).text
        ids = sorted({m.upper() for m in re.findall(rf"b((?:al|ep|cp)[0-8]\d{year})\.dat", listing)})
        rows = []
        for sid in ids:
            r = requests.get(f"{BTK_DIR}b{sid.lower()}.dat", headers=HEADERS, timeout=30)
            if r.ok and (row := _parse(sid, r.text)):
                rows.append(row)
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["first"], df["last"] = pd.to_datetime(df["first"]), pd.to_datetime(df["last"])
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    df["active"] = df["last"] > now - pd.Timedelta(hours=12)
    df["strength"] = df["peak_kt"].map(category)
    df["peak_mph"] = (df["peak_kt"] * MPH_PER_KT).round(-1).astype(int)   # NHC rounds mph to 5s; tens reads fine
    df["forecasts"] = [_has_forecasts(r) for r in df.to_dict("records")]
    return df.sort_values("first", ascending=False).reset_index(drop=True)


def _has_forecasts(r: dict) -> bool:
    """Did Weather Lab publish WeatherNext 3 tracks under this storm's ID? Checks a few runs across its life.
    Answers for finished storms are cached for good; active storms are always treated as covered."""
    if r["active"]:
        return True
    path = CACHE / "coverage.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    if r["id"] in known:
        return known[r["id"]]
    first, last = r["first"], r["last"]
    found = False
    for frac in (0.5, 0.25, 0.75):
        t = (first + (last - first) * frac).floor("6h").to_pydatetime()
        if not weatherlab.load("WNV3", t, storm=r["id"]).empty:
            found = True
            break
    known[r["id"]] = found
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known))
    return found


def dates(r) -> str:
    a, b = r["first"], r["last"]
    return f"{a:%b} {a.day}–{b.day}" if a.month == b.month else f"{a:%b} {a.day}–{b:%b} {b.day}"
