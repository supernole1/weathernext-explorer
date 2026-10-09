"""Official National Hurricane Center forecast: cone, track, and coastal watches/warnings.

Covers storms NHC is responsible for (Atlantic, East and Central Pacific). Pulled fresh on each run from
https://www.nhc.noaa.gov/CurrentStorms.json and the KMZ files it links to. Public domain, no key.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
HEADERS = {"User-Agent": "weathernext-explorer/0.1"}
UTC_OFFSETS = {"AST": -4, "EDT": -4, "EST": -5, "CDT": -5, "CST": -6, "MDT": -6, "MST": -7,
               "PDT": -7, "PST": -8, "HST": -10, "UTC": 0, "GMT": 0}


@dataclass
class TrackPoint:
    lat: float
    lon: float
    label: str                      # e.g. "12 hr Forecast"
    valid_time: datetime | None     # UTC
    wind_kt: float | None


@dataclass
class OfficialForecast:
    atcf_id: str
    name: str
    classification: str             # HU, TS, TD, ...
    advisory: str
    issued: datetime                # UTC
    current_lat: float
    current_lon: float
    current_wind_kt: float
    current_mslp_hpa: float
    cone: list[list[float]] = field(default_factory=list)              # [[lat, lon], ...]
    track: list[TrackPoint] = field(default_factory=list)
    warnings: list[tuple[str, list[list[float]]]] = field(default_factory=list)  # (type, [[lat, lon]])


def _kml(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        name = next(n for n in z.namelist() if n.endswith(".kml"))
        return z.read(name).decode("utf-8", errors="replace")


def _coords(text: str) -> list[list[float]]:
    """KML 'lon,lat,alt lon,lat,alt' -> [[lat, lon], ...]"""
    pts = []
    for triple in text.split():
        lon, lat = triple.split(",")[:2]
        pts.append([float(lat), float(lon)])
    return pts


def _parse_valid(text: str) -> datetime | None:
    m = re.search(r"Valid at:\s*(\d{1,2}:\d{2} [AP]M) (\w+) (\w+ \d{1,2}, \d{4})", text)
    if not m or m.group(2) not in UTC_OFFSETS:
        return None
    local = datetime.strptime(f"{m.group(1)} {m.group(3)}", "%I:%M %p %B %d, %Y")
    return local - timedelta(hours=UTC_OFFSETS[m.group(2)])


def official_forecast(atcf_id: str) -> OfficialForecast | None:
    """Latest NHC advisory for a storm, or None if NHC isn't currently tracking it."""
    try:
        storms = requests.get(CURRENT_STORMS_URL, headers=HEADERS, timeout=30).json()["activeStorms"]
    except (requests.RequestException, ValueError, KeyError):
        return None
    s = next((s for s in storms if s["id"].upper() == atcf_id.upper()), None)
    if s is None:
        return None

    fc = OfficialForecast(
        atcf_id=s["id"].upper(), name=s["name"], classification=s["classification"],
        advisory=s["publicAdvisory"]["advNum"].upper(),
        issued=datetime.fromisoformat(s["lastUpdate"].replace("Z", "")),
        current_lat=s["latitudeNumeric"], current_lon=s["longitudeNumeric"],
        current_wind_kt=float(s["intensity"]), current_mslp_hpa=float(s["pressure"]))

    try:
        if s.get("trackCone"):
            kml = _kml(s["trackCone"]["kmzFile"])
            m = re.search(r"<Polygon>.*?<coordinates>(.*?)</coordinates>", kml, re.S)
            if m:
                fc.cone = _coords(m.group(1))
        if s.get("forecastTrack"):
            kml = _kml(s["forecastTrack"]["kmzFile"])
            for pm in re.findall(r"<Placemark>.*?</Placemark>", kml, re.S):
                pt = re.search(r"<Point>\s*<coordinates>(.*?)</coordinates>", pm, re.S)
                if not pt:
                    continue
                lat, lon = _coords(pt.group(1))[0]
                label = re.search(r"<td nowrap>([^<]*(?:Forecast|Advisory Information)[^<]*)</td>", pm)
                wind = re.search(r"Maximum Wind:\s*(\d+) knots", pm)
                fc.track.append(TrackPoint(
                    lat, lon, (label.group(1).strip() if label else "").replace("Advisory Information", "Now"),
                    _parse_valid(pm), float(wind.group(1)) if wind else None))
        if s.get("windWatchesWarnings"):
            kml = _kml(s["windWatchesWarnings"]["kmzFile"])
            for pm in re.findall(r"<Placemark>.*?</Placemark>", kml, re.S):
                name = re.search(r"<name>(.*?)</name>", pm)
                for c in re.findall(r"<coordinates>(.*?)</coordinates>", pm, re.S):
                    fc.warnings.append((name.group(1) if name else "Warning", _coords(c)))
    except (requests.RequestException, zipfile.BadZipFile, StopIteration, ValueError):
        pass  # show whatever pieces we did get
    return fc
