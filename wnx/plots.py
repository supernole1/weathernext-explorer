"""Plotly figures for cyclone forecasts. All figures are interactive (hover for values)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# Fixed categorical order: color follows the model, never its rank.
MODEL_COLORS = {"WNV3": "#2a78d6", "OPER": "#1baf7a", "FNV3P2": "#eda100",
                "FNV3P1": "#e87ba4", "FNV3_LARGE_ENSEMBLE": "#4a3aa7"}
OBS_COLOR = "#eb6834"
MPH_PER_KT = 1.15078
MI_PER_KM = 0.621371
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
            ys += list(m["wind_kt"] * MPH_PER_KT) + [None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=1, color=MEMBER_COLOR),
                                 hoverinfo="skip", name="Ensemble members"))
    for (model, init), m in means.groupby(["model", "init_time"]):
        fig.add_trace(go.Scatter(x=m["valid_time"], y=m["wind_kt"] * MPH_PER_KT, mode="lines",
                                 line=dict(width=2, color=MODEL_COLORS.get(model, "#2a78d6")),
                                 name=f"{model} mean, init {init:%m-%d %HZ}", legendgroup=model))
    if obs is not None and not obs.empty:
        fig.add_trace(go.Scatter(x=obs["valid_time"], y=obs["wind_kt"] * MPH_PER_KT, mode="lines+markers",
                                 line=dict(width=2.5, color=OBS_COLOR), marker=dict(size=8),
                                 name=f"Observed ({obs.attrs.get('source', 'IBTrACS')})"))
    if official is not None and official.track:
        pts = [p for p in official.track if p.valid_time and p.wind_kt is not None]
        fig.add_trace(go.Scatter(x=[p.valid_time for p in pts], y=[p.wind_kt * MPH_PER_KT for p in pts],
                                 mode="lines+markers", line=dict(width=2.5, color=INK, dash="dash"),
                                 marker=dict(size=8, color="white", line=dict(width=2, color=INK)),
                                 name=f"NHC official (adv {official.advisory})"))
    # Saffir-Simpson thresholds as recessive reference lines.
    for mph, label in [(74, "Cat 1"), (111, "Cat 3"), (157, "Cat 5")]:
        fig.add_hline(y=mph, line=dict(color="#c3c2b7", width=1, dash="dot"),
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(color=INK_2, size=11))
    _style(fig, title).update_layout(height=420, hovermode="x unified",
                                     yaxis_title="Max sustained wind (mph)")
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


BUTTON_CSS = ("font:600 14px system-ui,sans-serif;padding:8px 16px;border-radius:6px;cursor:pointer;"
              "border:1px solid #1c5cab;")
REPO_URL = "https://github.com/supernole1/weathernext-explorer"

# Refresh re-runs the scripts through scripts/serve.py. Share sends the clean copy in outputs/share/
# (see write_report) through the device's share menu (email, text, WhatsApp, Nearby Share...).
# Deliberately no Blob downloads or embedded iframes anywhere: email virus scanners treat those
# patterns as "HTML smuggling" and block the attachment.
TOOLBAR = """
<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0 8px">
<button id="wnx-refresh" style="{css}background:#2a78d6;color:#fff">&#x27F3; Refresh everything</button>
<button id="wnx-share" style="{css}background:#fff;color:#1c5cab" title="Send this report to someone">
<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
 stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px">
<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
<line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/><line x1="15.4" y1="6.5" x2="8.6" y2="10.5"/></svg>Share</button>
<span id="wnx-status" style="color:#52514e;font-size:13px">Data as of {built}</span></div>
<script>
(function () {
  const refreshable = {refreshable};
  const shareUrl = "share/{stem}.html", fileName = "{file_name}", title = "{title}";
  const btn = document.getElementById("wnx-refresh"), share = document.getElementById("wnx-share");
  const st = document.getElementById("wnx-status");
  const live = location.protocol.startsWith("http");

  // Fetch the clean share copy up front, so the share menu opens instantly on click.
  let shareFile = null;
  if (live) fetch(shareUrl, {cache: "no-store"}).then(r => r.ok ? r.blob() : null)
    .then(b => { if (b) shareFile = new File([b], fileName, {type: "text/html"}); }).catch(() => {});

  function showManual() {
    st.innerHTML = live
      ? "Your browser can&#39;t share files directly. <a href='" + shareUrl + "' download='" + fileName +
        "'>Save the report file</a>, then attach it to an email or text."
      : "To share, attach this file from the project folder: outputs / share / {stem}.html";
  }

  share.onclick = async function () {
    if (!shareFile || !(navigator.canShare && navigator.canShare({files: [shareFile]}))) return showManual();
    const text = title + " (snapshot {built}). Open the attached file in a web browser. " +
                 "On a phone, download it first, then open it with Chrome.";
    st.textContent = "Opening your share menu...";
    const t0 = Date.now();
    try {
      await navigator.share({files: [shareFile], title: title, text: text});
      st.textContent = "Shared " + fileName + ".";
    } catch (e) {
      // A real "cancel" takes the user a moment; an instant AbortError means the menu failed to open.
      if (e.name === "AbortError" && Date.now() - t0 > 1500) st.textContent = "Share cancelled.";
      else showManual();
    }
  };

  if (!refreshable) { btn.style.display = "none"; return; }
  if (!live) {
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

# The shared copy has no toolbar script at all, just a note.
SNAPSHOT_BAR = """<p style="background:#fff;border:1px solid #e6e5e0;border-radius:8px;padding:10px 14px">
<b>Snapshot from {built}.</b> Forecasts change every few hours. For live updates, use the free
<a href="{repo}">WeatherNext Explorer</a> storm viewer, and always check the
<a href="https://www.nhc.noaa.gov/">National Hurricane Center</a>.</p>"""


def inline_map(fig, height: int = 650) -> str:
    """A folium figure as plain page content: Leaflet + the map's own div/style/script, no iframe.
    Skips folium's default header (bootstrap, page-wide html/body styles) so the report's styling survives."""
    fig.render()
    header = fig.header.render()
    keep = [line for line in header.splitlines() if "/leaflet@" in line]  # leaflet.js and leaflet.css
    keep += re.findall(r"<style>\s*#map_\w+\s*\{.*?</style>", header, re.S)
    keep.append("<style>.leaflet-control-layers{font-size:12px;line-height:1.5}</style>")
    return (f"{''.join(keep)}<div style=\"height:{height}px;position:relative\">{fig.html.render()}</div>"
            f"<script>{fig.script.render()}</script>")


def _page(heading: str, bar: str, notes: str, body: str, table_html: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{heading}</title>
<style>body{{font-family:system-ui,sans-serif;background:{SURFACE};color:{INK};max-width:1100px;
margin:0 auto;padding:16px}} p,li{{color:{INK_2}}} table{{border-collapse:collapse;font-size:13px}}
td,th{{padding:4px 10px;border-bottom:1px solid {GRID};text-align:right}}</style></head><body>
<h1>{heading}</h1>{bar}<p>{notes}</p>{body}{table_html}
<p style="font-size:12px">Forecast data: Google DeepMind Weather Lab (CC BY 4.0 for data &gt;48h old).
Observed tracks: NHC best track, or NOAA IBTrACS outside NHC's area. NHC data: NOAA. Not an official forecast.</p></body></html>"""


def write_report(figs: list, path: Path, heading: str, notes: str = "",
                 table_html: str = "", refreshable: bool = True) -> Path:
    """Write the live report to `path` and a clean share copy to `path.parent/share/`.

    figs may mix Plotly figures, folium figures and raw HTML strings."""
    parts, plotly_loaded = [], False
    for f in figs:
        if isinstance(f, go.Figure):
            parts.append(f.to_html(full_html=False, include_plotlyjs=False if plotly_loaded else "cdn"))
            plotly_loaded = True
        elif isinstance(f, str):
            parts.append(f)
        else:
            height = getattr(f, "height", 650)
            parts.append(inline_map(f, height if isinstance(height, int) else 650))
    body = "".join(parts)
    now = datetime.now().astimezone()
    built = f"{now:%a %b %d, %I:%M %p} local ({now.astimezone(timezone.utc):%H:%M} UTC)"
    file_name = f"{path.stem}_{now.astimezone(timezone.utc):%Y-%m-%d_%H%MZ}.html"
    bar = (TOOLBAR.replace("{css}", BUTTON_CSS).replace("{built}", built)
           .replace("{refreshable}", "true" if refreshable else "false").replace("{stem}", path.stem)
           .replace("{file_name}", file_name).replace("{title}", heading.replace('"', "'")))
    snapshot = SNAPSHOT_BAR.replace("{built}", built).replace("{repo}", REPO_URL)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_page(heading, bar, notes, body, table_html), encoding="utf-8")
    share = path.parent / "share" / path.name
    share.parent.mkdir(exist_ok=True)
    share.write_text(_page(heading, snapshot, notes, body, table_html), encoding="utf-8")
    return path
