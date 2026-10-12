"""Acronyms and abbreviations used across the reports, shown in a pop-up on each page.

Each page lists only the terms that actually appear on it (see `popup`).
"""

from __future__ import annotations

import html
import re

# term: (meaning, optional regex if a plain word-boundary match on the term won't do)
TERMS: dict[str, tuple[str, str | None]] = {
    "AI": ("Artificial intelligence. WeatherNext is an AI model trained on decades of past weather.", None),
    "AM / PM": ("Before noon / after noon.", r"\b\d{1,2}(:\d\d)? ?(AM|PM)\b"),
    "AO": ("Arctic Oscillation: an index of air pressure over the Arctic. Strongly negative values often go with "
           "cold outbreaks in the eastern US.", None),
    "ASOS": ("Automated Surface Observing System: the weather stations at US airports.", None),
    "ATCF": ("Automated Tropical Cyclone Forecasting system: the format NHC uses for storm IDs and track data.", None),
    "BigQuery": ("Google Cloud's database service, where the full WeatherNext data is published.", None),
    "CC BY 4.0": ("Creative Commons Attribution license: free to reuse with credit.", r"\bCC BY\b"),
    "CDT / CST": ("Central Daylight / Standard Time.", r"\b(CDT|CST)\b"),
    "CLIPER / SHIFOR": ("Simple statistical baseline forecasts (climatology and persistence) that any skilful model "
                        "should beat.", r"\b(CLIPER|SHIFOR)\b"),
    "CPC": ("NOAA's Climate Prediction Center, which issues the official US outlooks from 6 days to a year ahead.", None),
    "DJF": ("December–January–February, meteorological winter. NOAA names 3-month seasons by their first letters "
            "(NDJ, JFM, ...).", r"\b(DJF|NDJ|JFM|FMA|OND|SON|MAM|AMJ|MJJ|JJA|JAS|ASO)\b"),
    "EC": ("Equal chances: NOAA's label when its outlook doesn't lean warmer/colder or wetter/drier.", r"\bEC\b(?!MWF)"),
    "ECMWF": ("European Centre for Medium-Range Weather Forecasts. Its models are among the most accurate in the "
              "world.", None),
    "EDT / EST": ("Eastern Daylight / Standard Time.", r"\b(EDT|EST)\b"),
    "ENSO": ("El Niño–Southern Oscillation: the El Niño / La Niña cycle in the tropical Pacific.", r"\bENSO\b|El Niño"),
    "FNV3": ("An experimental WeatherNext 3 variant (Weather Lab's FNV3P1/FNV3P2).", r"\bFNV3"),
    "G (in 29 G63)": ("Gust: \"29 G63\" means a 29 mph steady wind gusting to 63 mph.", r"\bG\d{2}\b|\d+ G\d+"),
    "GFS": ("Global Forecast System: the main US government weather model.", None),
    "hPa / mb": ("Hectopascals / millibars, the same unit of air pressure. Lower pressure at a storm's center means "
                 "a stronger storm. 10 hPa is about 19 miles up.", r"\b(hPa|mb)\b"),
    "HU / TS / TD": ("Hurricane / tropical storm / tropical depression (NHC's storm classes). STS and STD are the "
                     "subtropical versions; PTC is post-tropical.", r"\b(HU|TS|TD|STS|STD|PTC)\b"),
    "IBTrACS": ("International Best Track Archive for Climate Stewardship: NOAA's global record of observed storm "
                "tracks.", None),
    "kt": ("Knots: nautical miles per hour. 1 kt = 1.15 mph.", r"\b(kt|knots)\b"),
    "m/s": ("Meters per second. 1 m/s = 2.24 mph.", r"\bm/s\b"),
    "mph": ("Miles per hour.", r"\b(mph|MPH)\b"),
    "NDBC": ("National Data Buoy Center: NOAA's ocean buoys and coastal stations.", None),
    "NEXRAD": ("Next-Generation Radar: the US network of Doppler weather radars.", None),
    "NHC": ("National Hurricane Center (NOAA), the official source of US tropical forecasts and warnings.", None),
    "NOAA": ("National Oceanic and Atmospheric Administration: the US agency over the National Weather Service, NHC "
             "and CPC.", None),
    "NWS": ("National Weather Service.", None),
    "N, NNE, NE, ...": ("Compass directions: north, north-northeast, northeast, and so on around the 16 points.",
                        r"\b(NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|SE|SW|NW)\b"),
    "OFCL": ("NHC's official forecast, as labeled in its forecast files.", None),
    "OPER": ("Weather Lab's operational WeatherNext model (the green line), compared against WeatherNext 3.", None),
    "PDT / PST": ("Pacific Daylight / Standard Time.", r"\b(PDT|PST)\b"),
    "SEAS5": ("ECMWF's seasonal forecast system (fifth version): 51 forecasts out to 7 months.", None),
    "Storm IDs": ("Like AL092026: basin (AL Atlantic, EP eastern Pacific, CP central Pacific, WP western Pacific), "
                  "storm number, year.", r"\b(AL|EP|CP|WP)\d{6}\b"),
    "US": ("United States.", r"\bUS\b"),
    "UTC / Z": ("Coordinated Universal Time, the clock forecasters use worldwide (\"12Z\" is 12:00 UTC). Central "
                "Daylight Time is UTC − 5 hours.", r"\bUTC\b|\b\d{2}Z\b"),
    "WNV3 / WN3": ("WeatherNext 3, Google DeepMind's newest AI weather model.", r"\b(WNV3|WN3)\b"),
    "ZIP": ("US postal code, used to find your location.", r"\bZIP\b"),
}

BUTTON = """
<button id="wnx-acr-open" title="What the abbreviations mean"
 style="position:fixed;right:16px;bottom:16px;z-index:2000;font:600 14px system-ui,sans-serif;padding:8px 14px;
 border-radius:20px;border:1px solid #1c5cab;background:#fff;color:#1c5cab;cursor:pointer;
 box-shadow:0 2px 8px rgba(0,0,0,.15)">Acronyms</button>
<dialog id="wnx-acr" style="max-width:560px;width:calc(100% - 32px);max-height:80vh;border:1px solid #e6e5e0;
 border-radius:10px;padding:0;box-shadow:0 8px 30px rgba(0,0,0,.25)">
<div style="position:sticky;top:0;background:#fff;display:flex;justify-content:space-between;align-items:center;
 padding:12px 18px;border-bottom:1px solid #e6e5e0">
<b style="font:600 16px system-ui,sans-serif">Acronyms on this page</b>
<button id="wnx-acr-close" aria-label="Close" style="font:600 20px system-ui,sans-serif;border:none;
 background:none;cursor:pointer;color:#52514e;line-height:1">&times;</button></div>
<dl style="margin:0;padding:8px 18px 16px;font:14px/1.45 system-ui,sans-serif">{items}</dl></dialog>
<script>
(function () {
  const d = document.getElementById("wnx-acr");
  document.getElementById("wnx-acr-open").onclick = () => d.showModal();
  document.getElementById("wnx-acr-close").onclick = () => d.close();
  d.addEventListener("click", e => { if (e.target === d) d.close(); });  // click outside the box closes it
})();
</script>"""


def _visible(page_html: str) -> str:
    """Page text plus chart/map labels: drop tags but keep inline script data (legends, tooltips)."""
    text = re.sub(r"(?s)<style.*?</style>", " ", page_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text.replace("\\u00b0", "°"))


def used(page_html: str) -> list[tuple[str, str]]:
    text = _visible(page_html)
    hits = []
    for term, (meaning, pattern) in TERMS.items():
        if re.search(pattern or rf"\b{re.escape(term)}\b", text):
            hits.append((term, meaning))
    return sorted(hits, key=lambda t: t[0].lower())


def popup(page_html: str) -> str:
    """Floating "Acronyms" button and its pop-up, listing the terms found in page_html ('' if none)."""
    hits = used(page_html)
    if not hits:
        return ""
    items = "".join(f"<dt style='font-weight:700;color:#0b0b0b;margin-top:10px'>{html.escape(t)}</dt>"
                    f"<dd style='margin:2px 0 0;color:#52514e'>{html.escape(m)}</dd>" for t, m in hits)
    return BUTTON.replace("{items}", items)
