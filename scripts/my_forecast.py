"""Local forecast page for a US ZIP code from the 64-member WeatherNext 2 ensemble.

    python scripts/my_forecast.py 32578
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

from wnx import forecast, plots  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLUE, BLUE_BAND, INK, INK_2 = "#2a78d6", "rgba(42,120,214,0.18)", "#0b0b0b", "#52514e"


def day_label(date, month: bool = True) -> str:
    """'Sat Oct 10' (no leading zero; strftime's %-d isn't available on Windows)."""
    t = pd.Timestamp(date)
    return f"{t:%a %b} {t.day}" if month else f"{t:%a} {t.day}"


def band_chart(bands: pd.DataFrame, title: str, unit: str, ytitle: str) -> go.Figure:
    """Median line with the 10-90% range of the 64 forecasts shaded."""
    fig = go.Figure([
        go.Scatter(x=bands["time"], y=bands["p90"], mode="lines", line=dict(width=0), hoverinfo="skip",
                   showlegend=False),
        go.Scatter(x=bands["time"], y=bands["p10"], mode="lines", line=dict(width=0), fill="tonexty",
                   fillcolor=BLUE_BAND, name="Likely range (80% of forecasts)",
                   customdata=bands["p90"], hovertemplate=f"range %{{y:.0f}}–%{{customdata:.0f}}{unit}<extra></extra>"),
        go.Scatter(x=bands["time"], y=bands["p50"], mode="lines", line=dict(width=2.5, color=BLUE),
                   name="Most likely (median)", hovertemplate=f"%{{y:.0f}}{unit}<extra></extra>"),
    ])
    plots._style(fig, title).update_layout(height=340, hovermode="x unified", yaxis_title=ytitle,
                                           legend=dict(orientation="h", y=-0.18))
    fig.update_xaxes(tickformat="%a %-d<br>%-I %p", dtick=12 * 3600 * 1000)
    return fig


def rain_chart(days: pd.DataFrame) -> go.Figure:
    labels = [day_label(d, month=False) for d in days["date"]]
    fig = go.Figure(go.Bar(
        x=labels, y=days["rain_chance"], marker=dict(color=BLUE, cornerradius=4),
        customdata=days[["rain_median", "rain_hi"]].round(2),
        hovertemplate="%{y:.0f}% of forecasts bring rain<br>typical %{customdata[0]:.2f}\", "
                      "up to %{customdata[1]:.2f}\"<extra></extra>"))
    plots._style(fig, "Chance of rain by day (share of the 64 forecasts with measurable rain)").update_layout(
        height=300, yaxis=dict(title="Chance of rain (%)", range=[0, 100]), bargap=0.35)
    return fig


def day_cards(days: pd.DataFrame) -> str:
    cards = []
    for i, d in days.head(7).iterrows():
        name = "Rest of today" if d["partial"] else ("Today" if i == 0 else day_label(d["date"]))
        rain = f"{d['rain_chance']:.0f}%"
        if d["rain_chance"] >= 10 and d["rain_hi"] >= 0.01:
            rain += f" <span style='color:{INK_2}'>(up to {d['rain_hi']:.2f}\")</span>"
        cards.append(f"""<div style="border:1px solid #e6e5e0;border-radius:8px;padding:10px 12px;background:#fff">
<div style="font-weight:700;color:{INK}">{name}</div>
<div style="font-size:13px;color:{INK_2};margin-bottom:6px">{forecast.sky(d['clouds'], d['rain_chance'])}</div>
<div style="font-size:24px;font-weight:700;color:{INK}">{d['high']:.0f}°<span style="font-size:15px;color:{INK_2};font-weight:600"> / {d['low']:.0f}°</span></div>
<div style="font-size:12px;color:{INK_2}">high {d['high_lo']:.0f}–{d['high_hi']:.0f}°, low {d['low_lo']:.0f}–{d['low_hi']:.0f}°</div>
<div style="font-size:13px;color:{INK};margin-top:6px">Rain {rain}</div>
<div style="font-size:13px;color:{INK}">Wind to {d['wind']:.0f} mph <span style="color:{INK_2}">(up to {d['wind_hi']:.0f})</span></div>
</div>""")
    return ("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:8px;"
            f"margin:12px 0 18px'>{''.join(cards)}</div>")


def outlook_table(days: pd.DataFrame) -> str:
    rows = "".join(
        f"<tr><td style='text-align:left'>{day_label(d['date'])}</td><td>{d['high']:.0f}° "
        f"<span style='color:{INK_2}'>({d['high_lo']:.0f}–{d['high_hi']:.0f})</span></td><td>{d['low']:.0f}°</td>"
        f"<td>{d['rain_chance']:.0f}%</td><td>{d['wind']:.0f} mph</td>"
        f"<td style='text-align:left'>{forecast.sky(d['clouds'], d['rain_chance'])}</td></tr>"
        for _, d in days.iloc[7:].iterrows())
    return ("<h3>Days 8–15 outlook</h3><p>Further out, the 64 forecasts spread apart, so treat these as trends.</p>"
            "<table><tr><th style='text-align:left'>Day</th><th>High (likely range)</th><th>Low</th>"
            f"<th>Rain chance</th><th>Wind</th><th style='text-align:left'>Sky</th></tr>{rows}</table>") if rows else ""


EXPLAINER = """
<details style="border:1px solid #e6e5e0;border-radius:8px;padding:10px 18px;margin:16px 0;background:#fff">
<summary style="cursor:pointer;font-weight:600">How this forecast works</summary>
<ul style="line-height:1.55">
<li><b>64 forecasts, not one.</b> This comes from Google DeepMind's <b>WeatherNext 2</b>, which runs 64 slightly
different versions every 6 hours. The big numbers are the <b>median</b> (the middle of the 64), and the smaller
ranges cover the middle 80% of them, so 1 in 10 forecasts is warmer and 1 in 10 is cooler than the range.</li>
<li><b>Chance of rain</b> is the share of the 64 forecasts that bring at least 0.01" that day. "Up to" amounts
are what the wettest 10% of forecasts show.</li>
<li><b>Resolution:</b> about 25 km (15 miles), with model steps every 6 hours that are smoothed to hourly.
Very local effects like sea breezes and single thunderstorms aren't resolved, and the daily high can run a
degree or two low because the model only samples every 6 hours.</li>
<li><b>Not included:</b> wind gusts (this model doesn't produce them) and official alerts. Check the
<a href="https://www.weather.gov/">National Weather Service</a> for warnings.</li>
<li>Data via <a href="https://open-meteo.com/en/docs/google-weathernext-api">Open-Meteo</a>, free for non-commercial use.
WeatherNext 3 (hourly, about 5 km) will replace this once Google Cloud access is set up.</li>
</ul></details>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", help="5-digit US ZIP code")
    args = ap.parse_args()

    loc = forecast.geocode_zip(args.zip)
    print(f"Forecast for {loc['place']} ({loc['zip']})...")
    df, tz = forecast.ensemble(loc["lat"], loc["lon"])
    now = pd.Timestamp.now(tz=tz).tz_localize(None) if tz else pd.Timestamp.now()
    df = forecast.upcoming(df, now)
    days = forecast.daily(df)
    week = df[df["time"] < now + pd.Timedelta(days=7)]

    for _, d in days.head(7).iterrows():
        print(f"  {day_label(d['date'])}: {d['high']:.0f}/{d['low']:.0f}°F, rain {d['rain_chance']:.0f}%, "
              f"wind {d['wind']:.0f} mph")

    figs = [
        day_cards(days),
        band_chart(forecast.hourly_bands(week, "temperature_2m"), "Temperature, next 7 days", "°F", "°F"),
        rain_chart(days),
        band_chart(forecast.hourly_bands(week, "wind_speed_10m"), "Sustained wind, next 7 days", " mph", "mph"),
        outlook_table(days),
        EXPLAINER,
    ]
    out = plots.write_report(
        figs, ROOT / "outputs" / f"forecast_{loc['zip']}.html", f"Forecast for {loc['place']} ({loc['zip']})",
        notes=f"From the 64-member WeatherNext 2 ensemble (Google DeepMind). Times are local ({tz}). "
              "Big numbers are the most likely values; small ranges show the spread of the 64 forecasts.")
    print(f"\nForecast written: {out}")


if __name__ == "__main__":
    main()
