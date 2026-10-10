"""Official National Hurricane Center forecast: cone, track, and coastal watches/warnings.

Covers storms NHC is responsible for (Atlantic, East and Central Pacific). Pulled fresh on each run from
https://www.nhc.noaa.gov/CurrentStorms.json and the KMZ files it links to. Public domain, no key.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
    conditions: Conditions | None = None   # from the latest public advisory text
    # Wind field: (threshold kt 34/50/64, polygon [[lat, lon], ...]) now and over the forecast,
    # plus NHC's earliest reasonable arrival time of 39+ mph winds: (label like "Sat 2 am", line).
    wind_now: list[tuple[int, list[list[float]]]] = field(default_factory=list)
    wind_forecast: list[tuple[int, list[list[float]]]] = field(default_factory=list)
    arrival_34kt: list[tuple[str, list[list[float]]]] = field(default_factory=list)
    arrival_tz: str = ""


@dataclass
class Conditions:
    """The 'SUMMARY ... INFORMATION' block of NHC's public advisory, in NHC's own words."""
    title: str                      # e.g. "Hurricane Isaias Advisory Number 12"
    issued_text: str                # e.g. "1000 AM CDT Fri Oct 09 2026"
    url: str
    headlines: list[str] = field(default_factory=list)   # "CENTER OF ISAIAS EXPECTED TO REACH..."
    location: str = ""              # "27.7N 87.3W"
    distances: list[str] = field(default_factory=list)   # "About 195 mi S of Pensacola Florida"
    wind_mph: int | None = None
    movement: str = ""              # "NNE at 16 mph"
    pressure_mb: int | None = None
    watches_warnings: list[tuple[str, list[str]]] = field(default_factory=list)  # (type, [areas])
    next_advisories: list[str] = field(default_factory=list)  # "Next intermediate advisory at 100 PM CDT."


SMALL_WORDS = {"of", "the", "and", "to", "at", "in", "on", "for", "a"}


def _title(text: str) -> str:
    words = text.lower().split()
    return " ".join(w if w in SMALL_WORDS else w[:1].upper() + w[1:] for w in words)


def _parse_advisory(text: str, url: str) -> Conditions | None:
    lines = [l.rstrip() for l in text.splitlines()]
    title = next((l.strip() for l in lines if re.search(r"Advisory Number", l)), "")
    if not title:
        return None
    i = next(i for i, l in enumerate(lines) if l.strip() == title)
    c = Conditions(title=re.sub(r"\s+", " ", title), issued_text=lines[i + 2].strip() if i + 2 < len(lines) else "",
                   url=url)

    head, j = [], i + 3
    while j < len(lines) and not lines[j].startswith("SUMMARY OF"):
        if lines[j].strip():
            head.append(lines[j].strip())
        j += 1
    # Headlines are "...TEXT..." blocks that may wrap across lines.
    c.headlines = [h.strip(". ") for h in re.split(r"\.\.\.\s*\.\.\.", " ".join(head)) if h.strip(". ")]

    for l in lines[j:]:
        if l.startswith("WATCHES AND WARNINGS") or l.startswith("DISCUSSION AND OUTLOOK"):
            break
        if m := re.match(r"LOCATION\.\.\.(.+)", l):
            c.location = m.group(1).strip()
        elif m := re.match(r"ABOUT (\d+) MI\.\.\.\d+ KM (\w+) OF (.+)", l):
            c.distances.append(f"About {m.group(1)} mi {m.group(2)} of {_title(m.group(3))}")
        elif m := re.match(r"MAXIMUM SUSTAINED WINDS\.\.\.(\d+) MPH", l):
            c.wind_mph = int(m.group(1))
        elif m := re.match(r"PRESENT MOVEMENT\.\.\.(\w+) OR \d+ DEGREES AT (\d+) MPH", l):
            c.movement = f"{m.group(1)} at {m.group(2)} mph"
        elif m := re.match(r"PRESENT MOVEMENT\.\.\.(.+?)(?:\.\.\.|$)", l):
            c.movement = m.group(1).strip().capitalize()   # e.g. "Stationary"
        elif m := re.match(r"MINIMUM CENTRAL PRESSURE\.\.\.(\d+) MB", l):
            c.pressure_mb = int(m.group(1))

    # "A Hurricane Warning is in effect for..." followed by "* area" bullet lines.
    in_summary, current = False, None
    for l in lines:
        s = l.strip()
        if s.startswith("SUMMARY OF WATCHES AND WARNINGS IN EFFECT"):
            in_summary = True
        elif in_summary and (s.startswith("For storm information") or s.startswith("DISCUSSION AND OUTLOOK")
                             or s.startswith("Interests elsewhere")):
            break
        elif in_summary and (m := re.match(r"An? (.+?) is in effect for", s)):
            current = (m.group(1), [])
            c.watches_warnings.append(current)
        elif in_summary and current and s.startswith("*"):
            current[1].append(s.lstrip("* ").strip())
        elif in_summary and current and current[1] and s:   # a bullet wrapped onto the next line
            current[1][-1] += " " + s
        elif in_summary and not s:
            current = None                                  # blank line ends the bullet list

    c.next_advisories = [_pretty_times(l.strip()) for l in lines if re.match(r"\s*Next .*advisory at", l)]
    return c


def _pretty_times(text: str) -> str:
    """'Next complete advisory at 400 PM CDT.' -> 'Next complete advisory at 4:00 PM CDT.'"""
    return re.sub(r"\b(\d{1,2})(\d{2}) (AM|PM)\b", r"\1:\2 \3", text)


def _conditions(url: str) -> Conditions | None:
    try:
        html = requests.get(url, headers=HEADERS, timeout=30).text
    except requests.RequestException:
        return None
    pre = re.search(r"<pre[^>]*>(.*?)</pre>", html, re.S | re.I)
    text = re.sub(r"<[^>]+>", "", pre.group(1) if pre else html)
    try:
        return _parse_advisory(text, url)
    except (StopIteration, IndexError):
        return None


def saffir_simpson(wind_kt: float, classification: str) -> str:
    """Category label from max wind (kt) and NHC's classification code."""
    if classification in ("HU", "TY", "MH"):
        for floor, cat in [(137, "Category 5"), (113, "Category 4"), (96, "Category 3"), (83, "Category 2")]:
            if wind_kt >= floor:
                return f"{cat} hurricane"
        return "Category 1 hurricane"
    return {"TS": "Tropical storm", "TD": "Tropical depression", "STS": "Subtropical storm",
            "SD": "Subtropical depression", "PTC": "Potential tropical cyclone",
            "PC": "Post-tropical cyclone"}.get(classification, classification)


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

    if s.get("publicAdvisory", {}).get("url"):
        fc.conditions = _conditions(s["publicAdvisory"]["url"])

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

    for key, target in (("initialWindExtent", fc.wind_now), ("forecastWindRadiiGIS", fc.wind_forecast)):
        try:
            if s.get(key, {}).get("kmzFile"):
                for pm in re.findall(r"<Placemark>.*?</Placemark>", _kml(s[key]["kmzFile"]), re.S):
                    kt = re.search(r"<name>\s*(\d+)\s*</name>", pm)
                    for ring in re.findall(r"<outerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", pm, re.S):
                        if kt:
                            target.append((int(kt.group(1)), _coords(ring)))
        except (requests.RequestException, zipfile.BadZipFile, StopIteration, ValueError):
            pass
    try:
        if s.get("earliestArrivalTimeTSWindsGIS", {}).get("kmzFile"):
            kml = _kml(s["earliestArrivalTimeTSWindsGIS"]["kmzFile"])
            tz = re.search(r'<Data name="timezone">\s*<value>(\w+)</value>', kml)
            fc.arrival_tz = tz.group(1) if tz else ""
            for pm in re.findall(r"<Placemark>.*?</Placemark>", kml, re.S):
                label = re.search(r"<td>(.*?)</td>", pm)
                line = re.search(r"<LineString>\s*<coordinates>(.*?)</coordinates>", pm, re.S)
                if label and line and "Probability" not in label.group(1):
                    fc.arrival_34kt.append((label.group(1).strip(), _coords(line.group(1))))
    except (requests.RequestException, zipfile.BadZipFile, StopIteration, ValueError):
        pass
    return fc


# Swatch colors match the coastline segments on the map (wnx/maps.py WARNING_COLORS).
WW_COLORS = {"Hurricane Warning": "#d00000", "Hurricane Watch": "#f08cb4",
             "Tropical Storm Warning": "#1f3c88", "Tropical Storm Watch": "#f2c200",
             "Storm Surge Warning": "#a01ac4", "Storm Surge Watch": "#d6a8ec"}


def _tile(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div style="font-size:12px;color:#52514e">{sub}</div>' if sub else ""
    return (f'<div style="min-width:130px"><div style="font-size:12px;color:#52514e">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:#0b0b0b">{value}</div>{sub_html}</div>')


def conditions_html(fc: OfficialForecast | None) -> str:
    """'Current conditions' panel from the latest NHC advisory, or a note if NHC isn't tracking the storm."""
    box = ("border:1px solid #e6e5e0;border-radius:8px;padding:12px 18px;margin:12px 0;background:#fff;"
           "border-left:6px solid {accent}")
    if fc is None:
        return (f'<div style="{box.format(accent="#c3c2b7")}"><b>No NHC advisory for this storm.</b> '
                "The National Hurricane Center covers the Atlantic and the eastern and central Pacific. For other "
                'basins, see the <a href="https://www.metoc.navy.mil/jtwc/jtwc.html">Joint Typhoon Warning Center</a> '
                "or the regional weather agency.</div>")
    c = fc.conditions
    kind = saffir_simpson(fc.current_wind_kt, fc.classification)
    major = " · major hurricane" if kind.startswith(("Category 3", "Category 4", "Category 5")) else ""
    accent = "#d00000" if fc.classification == "HU" else "#1f3c88" if fc.classification in ("TS", "STS") else "#8a8984"
    title = f"{fc.name}: {kind}{major}"
    if c is None:   # advisory text unavailable; fall back to the JSON summary
        return (f'<div style="{box.format(accent=accent)}"><div style="font-size:20px;font-weight:700">{title}</div>'
                f"{fc.current_wind_kt:.0f} kt · {fc.current_mslp_hpa:.0f} mb · {fc.current_lat}, {fc.current_lon}"
                f" · NHC advisory {fc.advisory}</div>")

    adv = re.sub(r".*Advisory Number\s*", "Advisory ", c.title)
    if "Intermediate" in c.title:
        adv = "Intermediate a" + adv[1:]
    heads = "".join(f'<div style="font-weight:600;color:#0b0b0b;margin:6px 0 0">{h}</div>' for h in c.headlines)
    tiles = "".join([
        _tile("Max sustained wind", f"{c.wind_mph} mph" if c.wind_mph else f"{fc.current_wind_kt:.0f} kt",
              f"{fc.current_wind_kt:.0f} kt" if c.wind_mph else ""),
        _tile("Min. pressure", f"{c.pressure_mb} mb" if c.pressure_mb else "n/a"),
        _tile("Moving", c.movement or "n/a"),
        _tile("Center", c.location or f"{fc.current_lat}, {fc.current_lon}"),
    ])
    where = " · ".join(c.distances)
    # Near landfall NHC posts hourly position updates between advisories; CurrentStorms.json carries them.
    adv_pos = re.match(r"([\d.]+)([NS])\s+([\d.]+)([EW])", c.location or "")
    if adv_pos:
        lat = float(adv_pos.group(1)) * (1 if adv_pos.group(2) == "N" else -1)
        lon = float(adv_pos.group(3)) * (1 if adv_pos.group(4) == "E" else -1)
        if abs(lat - fc.current_lat) > 0.05 or abs(lon - fc.current_lon) > 0.05:
            when = fc.issued.replace(tzinfo=timezone.utc).astimezone().strftime("%I:%M %p").lstrip("0")
            where += (f'<div style="margin-top:4px;color:#0b0b0b"><b>Latest NHC position update ({when}):</b> '
                      f"{abs(fc.current_lat):.1f}{'N' if fc.current_lat >= 0 else 'S'} "
                      f"{abs(fc.current_lon):.1f}{'W' if fc.current_lon < 0 else 'E'} · "
                      f"{round(fc.current_wind_kt * 1.15078 / 5) * 5:.0f} mph · {fc.current_mslp_hpa:.0f} mb</div>")
    checked = datetime.now().astimezone().strftime("%I:%M %p").lstrip("0")
    nxt = (f" · <b>{' '.join(c.next_advisories)}</b>" if c.next_advisories else "") + \
          f" <span style='color:#8a8984'>(checked NHC at {checked})</span>"
    ww = ""
    if c.watches_warnings:
        items = "".join(
            f'<li style="margin:3px 0"><span style="display:inline-block;width:11px;height:11px;border-radius:2px;'
            f'background:{WW_COLORS.get(kind_, "#8a8984")};margin-right:7px;vertical-align:-1px"></span>'
            f'<b>{kind_}:</b> {"; ".join(areas)}</li>'
            for kind_, areas in c.watches_warnings)
        ww = (f'<div style="margin-top:10px;font-size:13px;color:#0b0b0b"><b>Watches &amp; warnings in effect</b>'
              f'<ul style="list-style:none;padding:0;margin:4px 0 0">{items}</ul></div>')
    return f"""<div style="{box.format(accent=accent)}">
<div style="font-size:12px;color:#52514e;text-transform:uppercase;letter-spacing:.04em">Current conditions ·
National Hurricane Center</div>
<div style="font-size:22px;font-weight:700;color:#0b0b0b;margin:2px 0">{title}</div>
<div style="font-size:13px;color:#52514e">{adv} · issued {_pretty_times(c.issued_text)}{nxt}</div>{heads}
<div style="display:flex;flex-wrap:wrap;gap:14px 28px;margin:12px 0 6px">{tiles}</div>
<div style="font-size:13px;color:#52514e">{where}</div>{ww}
<div style="margin-top:10px;font-size:13px"><a href="{c.url}">Read the full NHC advisory &rarr;</a></div>
</div>"""
