"""Winter outlook for a US ZIP code: NOAA's official 3-month outlooks, El Niño / La Niña status, and the
51-member ECMWF seasonal forecast.

    python scripts/winter_outlook.py 32578
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

from wnx import forecast, plots, seasonal  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
# Diverging pairs: warm/cool for temperature, green/brown for rain (the conventions on NOAA's own maps).
WARM, COOL, WET, DRY, NEUTRAL = "#d1495b", "#2a78d6", "#1baf7a", "#a8642a", "#8a8984"
PROB_BINS = {33: "33–40%", 40: "40–50%", 50: "50–60%", 60: "60–70%", 70: "70–80%", 80: "80–90%", 90: "90–100%"}


def month_name(p: pd.Period) -> str:
    return p.strftime("%b %Y")


def tile(label: str, value: str, sub: str = "", color: str = INK) -> str:
    return (f"<div style='border:1px solid {GRID};border-radius:8px;padding:10px 14px;background:#fff'>"
            f"<div style='font-size:13px;color:{INK_2}'>{label}</div>"
            f"<div style='font-size:24px;font-weight:700;color:{color};margin:2px 0'>{value}</div>"
            f"<div style='font-size:12px;color:{INK_2}'>{sub}</div></div>")


def noaa_words(cat: str, prob: int, var: str) -> tuple[str, str]:
    """('Leans wetter (50–60%)', color) from a CPC category."""
    if cat == "EC":
        return "Equal chances", NEUTRAL
    word = {"temp": {"Above": ("warmer", WARM), "Below": ("colder", COOL), "Near": ("near normal", NEUTRAL)},
            "prcp": {"Above": ("wetter", WET), "Below": ("drier", DRY), "Near": ("near normal", NEUTRAL)}}[var][cat]
    return f"Leans {word[0]} ({PROB_BINS.get(prob, f'{prob}%')})", word[1]


def chip(text: str, color: str) -> str:
    return (f"<span style='display:inline-block;padding:2px 8px;border-radius:10px;border:1.5px solid {color};"
            f"color:{INK};font-size:12px;white-space:nowrap'><span style='color:{color}'>●</span> {text}</span>")


def headline(m: pd.DataFrame, cpc: pd.DataFrame, enso: dict) -> str:
    w = seasonal.winter(m)
    djf = cpc[cpc["season"] == "DJF"].head(1)
    noaa_t = noaa_words(djf["temp_cat"].iloc[0], djf["temp_prob"].iloc[0], "temp")[0] if not djf.empty else "n/a"
    noaa_p = noaa_words(djf["prcp_cat"].iloc[0], djf["prcp_prob"].iloc[0], "prcp")[0] if not djf.empty else "n/a"
    t, r = w["temp_anom"], w["rain_anom"]
    pct_rain = 100 * r / w["rain_normal"] if w["rain_normal"] else np.nan
    colder = 100 - w["pct_warmer"]
    t_sub = (f"{w['pct_warmer']:.0f}% of the 51 ECMWF forecasts are warmer than normal, {colder:.0f}% colder"
             if pd.notna(w["pct_warmer"]) else "")
    r_sub = f"{w['pct_wetter']:.0f}% of the 51 ECMWF forecasts are wetter than normal" if pd.notna(w["pct_wetter"]) else ""
    tiles = "".join([
        tile("El Niño / La Niña", enso["status"] or "n/a", f"NOAA, {enso['issued']}"),
        tile("Winter temperature (Dec–Feb)", f"{t:+.1f}°F", f"vs normal. {t_sub}<br>NOAA: {noaa_t}",
             WARM if t >= 0.5 else COOL if t <= -0.5 else INK),
        tile("Winter rain (Dec–Feb)", f"{r:+.1f}\"", f"vs normal ({pct_rain:+.0f}%). {r_sub}<br>NOAA: {noaa_p}",
             WET if r > 0 else DRY),
    ])
    return ("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px;margin:12px 0'>"
            f"{tiles}</div><p><b>Bottom line:</b> {bottom_line(w, djf)}</p>")


def bottom_line(w: dict, djf: pd.DataFrame) -> str:
    parts = []
    wet_noaa = not djf.empty and djf["prcp_cat"].iloc[0] == "Above"
    if w["rain_anom"] > 0 and wet_noaa:
        parts.append("NOAA and ECMWF agree on a <b>wetter than normal winter</b>")
    elif w["rain_anom"] > 0:
        parts.append("ECMWF leans <b>wetter than normal</b>")
    elif w["rain_anom"] < 0:
        parts.append("ECMWF leans <b>drier than normal</b>")
    if w["temp_anom"] <= -0.5:
        parts.append("ECMWF leans <b>cooler</b> (cloudier, rainier days hold highs down)")
    elif w["temp_anom"] >= 0.5:
        parts.append("ECMWF leans <b>warmer</b>")
    else:
        parts.append("temperatures look close to normal overall")
    if not djf.empty and djf["temp_cat"].iloc[0] == "EC":
        parts.append("NOAA doesn't lean either way on temperature")
    return "; ".join(parts) + ". These are odds, not promises, and cold snaps can still happen in any winter."


def member_chart(m: pd.DataFrame, members: pd.DataFrame, column: str, title: str, unit: str,
                 up: str, down: str, up_word: str, down_word: str) -> go.Figure:
    """Each month: the 51 forecasts' difference from normal as dots, the average as a bar."""
    months = [p for p in members.index]
    labels = [p.strftime("%b %Y") for p in months]
    mean = m.set_index("month").loc[months, column]
    fig = go.Figure()
    fig.add_bar(x=labels, y=mean, showlegend=False, width=0.5,
                marker=dict(color=[up if v >= 0 else down for v in mean], cornerradius=4),
                hovertemplate=f"average %{{y:+.1f}}{unit} vs normal<extra></extra>")
    for color, word in ((up, up_word), (down, down_word)):   # legend entries for the two bar colors
        fig.add_bar(x=[None], y=[None], name=f"Average: {word} than normal", marker_color=color)
    xs, ys = [], []
    for label, (_, row) in zip(labels, members.iterrows()):
        xs += [label] * row.notna().sum()
        ys += row.dropna().tolist()
    # A box trace with its box hidden, just for the jittered points, so the 51 dots don't stack in one column.
    fig.add_box(x=xs, y=ys, name="Each of the 51 forecasts", boxpoints="all", jitter=0.6, pointpos=0,
                fillcolor="rgba(0,0,0,0)", line=dict(color="rgba(0,0,0,0)"), hoveron="points",
                marker=dict(size=6, color="rgba(11,11,11,0.3)"),
                hovertemplate=f"one forecast: %{{y:+.1f}}{unit}<extra></extra>")
    fig.update_layout(barmode="overlay")
    fig.add_hline(y=0, line=dict(color=INK, width=1))
    fig.add_annotation(x=1, xref="paper", y=0, text="normal", showarrow=False, xanchor="right", yanchor="bottom",
                       font=dict(color=INK_2, size=11))
    plots._style(fig, title).update_layout(height=360, yaxis_title=f"Difference from normal ({unit.strip()})",
                                           legend=dict(orientation="h", y=-0.15))
    return fig


def month_table(m: pd.DataFrame) -> str:
    rows = []
    for r in m.itertuples():
        warm = f"{r.pct_warmer:.0f}%" if pd.notna(r.pct_warmer) else "–"
        wet = f"{r.pct_wetter:.0f}%" if pd.notna(r.pct_wetter) else "–"
        rows.append(
            f"<tr><td style='text-align:left'>{month_name(r.month)}</td>"
            f"<td>{r.temperature_max24h_2m_normal:.0f}° / {r.temperature_min24h_2m_normal:.0f}°</td>"
            f"<td><b>{r.temperature_max24h_2m_mean:.0f}° / {r.temperature_min24h_2m_mean:.0f}°</b></td>"
            f"<td>{r.temperature_2m_anomaly:+.1f}°</td><td>{warm}</td>"
            f"<td>{r.precipitation_normal:.1f}\"</td><td><b>{r.precipitation_mean:.1f}\"</b></td>"
            f"<td>{r.precipitation_anomaly:+.1f}\"</td><td>{wet}</td></tr>")
    return ("<h3>Month by month (ECMWF)</h3><p>Highs and lows are monthly averages. \"Normal\" is the model's own "
            "long-term average for that month. Chances are the share of the 51 forecasts above normal "
            "(– where the current month is already partly over, or past the end of the daily data).</p>"
            "<div style='overflow-x:auto'><table><tr><th style='text-align:left'>Month</th><th>Normal high/low</th>"
            "<th>Forecast high/low</th><th>Temp vs normal</th><th>Chance warmer</th><th>Normal rain</th>"
            f"<th>Forecast rain</th><th>Rain vs normal</th><th>Chance wetter</th></tr>{''.join(rows)}</table></div>")


def noaa_section(cpc: pd.DataFrame, created: str) -> str:
    rows = []
    for r in cpc.head(6).itertuples():
        end_year = r.year + 1 if r.season in ("NDJ", "DJF") else r.year
        span = f"{seasonal.SEASON_MONTHS.get(r.season, r.season)} {r.year}" + (f"–{str(end_year)[2:]}" if end_year != r.year else "")
        t = chip(*noaa_words(r.temp_cat, r.temp_prob, "temp"))
        p = chip(*noaa_words(r.prcp_cat, r.prcp_prob, "prcp"))
        star = " <b>(winter)</b>" if r.season == "DJF" else ""
        rows.append(f"<tr><td style='text-align:left'>{span}{star}</td><td style='text-align:left'>{t}</td>"
                    f"<td style='text-align:left'>{p}</td></tr>")
    djf = cpc[cpc["season"] == "DJF"].head(1)
    maps = ""
    if not djf.empty:
        lead = int(djf["lead"].iloc[0])
        imgs = "".join(
            f"<a href='{seasonal.CPC_PAGE.format(lead=lead)}'><img src='{seasonal.CPC_MAP.format(lead=lead, var=v)}' "
            f"alt='NOAA winter {name} outlook map' style='width:100%;border:1px solid {GRID};border-radius:6px'></a>"
            for v, name in (("temp", "temperature"), ("prcp", "precipitation")))
        maps = ("<p>NOAA's winter maps for the whole country (click for NOAA's page):</p>"
                f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px'>{imgs}</div>")
    issued = pd.to_datetime(created, format="%m/%d/%Y")
    return (f"<h3>NOAA's official outlook for your location</h3><p>From the Climate Prediction Center, issued "
            f"{issued:%b} {issued.day}, {issued:%Y}. NOAA updates it on the third Thursday of each month.</p>"
            "<table><tr><th style='text-align:left'>Season</th><th style='text-align:left'>Temperature</th>"
            f"<th style='text-align:left'>Rain</th></tr>{''.join(rows)}</table>{maps}")


def details(summary: str, body: str) -> str:
    return (f"<details style='border:1px solid {GRID};border-radius:8px;padding:10px 18px;margin:10px 0;background:#fff'>"
            f"<summary style='cursor:pointer;font-weight:600'>{summary}</summary>"
            f"<div style='line-height:1.55'>{body}</div></details>")


EXPLAINERS = "".join([
    details("Why doesn't WeatherNext do seasons?", """
<p>WeatherNext (and every regular weather forecast) predicts the actual weather day by day. That only works for
about two weeks: small errors double every few days until a forecast for a specific day is no better than a guess.
WeatherNext 2 and 3 stop at 15 days for that reason, and Google DeepMind doesn't publish a seasonal version.</p>
<p>Seasonal forecasts ask a different question: not "will it rain on January 12?" but "will this January, on
the whole, be wetter or warmer than usual?" That can be predicted months ahead, because slow-moving things (mainly
ocean temperatures) tilt the odds for weeks of weather at once.</p>"""),
    details("What a seasonal outlook means: odds, not dates", """
<p>Think of every winter as falling into one of three equal bins, based on the last 30 years: the coldest third,
the middle third, and the warmest third. With no other information, each is a 33% chance.</p>
<p>A seasonal outlook shifts those odds. "Leans wetter, 50–60%" means the wettest-third bin is now about a 50–60%
chance and the driest third much less likely. It does <b>not</b> mean it will rain on 50–60% of days, or that every
week will be wet. A wet winter can still have dry spells, and a mild winter can still bring a hard freeze.</p>"""),
    details("El Niño, La Niña, and your winter on the Gulf Coast", """
<p><b>El Niño</b> is a warming of the tropical Pacific Ocean every few years; <b>La Niña</b> is the opposite,
cooling. They shift where the jet stream runs, which steers storms across North America.</p>
<ul>
<li><b>El Niño winters</b> push the southern (subtropical) jet stream across the Gulf Coast. That means more storm
systems, more rain, more clouds, and daytime highs that often run cooler than usual. Severe weather, including
tornadoes, is also more common in the Gulf states during strong El Niño winters and early springs.</li>
<li><b>La Niña winters</b> usually do the opposite here: warmer and drier than normal, with higher wildfire and
drought risk by spring.</li>
<li>For north Florida and the Gulf Coast, this is one of the most reliable seasonal signals anywhere in the US,
and the stronger the event, the more consistent the effect. Past strong El Niño winters, like 1982–83 and 1997–98,
were notably wet across the region.</li>
<li>El Niño also tends to <b>suppress Atlantic hurricanes</b>, because it strengthens the upper-level winds that
tear developing storms apart. That matters most from August to October.</li>
</ul>"""),
    details("How to read NOAA's outlook", """
<p>NOAA's Climate Prediction Center draws three kinds of areas on its maps:</p>
<ul>
<li><b>Above</b> (red for temperature, green for rain): the warm or wet third is favored, with the shown probability.</li>
<li><b>Below</b> (blue for temperature, brown for rain): the cold or dry third is favored.</li>
<li><b>EC, "equal chances"</b>: no lean either way. This does <i>not</i> mean "normal weather"; it means the signals
don't favor any bin, so it stays 33/33/33.</li>
</ul>
<p>NOAA's outlook is put together by forecasters from many models (ECMWF among them), El Niño and La Niña,
long-term trends, and soil moisture. It's the official US forecast.</p>"""),
    details("About the ECMWF forecast", """
<p>The European Centre for Medium-Range Weather Forecasts (ECMWF) runs SEAS5, a physics-based model of the whole
atmosphere and ocean, once a month (new runs appear around the 5th). It runs 51 slightly different versions out to
7 months. This page gets it free from <a href="https://open-meteo.com/en/docs/seasonal-forecast-api">Open-Meteo</a>.</p>
<ul>
<li><b>"Normal"</b> is the model's own long-term average for that month. Comparing the model with itself cancels
out most of its biases (for example, if it always runs a degree cool somewhere).</li>
<li>Each month's chart shows all 51 forecasts as dots. When most dots sit on one side of the line, the model is
confident in that direction; when they're spread across both sides, it isn't.</li>
<li>The first few weeks come from ECMWF's daily-updated 46-day system, and the months after that come from SEAS5.</li>
</ul>"""),
    details("How much to trust it", """
<ul>
<li><b>Rain in El Niño winters</b> on the Gulf Coast is about as predictable as seasonal forecasts get.</li>
<li><b>Temperature</b> is harder: long-term warming pushes winters warmer while El Niño's clouds and rain push
daytime highs cooler, so the two can cancel out. That is often why NOAA shows "equal chances" here.</li>
<li><b>Individual cold snaps and freezes</b> can't be predicted months ahead. For those, watch the 15-day local
forecast (F in the viewer) as the season goes on.</li>
<li>The outlook improves each month as winter gets closer; this page always pulls the newest NOAA and ECMWF
issues.</li>
</ul>"""),
])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", help="5-digit US ZIP code")
    args = ap.parse_args()

    loc = forecast.geocode_zip(args.zip)
    print(f"Winter outlook for {loc['place']} ({loc['zip']})...")
    enso = seasonal.enso()
    cpc, created = seasonal.cpc_outlook(loc["lat"], loc["lon"])
    m = seasonal.ecmwf(loc["lat"], loc["lon"])
    w = seasonal.winter(m)
    print(f"  ENSO: {enso['status']} ({enso['issued']})")
    print(f"  ECMWF Dec–Feb: {w['temp_anom']:+.1f}°F, rain {w['rain_anom']:+.1f}\" vs normal")
    djf = cpc[cpc["season"] == "DJF"].head(1)
    if not djf.empty:
        print(f"  NOAA Dec–Feb: temperature {noaa_words(djf['temp_cat'].iloc[0], djf['temp_prob'].iloc[0], 'temp')[0]}, "
              f"rain {noaa_words(djf['prcp_cat'].iloc[0], djf['prcp_prob'].iloc[0], 'prcp')[0]}")

    enso_box = (f"<div style='border-left:4px solid {WARM if 'Niño' in enso['status'] else COOL if 'Niña' in enso['status'] else NEUTRAL};"
                f"background:#fff;padding:10px 14px;margin:12px 0'><b>{enso['status']}</b> "
                f"<span style='color:{INK_2}'>(NOAA, {enso['issued']})</span><br>{enso['synopsis']} "
                f"<a href='{enso['url']}'>NOAA's full discussion</a>"
                + (f" <span style='color:{INK_2}'>Next update {enso['next']}.</span>" if enso["next"] else "") + "</div>")
    figs = [
        headline(m, cpc, enso),
        enso_box,
        EXPLAINERS,
        noaa_section(cpc, created),
        "<h3>ECMWF's 51 forecasts, month by month</h3>",
        member_chart(m, m.attrs["members_t"], "temperature_2m_anomaly",
                     "Temperature vs normal (average of each month)", "°F", WARM, COOL, "warmer", "colder"),
        member_chart(m, m.attrs["members_p"], "precipitation_anomaly",
                     "Rain vs normal (monthly total)", " in", WET, DRY, "wetter", "drier"),
        month_table(m),
    ]
    out = plots.write_report(
        figs, ROOT / "outputs" / f"winter_{loc['zip']}.html", f"Winter outlook for {loc['place']} ({loc['zip']})",
        notes="NOAA Climate Prediction Center outlooks and El Niño status, plus the 51-member ECMWF seasonal "
              "forecast. Seasonal outlooks give the odds of a warmer/colder or wetter/drier season, not day-to-day weather.")
    print(f"\nOutlook written: {out}")


if __name__ == "__main__":
    main()
