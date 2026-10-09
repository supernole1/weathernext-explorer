"""Plotly figures for cyclone forecasts. All figures are interactive (hover for values)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# Fixed categorical order: color follows the model, never its rank.
MODEL_COLORS = {"WNV3": "#2a78d6", "OPER": "#1baf7a", "FNV3P2": "#eda100",
                "FNV3P1": "#e87ba4", "FNV3_LARGE_ENSEMBLE": "#4a3aa7"}
OBS_COLOR = "#eb6834"
MEMBER_COLOR = "rgba(42,120,214,0.18)"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=16, color=INK)),
                      paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                      font=dict(family="system-ui, sans-serif", color=INK_2, size=12),
                      legend=dict(orientation="h", y=-0.12), margin=dict(l=50, r=20, t=60, b=50),
                      hovermode="closest")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def intensity_plume(members: pd.DataFrame, means: pd.DataFrame, obs: pd.DataFrame | None,
                    title: str, official=None) -> go.Figure:
    """Max sustained wind over time: members, mean(s), observed, and NHC official forecast."""
    fig = go.Figure()
    if not members.empty:
        xs, ys = [], []
        for _, m in members.groupby(["model", "init_time", "sample"]):
            xs += list(m["valid_time"]) + [None]
            ys += list(m["wind_kt"]) + [None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=1, color=MEMBER_COLOR),
                                 hoverinfo="skip", name="Ensemble members"))
    for (model, init), m in means.groupby(["model", "init_time"]):
        fig.add_trace(go.Scatter(x=m["valid_time"], y=m["wind_kt"], mode="lines",
                                 line=dict(width=2, color=MODEL_COLORS.get(model, "#2a78d6")),
                                 name=f"{model} mean, init {init:%m-%d %HZ}", legendgroup=model))
    if obs is not None and not obs.empty:
        fig.add_trace(go.Scatter(x=obs["valid_time"], y=obs["wind_kt"], mode="lines+markers",
                                 line=dict(width=2.5, color=OBS_COLOR), marker=dict(size=8),
                                 name="Observed (IBTrACS)"))
    if official is not None and official.track:
        pts = [p for p in official.track if p.valid_time and p.wind_kt is not None]
        fig.add_trace(go.Scatter(x=[p.valid_time for p in pts], y=[p.wind_kt for p in pts],
                                 mode="lines+markers", line=dict(width=2.5, color=INK, dash="dash"),
                                 marker=dict(size=8, color="white", line=dict(width=2, color=INK)),
                                 name=f"NHC official (adv {official.advisory})"))
    # Saffir-Simpson thresholds as recessive reference lines.
    for kt, label in [(64, "Cat 1"), (96, "Cat 3"), (137, "Cat 5")]:
        fig.add_hline(y=kt, line=dict(color="#c3c2b7", width=1, dash="dot"),
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(color=INK_2, size=11))
    _style(fig, title).update_layout(height=420, hovermode="x unified",
                                     yaxis_title="Max sustained wind (kt)")
    return fig


def error_chart(errors: pd.DataFrame, column: str, ylabel: str, title: str) -> go.Figure:
    fig = go.Figure()
    for model, e in errors.groupby("model"):
        fig.add_trace(go.Scatter(x=e["lead_time_hours"], y=e[column], mode="lines+markers",
                                 line=dict(width=2, color=MODEL_COLORS.get(model, "#2a78d6")),
                                 marker=dict(size=8), name=model, customdata=e["cases"],
                                 hovertemplate="+%{x}h: %{y:.0f} (n=%{customdata})"))
    _style(fig, title).update_layout(height=380, hovermode="x unified", yaxis_title=ylabel,
                                     xaxis_title="Lead time (hours)")
    fig.update_xaxes(dtick=24)
    return fig


REFRESH_BAR = """
<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:4px 0 8px">
<button id="wnx-refresh" style="font:600 14px system-ui,sans-serif;padding:8px 16px;border-radius:6px;
 border:1px solid #1c5cab;background:#2a78d6;color:#fff;cursor:pointer">&#x27F3; Refresh everything</button>
<span id="wnx-status" style="color:#52514e;font-size:13px">Data as of {built}</span></div>
<script>
(function () {
  const btn = document.getElementById("wnx-refresh"), st = document.getElementById("wnx-status");
  if (!location.protocol.startsWith("http")) {
    btn.disabled = true; btn.style.opacity = 0.5; btn.style.cursor = "default";
    st.textContent += ". Open this report from storm_report.bat to turn on Refresh.";
    return;
  }
  btn.onclick = async function () {
    btn.disabled = true;
    st.textContent = "Downloading the newest forecasts, NHC advisory and radar (about 30 seconds)...";
    try {
      const r = await fetch("/refresh/" + location.pathname.split("/").pop(), {method: "POST"});
      const j = await r.json();
      if (j.ok) { location.reload(); return; }
      st.textContent = "Refresh failed: " + j.error;
    } catch (e) {
      st.textContent = "The refresh helper isn't running. Start storm_report.bat and open the report from there.";
    }
    btn.disabled = false;
  };
})();
</script>
"""


def write_report(figs: list, path: Path, heading: str, notes: str = "",
                 table_html: str = "", refreshable: bool = True) -> Path:
    """figs may mix Plotly figures, folium maps (embedded as iframes) and raw HTML strings."""
    parts, plotly_loaded = [], False
    for f in figs:
        if isinstance(f, go.Figure):
            parts.append(f.to_html(full_html=False, include_plotlyjs=False if plotly_loaded else "cdn"))
            plotly_loaded = True
        elif isinstance(f, str):
            parts.append(f)
        else:
            parts.append(f._repr_html_())
    now = datetime.now().astimezone()
    built = f"{now:%a %b %d, %I:%M %p} local ({now.astimezone(timezone.utc):%H:%M} UTC)"
    bar = REFRESH_BAR.replace("{built}", built) if refreshable else f"<p>Built {built}</p>"
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{heading}</title>
<style>body{{font-family:system-ui,sans-serif;background:{SURFACE};color:{INK};max-width:1100px;
margin:0 auto;padding:16px}} p,li{{color:{INK_2}}} table{{border-collapse:collapse;font-size:13px}}
td,th{{padding:4px 10px;border-bottom:1px solid {GRID};text-align:right}}</style></head><body>
<h1>{heading}</h1>{bar}<p>{notes}</p>{''.join(parts)}{table_html}
<p style="font-size:12px">Forecast data: Google DeepMind Weather Lab (CC BY 4.0 for data &gt;48h old).
Observations: NOAA IBTrACS v04r01.</p></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
