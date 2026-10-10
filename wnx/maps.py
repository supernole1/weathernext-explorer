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

from . import windobs
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


# Sustained-wind thresholds NHC maps: 34/50/64 kt = 39/58/74 mph.
WIND_FIELD = {34: ("#f2c200", "39+ mph (tropical-storm force)"), 50: ("#eb6834", "58+ mph"),
              64: ("#d00000", "74+ mph (hurricane force)")}


def _add_wind_field(m: folium.Map, f: OfficialForecast) -> None:
    if f.wind_now:
        layer = folium.FeatureGroup(name=f"NHC wind field now: 39/58/74+ mph ({f.name})").add_to(m)
        for kt, ring in sorted(f.wind_now, key=lambda x: x[0]):
            color, label = WIND_FIELD.get(kt, ("#8a8984", f"{kt} kt"))
            folium.Polygon(ring, color=color, weight=1.5, fill=True, fill_color=color, fill_opacity=0.18,
                           tooltip=f"{f.name}: sustained winds of {label} extend this far now "
                                   f"(NHC advisory {f.advisory})").add_to(layer)
    if f.wind_forecast:
        layer = folium.FeatureGroup(name=f"NHC forecast wind field, next 3 days ({f.name})", show=False).add_to(m)
        for kt, ring in sorted(f.wind_forecast, key=lambda x: x[0]):
            color, label = WIND_FIELD.get(kt, ("#8a8984", f"{kt} kt"))
            folium.Polygon(ring, color=color, weight=1, dash_array="4 4", fill=True, fill_color=color,
                           fill_opacity=0.07, tooltip=f"{f.name}: forecast reach of {label} winds "
                                                      f"(NHC advisory {f.advisory})").add_to(layer)
    if f.arrival_34kt:
        layer = folium.FeatureGroup(name=f"NHC earliest arrival of 39+ mph winds ({f.name})", show=False).add_to(m)
        for label, line in f.arrival_34kt:
            folium.PolyLine(line, color="#6a3fb5", weight=2.5, dash_array="7 5",
                            tooltip=folium.Tooltip(f"39+ mph winds as early as {label} {f.arrival_tz}",
                                                   permanent=True, sticky=False)).add_to(layer)


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
    _add_wind_field(m, f)
    if f.warnings:
        layer = folium.FeatureGroup(name="NHC coastal watches & warnings").add_to(m)
        for kind, coords in f.warnings:
            folium.PolyLine(coords, color=WARNING_COLORS.get(kind, "#7a00cc"), weight=7, opacity=0.9,
                            tooltip=f"{kind} ({issued})").add_to(layer)


def _unwrap(df: pd.DataFrame | None, keys: list[str]) -> pd.DataFrame | None:
    """Keep date-line-crossing tracks continuous. A West Pacific storm recurving past 180° jumps from +179 to
    -179 and would be drawn the long way around the world, so shift that track's negative longitudes by +360."""
    if df is None or df.empty:
        return df
    groups = df.groupby(keys)["lon"] if keys else [(None, df["lon"])]
    crossing = pd.Series(False, index=df.index)
    for _, lon in groups:
        if lon.max() - lon.min() > 180:
            crossing[lon.index] = True
    return df.assign(lon=df["lon"].where(~crossing | (df["lon"] >= 0), df["lon"] + 360))


def track_map(members: pd.DataFrame, means: pd.DataFrame, obs: pd.DataFrame | None,
              height: int = 650, counties: bool = True,
              official: list[OfficialForecast] | None = None, wind_obs: bool = True) -> folium.Figure:
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

    location_data = _location_data(means, members, official)  # raw lon (-180..180) for distance math
    location_means = means[means["lead_time_hours"] == means.groupby(["model", "track_id"])["lead_time_hours"]
                           .transform("min")]
    members = _unwrap(members, ["model", "init_time", "track_id", "sample"])
    means = _unwrap(means, ["model", "init_time", "track_id"])
    obs = _unwrap(obs, [])
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
        layer = folium.FeatureGroup(name=f"Observed track ({obs.attrs.get('source', 'IBTrACS')})").add_to(m)
        folium.PolyLine(obs[["lat", "lon"]].values.tolist(), color=OBS_COLOR, weight=3.5).add_to(layer)
        for row in obs.dropna(subset=["wind_kt"]).itertuples():
            folium.CircleMarker([row.lat, row.lon], radius=5, color="white", weight=1.5, fill=True,
                                fill_color=OBS_COLOR, fill_opacity=1,
                                tooltip=_point_tooltip(row, "Observed")).add_to(layer)

    if wind_obs:
        ref = [(f.current_lat, f.current_lon) for f in official]
        ref += [(t["lat"].iloc[0], t["lon"].iloc[0]) for _, t in location_means.groupby("track_id")
                if t["track_id"].iloc[0] not in {f.atcf_id for f in official}]
        _add_wind_obs(m, windobs.near(ref))

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[south, west], [north, east]])
    # "My location" star: the static script reads WNX_MAP / WNX_STORMS. folium emits this element before the
    # map's own setup code, so defer it until the map variable exists.
    m.get_root().script.add_child(folium.Element(
        f"setTimeout(function () {{ var WNX_MAP = {m.get_name()}; var WNX_STORMS = {json.dumps(location_data)};"
        + "\n" + MY_LOCATION_JS.read_text(encoding="utf-8") + "\n" + CALM_JS + "\n}, 0);"))
    return fig


# Station readings below CALM_MPH clutter the map when zoomed out; show them only from zoom 9 (metro scale) in.
CALM_MPH = 20
CALM_JS = """(function (map) {
  function update() {
    var show = map.getZoom() >= 9;
    document.querySelectorAll(".wnx-calm").forEach(function (e) { e.style.display = show ? "" : "none"; });
  }
  map.on("zoomend overlayadd", update);
  update();
})(WNX_MAP);"""


MY_LOCATION_JS = Path(__file__).resolve().parent / "static" / "my_location.js"

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _wind_style(peak: float | None, suspect: str) -> tuple[str, str]:
    """(background, text color) for a station label, by peak wind (gust if reported)."""
    if suspect:
        return "#d9d9d6", "#52514e"
    if peak is None or pd.isna(peak) or peak < 39:
        return "#ffffff", "#0b0b0b"
    if peak < 58:
        return "#f2c200", "#0b0b0b"
    if peak < 74:
        return "#eb6834", "#0b0b0b"
    return "#d00000", "#ffffff"


def _add_wind_obs(m: folium.Map, obs: pd.DataFrame) -> None:
    """Measured wind at airports and buoys: label 'sustained G gust' (mph) plus an arrow showing where it blows."""
    if obs.empty:
        return
    local = datetime.now().astimezone().tzinfo
    newest = obs["time"].max().tz_localize("UTC").tz_convert(local)
    layer = folium.FeatureGroup(name=f"Measured wind: airports and buoys (as of {newest:%I:%M %p})".replace(" 0", " "))
    for r in obs.itertuples():
        sust = None if pd.isna(r.sust_mph) else round(r.sust_mph)
        gust = None if pd.isna(r.gust_mph) else round(r.gust_mph)
        peak = max(v for v in (sust, gust, -1) if v is not None)
        bg, fg = _wind_style(peak if peak >= 0 else None, r.suspect)
        text = (f"{sust if sust is not None else '–'}" + (f" G{gust}" if gust is not None else "")
                + ("?" if r.suspect else ""))
        has_dir = not pd.isna(r.dir_deg)
        arrow = (f"<svg width='12' height='12' viewBox='0 0 12 12' style='transform:rotate({(r.dir_deg + 180) % 360:.0f}deg)'>"
                 "<path d='M6 0 L10 11 L6 8 L2 11 Z' fill='#0b0b0b'/></svg>") if has_dir else ""
        html = (f"<div style='display:flex;align-items:center;gap:1px;transform:translate(-50%,-50%);white-space:nowrap'>"
                f"{arrow}<span style='background:{bg};color:{fg};font:600 11px system-ui,sans-serif;padding:0 4px;"
                f"border-radius:4px;border:1px solid rgba(0,0,0,.4)'>{text}</span></div>")
        when = pd.Timestamp(r.time).tz_localize("UTC").tz_convert(local)
        details = [f"<b>{r.name}</b> ({r.id}) · {'airport' if r.kind == 'airport' else 'NOAA buoy / coastal station'}"]
        if sust is not None:
            details.append(f"Sustained {sust} mph" + (f" from the {COMPASS[round(r.dir_deg / 22.5) % 16]}" if has_dir else ""))
        if gust is not None:
            details.append(f"Gusts {gust} mph")
        if not pd.isna(r.pressure_mb):
            details.append(f"Pressure {r.pressure_mb:.0f} mb")
        if r.wave_ft is not None and not pd.isna(r.wave_ft):
            details.append(f"Waves {r.wave_ft:.0f} ft")
        details.append(f"Observed {when:%a %I:%M %p %Z}".replace(" 0", " "))
        if r.suspect:
            details.append(f"<span style='color:#b00'>Possibly unreliable: {r.suspect}.</span>")
        calm = "wnx-calm" if peak < CALM_MPH and not r.suspect else ""
        folium.Marker([r.lat, r.lon], icon=folium.DivIcon(html=html, icon_size=(1, 1), icon_anchor=(0, 0),
                                                          class_name=calm),
                      tooltip="<br>".join(details)).add_to(layer)
    layer.add_to(m)


def _ms(t) -> int:
    """Naive-UTC timestamp -> epoch milliseconds for JavaScript."""
    return int(pd.Timestamp(t).tz_localize("UTC").value // 1_000_000)


def _location_data(means: pd.DataFrame, members: pd.DataFrame,
                   official: list[OfficialForecast | None] | None) -> dict:
    """Per storm: NHC position, each model's newest mean track, and member tracks, for the star's distances."""
    nhc_by_id = {f.atcf_id: f for f in (official or []) if f is not None}
    storms = {}
    for storm_id, g in means.groupby("track_id"):
        f = nhc_by_id.get(storm_id)
        entry = {"name": f.name if f else storm_id, "means": {}, "members": None,
                 "now": {"lat": f.current_lat, "lon": f.current_lon, "ms": _ms(f.issued)} if f else None}
        for model, mg in g.groupby("model"):
            newest = mg[mg["init_time"] == mg["init_time"].max()].sort_values("lead_time_hours")
            entry["means"][model] = {
                "run": f"{newest['init_time'].iloc[0]:%m-%d %HZ}",
                "track": [[round(r.lat, 2), round(r.lon, 2), _ms(r.valid_time)] for r in newest.itertuples()]}
        if members is not None and not members.empty:
            mem = members[members["track_id"] == storm_id]
            if not mem.empty:
                mem = mem[mem["init_time"] == mem["init_time"].max()]
                entry["members"] = {"model": mem["model"].iloc[0], "tracks": [
                    [[round(r.lat, 2), round(r.lon, 2), _ms(r.valid_time)] for r in t.sort_values("lead_time_hours").itertuples()]
                    for _, t in mem.groupby("sample")]}
        storms[storm_id] = entry
    return storms


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
<li><b>Measured wind</b> (on by default): labels like <b>29 G63</b> are the latest readings at airports and NOAA
buoys, sustained wind G gusts in mph. The arrow points where the wind is blowing <i>to</i>. Colors follow the
peak reading: white below 39 mph, yellow 39+, orange 58+, red 74+ (hurricane force). Gray with a "?" marks a
reading that looks like a faulty sensor; hover any label for details.</li>
<li><b>NHC wind field</b> (on by default): shaded rings showing how far 39+ (yellow), 58+ (orange) and 74+ mph (red)
sustained winds reach from the center right now. Tick <i>forecast wind field</i> to see their reach over the next
3 days, and <i>earliest arrival of 39+ mph winds</i> for NHC's "conditions go downhill as early as..." lines.</li>
<li><b>Live radar</b> (on by default) shows rain from US NEXRAD radars, which reach roughly 150 miles offshore.
<b>Live satellite</b> (off by default; tick it in the layer box) shows infrared cloud tops worldwide, so
you can see a storm still far out at sea. Both are as of the time in the layer name. Press Refresh for newer images.</li>
<li><b style="color:#eb6834">Orange: observed track.</b> For storms NHC tracks, this is NHC's official best
track, updated with each advisory (about every 6 hours). Elsewhere it comes from NOAA's IBTrACS archive, which
runs about a day behind.</li>
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
