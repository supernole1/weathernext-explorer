"""Zoomable street maps of cyclone tracks (Leaflet via folium; no WebGL needed).

Base maps show state lines, cities and roads; a US county-lines overlay can be toggled
from the layer control in the map's top-right corner.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import folium
import pandas as pd
import requests

from .nhc import OfficialForecast
from .plots import MODEL_COLORS, OBS_COLOR

COUNTIES_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
COUNTIES_CACHE = Path(__file__).resolve().parent.parent / "data" / "us_counties.geojson"
MEMBER_COLOR = "#2a78d6"


def _counties_in(south: float, west: float, north: float, east: float) -> dict | None:
    """US county outlines that overlap the box, with coordinates rounded to keep the page small."""
    if not COUNTIES_CACHE.exists():
        COUNTIES_CACHE.parent.mkdir(parents=True, exist_ok=True)
        COUNTIES_CACHE.write_bytes(requests.get(COUNTIES_URL, timeout=120).content)
    data = json.loads(COUNTIES_CACHE.read_text(encoding="latin-1"))

    def rings(geom):
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        return [ring for poly in polys for ring in poly]

    feats = []
    for f in data["features"]:
        pts = [p for ring in rings(f["geometry"]) for p in ring]
        if not any(west <= x <= east and south <= y <= north for x, y in pts):
            continue
        lines = [[[round(x, 3), round(y, 3)] for x, y in ring] for ring in rings(f["geometry"])]
        feats.append({"type": "Feature", "properties": {"name": f["properties"].get("NAME", "")},
                      "geometry": {"type": "MultiLineString", "coordinates": lines}})
    return {"type": "FeatureCollection", "features": feats} if feats else None


def _point_tooltip(row, label: str) -> str:
    lead = f" (+{int(row.lead_time_hours)}h)" if "lead_time_hours" in row else ""
    return (f"<b>{label}</b><br>{row.valid_time:%a %b %d %H:%MZ}{lead}<br>"
            f"{row.wind_kt:.0f} kt · {row.mslp_hpa:.0f} hPa")


RADAR_URL = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png"
SATELLITE_WMS = "https://nowcoast.noaa.gov/geoserver/satellite/wms"


def _add_live_weather(m: folium.Map) -> None:
    """Live NEXRAD radar (US, ~5 min updates) and global infrared satellite, as of page build time."""
    now = datetime.now(timezone.utc)
    stamp = f"{now:%H:%M}Z"
    bust = now.strftime("%Y%m%d%H%M")  # new URL each build, so a refresh never shows cached old radar
    folium.TileLayer(f"{RADAR_URL}?_={bust}", name=f"Live radar, US only (as of {stamp})",
                     attr="NEXRAD via Iowa Environmental Mesonet", overlay=True, opacity=0.7,
                     max_native_zoom=8).add_to(m)
    folium.WmsTileLayer(SATELLITE_WMS, layers="global_longwave_imagery_mosaic", fmt="image/png",
                        transparent=True, name=f"Live satellite, infrared (as of {stamp})",
                        attr="NOAA nowCOAST", overlay=True, opacity=0.55, show=False,
                        build=bust).add_to(m)


# NHC's conventional watch/warning colors (navy for TS warning so it doesn't read as WNV3 blue).
WARNING_COLORS = {"Hurricane Warning": "#d00000", "Hurricane Watch": "#f08cb4",
                  "Tropical Storm Warning": "#1f3c88", "Tropical Storm Watch": "#f2c200"}
NHC_COLOR = "#0b0b0b"


def _add_official(m: folium.Map, f: OfficialForecast) -> None:
    issued = f"NHC advisory {f.advisory}, {f.issued:%m-%d %HZ}"
    if f.cone:
        layer = folium.FeatureGroup(name=f"NHC cone — {issued}").add_to(m)
        folium.Polygon(f.cone, color=NHC_COLOR, weight=1.5, dash_array="6 4", fill=True,
                       fill_color="#ffffff", fill_opacity=0.35,
                       tooltip=f"NHC cone of uncertainty ({issued}): the storm center is expected to "
                               "stay inside it about 2 out of 3 times").add_to(layer)
    if f.track:
        layer = folium.FeatureGroup(name=f"NHC official track — {f.name}").add_to(m)
        folium.PolyLine([[p.lat, p.lon] for p in f.track], color=NHC_COLOR, weight=3,
                        dash_array="8 6", tooltip=f"NHC official track ({issued})").add_to(layer)
        for p in f.track:
            when = f"{p.valid_time:%a %b %d %H:%MZ}" if p.valid_time else ""
            wind = f"{p.wind_kt:.0f} kt" if p.wind_kt is not None else ""
            folium.CircleMarker([p.lat, p.lon], radius=5, color=NHC_COLOR, weight=2, fill=True,
                                fill_color="white", fill_opacity=1,
                                tooltip=f"<b>NHC {p.label}</b><br>{when}<br>{wind}").add_to(layer)
    if f.warnings:
        layer = folium.FeatureGroup(name="NHC coastal watches & warnings").add_to(m)
        for kind, coords in f.warnings:
            folium.PolyLine(coords, color=WARNING_COLORS.get(kind, "#7a00cc"), weight=7, opacity=0.9,
                            tooltip=f"{kind} ({issued})").add_to(layer)


def track_map(members: pd.DataFrame, means: pd.DataFrame, obs: pd.DataFrame | None,
              height: int = 650, counties: bool = True,
              official: list[OfficialForecast] | None = None) -> folium.Figure:
    """Spaghetti map: thin ensemble members, bold ensemble mean(s) with hover points, observed track,
    and (when given) the official NHC cone, track and coastal watches/warnings."""
    fig = folium.Figure(height=height)
    m = folium.Map(tiles=None, control_scale=True).add_to(fig)
    # Esri tiles need no API key and work from pages opened off disk (file://).
    # OpenStreetMap blocks file:// pages and CARTO now requires a key.
    # The last layer added is the one shown by default.
    folium.TileLayer("Esri.WorldGrayCanvas", name="Light gray map").add_to(m)
    folium.TileLayer("Esri.WorldTopoMap", name="Topographic map").add_to(m)
    folium.TileLayer("Esri.WorldStreetMap", name="Street map (roads, cities)").add_to(m)
    _add_live_weather(m)

    official = [f for f in (official or []) if f is not None]
    extra = [pd.DataFrame(f.cone or [[p.lat, p.lon] for p in f.track], columns=["lat", "lon"])
             for f in official]
    lats = pd.concat([means["lat"]] + ([obs["lat"]] if obs is not None and not obs.empty else [])
                     + [e["lat"] for e in extra])
    lons = pd.concat([means["lon"]] + ([obs["lon"]] if obs is not None and not obs.empty else [])
                     + [e["lon"] for e in extra])
    south, north, west, east = lats.min() - 2, lats.max() + 2, lons.min() - 3, lons.max() + 3

    if counties and west < -65 and east > -125 and south < 50 and north > 24:
        gj = _counties_in(south - 6, west - 10, north + 6, east + 10)
        if gj:
            folium.GeoJson(gj, name="US counties", style_function=lambda _: {
                "color": "#8a8984", "weight": 0.7, "opacity": 0.8},
                tooltip=folium.GeoJsonTooltip(["name"], labels=False)).add_to(m)

    for f in official:
        _add_official(m, f)

    if not members.empty:
        layer = folium.FeatureGroup(name=f"Ensemble members ({members['sample'].nunique()})").add_to(m)
        for _, g in members.groupby(["model", "init_time", "track_id", "sample"]):
            folium.PolyLine(g[["lat", "lon"]].values.tolist(), color=MEMBER_COLOR,
                            weight=1, opacity=0.3).add_to(layer)

    for (model, init), g in means.groupby(["model", "init_time"]):
        color = MODEL_COLORS.get(model, "#2a78d6")
        layer = folium.FeatureGroup(name=f"{model} ensemble mean, run {init:%m-%d %HZ}").add_to(m)
        for _, t in g.groupby("track_id"):
            folium.PolyLine(t[["lat", "lon"]].values.tolist(), color=color, weight=3.5,
                            tooltip=f"{model} mean — {t['track_id'].iloc[0]}").add_to(layer)
            for row in t.itertuples():
                folium.CircleMarker([row.lat, row.lon], radius=4, color="white", weight=1.5,
                                    fill=True, fill_color=color, fill_opacity=1,
                                    tooltip=_point_tooltip(row, f"{model} mean {row.track_id}")).add_to(layer)

    if obs is not None and not obs.empty:
        layer = folium.FeatureGroup(name="Observed track (IBTrACS)").add_to(m)
        folium.PolyLine(obs[["lat", "lon"]].values.tolist(), color=OBS_COLOR, weight=3.5).add_to(layer)
        for row in obs.dropna(subset=["wind_kt"]).itertuples():
            folium.CircleMarker([row.lat, row.lon], radius=5, color="white", weight=1.5, fill=True,
                                fill_color=OBS_COLOR, fill_opacity=1,
                                tooltip=_point_tooltip(row, "Observed")).add_to(layer)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[south, west], [north, east]])
    return fig


HOW_TO_READ = """
<div style="border:1px solid #e6e5e0;border-radius:8px;padding:12px 18px;margin:14px 0;background:#fff">
<h3 style="margin:4px 0 8px">How to read this map</h3>
<ul style="margin:0;padding-left:20px;line-height:1.5">
<li><b style="color:#2a78d6">Thin light-blue lines: the 64 WeatherNext 3 ensemble members.</b> DeepMind runs the
model 64 times with slightly different starting conditions. Each line is one plausible path. A tight bundle
means the model is confident; a wide fan means the path is uncertain.</li>
<li><b style="color:#2a78d6">Bold blue line (WNV3 mean):</b> the average position of all 64 WeatherNext 3 members
at each 6-hour step. It is the model's single best-guess track and, on average, beats any one member.</li>
<li><b style="color:#16956a">Bold green line (OPER mean):</b> the same idea from a different model, WeatherNext
Cyclones. That is DeepMind's earlier operational cyclone model (built on WeatherNext 2, 50 members), which NHC
has consulted since 2025. When the blue and green means agree, confidence is higher. Where they split, so does
the uncertainty.</li>
<li><b>Black dashed line + white cone: the official NHC forecast.</b> The cone is drawn from NHC's
past errors: the storm <i>center</i> stays inside it about 2 out of 3 times. It does <i>not</i> show the storm's
size. Damaging wind, rain and surge often reach far outside it. The thick colored coastline segments are
NHC watches and warnings (red = hurricane warning, pink = hurricane watch, navy = tropical storm warning,
yellow = tropical storm watch).</li>
<li><b>Live radar</b> (on by default) shows rain from US NEXRAD radars, which reach roughly 150 miles offshore.
<b>Live satellite</b> (off by default; tick it in the layer box) shows infrared cloud tops worldwide, so
you can see a storm still far out at sea. Both are as of the time in the layer name. Press Refresh for newer images.</li>
<li><b style="color:#eb6834">Orange: observed track</b> from NOAA IBTrACS. It usually runs about a day behind.</li>
</ul>
<p style="margin:10px 0 4px"><b>Watch out for:</b></p>
<ul style="margin:0;padding-left:20px;line-height:1.5">
<li><b>Averages hide splits.</b> If half the members turn east and half go north, the mean runs up the middle where
<i>no</i> member goes. Always glance at the thin lines.</li>
<li><b>Mean intensity is smoothed.</b> Averaging 64 wind forecasts softens the peaks, so the mean usually understates
the strongest winds. Use the plume chart below for the range.</li>
<li><b>Different issue times.</b> The WeatherNext run, the green model's run and the NHC advisory can be several hours
apart. The legend box shows each one's time, and newer generally beats older.</li>
<li>This is experimental research data. Use NHC and your local officials for decisions.</li>
</ul></div>
"""
