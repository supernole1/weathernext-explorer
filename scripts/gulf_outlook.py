"""15-day tropical outlook for the Gulf of America and NW Caribbean (WeatherNext 2 ensemble + NHC outlook).

    python scripts/gulf_outlook.py
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folium  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

from wnx import gulf, maps, plots, weatherlab  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TZ = "America/Chicago"
BLUE, BLUE_LIGHT, GRAY, INK, INK_2 = "#2a78d6", "#a9c8ef", "#8a8984", "#0b0b0b", "#52514e"


def local(t) -> pd.Timestamp:
    return pd.Timestamp(t).tz_localize("UTC").tz_convert(TZ)


def when(t) -> str:
    t = local(t)
    return f"{t:%a %b} {t.day}, {t.hour % 12 or 12} {t:%p %Z}"


def day(t) -> str:
    t = pd.Timestamp(t)
    return f"{t:%a %b} {t.day}"


def tile(label: str, value: str, sub: str = "", size: int = 28) -> str:
    return (f"<div style='border:1px solid #e6e5e0;border-radius:8px;padding:10px 14px;background:#fff'>"
            f"<div style='font-size:13px;color:{INK_2}'>{label}</div>"
            f"<div style='font-size:{size}px;font-weight:700;color:{INK};margin:2px 0'>{value}</div>"
            f"<div style='font-size:12px;color:{INK_2}'>{sub}</div></div>")


def headline(df, n, times, outlook) -> str:
    start = times[0]
    whole = gulf.summary(df, n, start)
    gulf_only = gulf.summary(df, n, start, gulf_only=True)
    first = whole["first"]
    if first.empty:
        timing = "No forecast develops a storm"
    else:
        t = first["time"].sort_values()
        timing = f"{day(local(t.iloc[0]).date())} – {day(local(t.iloc[-1]).date())}" if len(t) > 1 else day(local(t.iloc[0]).date())
    where = ", ".join(f"{r} ({c})" for r, c in whole["regions"].items()) or "–"
    ours = [a for a in outlook["areas"] if gulf.area_in_domain(a)]
    nhc_value = " / ".join(a["pct_7"] for a in ours) if ours else "None"
    nhc = (", ".join(f"{a['title']}: {a['pct_7']} chance in 7 days" for a in ours) if ours
           else "No areas outlined in the Gulf or Caribbean")
    tiles = "".join([
        tile("Next 7 days", f"{whole['pct_7']:.0f}%", "of the 64 forecasts develop a tropical-storm-strength system"),
        tile("Next 15 days", f"{whole['pct_15']:.0f}%", f"Gulf + NW Caribbean ({gulf_only['pct_15']:.0f}% in the Gulf itself)"),
        tile("When they form", timing, f"where: {where}", size=20),
        tile("NHC 7-day outlook", nhc_value, nhc + (f"<br>issued {outlook['issued']}" if outlook["issued"] else "")),
    ])
    return ("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin:12px 0'>"
            f"{tiles}</div>"
            f"<p>Forecast period {when(start)} to {when(times[-1])}. A \"storm\" here is a closed low with 39+ mph winds near its center "
            "for at least 12 hours, the threshold for a named tropical storm. NHC's chance covers 7 days only, so compare "
            "it with the 7-day number. "
            f"<a href='{outlook['url']}'>NHC's outlook</a> is the official word.</p>")


def chance_chart(df, n, times) -> go.Figure:
    days = pd.date_range(local(times[0]).date(), local(times[-1]).date(), freq="D").date
    d = gulf.daily_chance(df, n, TZ).set_index("date").reindex(days, fill_value=0).reset_index()
    labels = [day(x) for x in d["date"]]
    fig = go.Figure([
        go.Bar(x=labels, y=d["low_pct"], name="Any tropical low (25+ mph)", marker=dict(color=BLUE_LIGHT, cornerradius=4),
               hovertemplate="%{y:.0f}% of forecasts have a tropical low<extra></extra>"),
        go.Bar(x=labels, y=d["storm_pct"], name="Tropical-storm strength (39+ mph)", marker=dict(color=BLUE, cornerradius=4),
               width=0.45, hovertemplate="%{y:.0f}% of forecasts have a tropical storm<extra></extra>"),
    ])
    top = max(20, float(d["low_pct"].max()) + 5)
    plots._style(fig, "Chance of a tropical system in the Gulf or NW Caribbean, by day").update_layout(
        height=330, barmode="overlay", bargap=0.3, yaxis=dict(title="% of the 64 forecasts", range=[0, top]),
        legend=dict(orientation="h", y=-0.2))
    return fig


def outlook_map(df, outlook, existing: pd.DataFrame) -> folium.Figure:
    fig = folium.Figure(height=620)
    m = folium.Map(tiles=None, control_scale=True).add_to(fig)
    folium.TileLayer("Esri.WorldGrayCanvas", name="Light gray map").add_to(m)
    folium.TileLayer("Esri.WorldTopoMap", name="Topographic map").add_to(m)
    maps._add_live_weather(m)

    for a in outlook["areas"]:
        color = gulf.NHC_AREA_COLORS.get(a["category"], "#f2c200")
        folium.Polygon(a["polygon"], color=color, weight=2, fill=True, fill_opacity=0.25,
                       tooltip=f"<b>NHC: {a['title']}</b><br>Formation chance: {a['pct_2']} in 2 days, "
                               f"{a['pct_7']} in 7 days").add_to(
            folium.FeatureGroup(name=f"NHC outlook area: {a['title']} ({a['pct_7']})").add_to(m))

    for peak, color, label, show in (("low", GRAY, "Weaker tropical lows", True),
                                     ("storm", BLUE, "Tropical-storm-strength systems", True)):
        sub = df[df["peak"] == peak]
        count = sub["member"].nunique()
        layer = folium.FeatureGroup(name=f"{label} ({count} of 64 forecasts)", show=show).add_to(m)
        for (mem, _), g in sub.groupby(["member", "system"]):
            folium.PolyLine(g[["lat", "lon"]].values.tolist(), color=color, weight=2.5 if peak == "storm" else 1.5,
                            opacity=0.8, dash_array=None if peak == "storm" else "5 5",
                            tooltip=f"Forecast #{mem + 1}").add_to(layer)
            for r in g.itertuples():
                strong = r.strength == "storm"
                folium.CircleMarker([r.lat, r.lon], radius=4 if strong else 2.5, color="white", weight=1,
                                    fill=True, fill_color=color, fill_opacity=1 if strong else 0.7,
                                    tooltip=f"Forecast #{mem + 1}<br>{when(r.time)}<br>{r.pressure:.0f} mb, "
                                            f"winds near {r.wind_mph:.0f} mph").add_to(layer)
            s = g.iloc[0]
            folium.CircleMarker([s.lat, s.lon], radius=6, color=INK, weight=2, fill=True, fill_color="white",
                                fill_opacity=1, tooltip=f"Forecast #{mem + 1}: low first appears {when(s.time)}").add_to(layer)

    if not existing.empty:
        layer = folium.FeatureGroup(name="Current storms: WeatherNext 3 average track").add_to(m)
        for tid, g in existing.groupby("track_id"):
            folium.PolyLine(g[["lat", "lon"]].values.tolist(), color=plots.MODEL_COLORS["WNV3"], weight=3.5,
                            tooltip=f"{tid}: WeatherNext 3 average track").add_to(layer)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[15, -98], [31, -78]])
    return fig


def existing_storms() -> pd.DataFrame:
    """WeatherNext 3 average tracks of storms that already exist and pass through the Gulf/Caribbean."""
    init = weatherlab.latest_init("WNV3")
    if init is None:
        return pd.DataFrame()
    df = weatherlab.load("WNV3", init)
    if df.empty:
        return df
    hits = df[df["lat"].between(15, 31) & df["lon"].between(-98, -78)]["track_id"].unique()
    return df[df["track_id"].isin(hits)]


EXPLAINER = """
<details style="border:1px solid #e6e5e0;border-radius:8px;padding:10px 18px;margin:16px 0;background:#fff">
<summary style="cursor:pointer;font-weight:600">How this outlook works, and its limits</summary>
<ul style="line-height:1.55">
<li><b>Why not the storm tracks we use elsewhere?</b> DeepMind's Weather Lab only publishes tracks for storms that
already exist or that NHC is watching. To see storms that <i>haven't formed yet</i>, this page reads the raw
forecast weather instead: sea-level pressure and wind from all 64 <b>WeatherNext 2</b> forecasts, out to 15 days.</li>
<li><b>Finding storms:</b> on a grid of ocean points about 100 miles apart, each forecast is searched every 6 hours
for a <b>closed low</b> (pressure lowest in the middle and rising in every direction) with strong winds around it.
Lows that last at least 12 hours are kept and followed as they move.</li>
<li><b>The chance</b> is simply the share of the 64 forecasts that produce a tropical-storm-strength system
(39+ mph). 5 of 64 is about 8%.</li>
<li><b>Limits:</b> the 100-mile grid can miss small storms and reads peak winds low, so a real hurricane may show
as a 60 mph storm here. In fall, a cold front can occasionally spin up a low that passes the test without being
tropical. Beyond about 10 days, any one forecast is a scenario, not a prediction; the <i>share</i> of
forecasts is what carries information.</li>
<li><b>Use it with NHC:</b> NHC's <a href="https://www.nhc.noaa.gov/gtwo.php?basin=atlc">Tropical Weather
Outlook</a> (outlined areas on the map) is the official 7-day forecast. This page adds days 8–15 and shows
where the AI model's storms tend to form and go.</li>
<li>Data via <a href="https://open-meteo.com/en/docs/google-weathernext-api">Open-Meteo</a> (free, non-commercial).
It's saved for 3 hours, because the model only updates a few times a day. With Google Cloud access this can move to
WeatherNext 3.</li>
</ul></details>"""


def main() -> None:
    print("Gulf of America + NW Caribbean, 15-day tropical outlook")
    data = gulf.fetch()
    df, times, n = gulf.detect(data)
    outlook = gulf.nhc_outlook()
    existing = existing_storms()
    s = gulf.summary(df, n, times[0])
    print(f"  WeatherNext 2 forecast through {when(times[-1])}, downloaded {data['fetched'][:16].replace('T', ' ')} UTC")
    print(f"  Tropical-storm-strength system: {s['pct_7']:.0f}% within 7 days, {s['pct_15']:.0f}% within 15 days")
    for a in outlook["areas"]:
        print(f"  NHC area: {a['title']} ({a['pct_7']} in 7 days)")

    figs = [
        headline(df, n, times, outlook),
        EXPLAINER,
        "<h3>Where the forecast storms form and go</h3><p>Each <b style='color:#2a78d6'>blue line</b> is one of "
        "the 64 forecasts that develops a tropical storm; bigger dots are where it's at storm strength. "
        "<b style='color:#8a8984'>Gray dashed lines</b> are weaker lows. A white dot marks where each low first "
        "appears. Hover for times, pressure and wind. Shaded areas are NHC's outlook.</p>",
        outlook_map(df, outlook, existing),
        chance_chart(df, n, times),
    ]
    if outlook["active"]:
        figs.insert(1, f"<p><b>NHC active systems:</b> {outlook['active']}</p>")
    out = plots.write_report(
        figs, ROOT / "outputs" / "gulf_outlook.html", "Gulf of America: 15-day tropical outlook",
        notes=f"From the 64-member WeatherNext 2 ensemble (Google DeepMind), {when(times[0])} to {when(times[-1])}, "
              "plus NHC's Tropical Weather Outlook. Experimental; not an official forecast.")
    print(f"\nOutlook written: {out}")


if __name__ == "__main__":
    main()
