"""How past forecasts did: WeatherNext 3, the operational WeatherNext model and NHC, against the observed track.

For forecasts made N hours before the latest observation, every forecast point that has already "happened"
is compared with where the storm actually was at that moment (observed track interpolated to the minute).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from . import nhc, weatherlab
from .verify import great_circle_km

MI_PER_KM = 0.621371
MPH_PER_KT = 1.15078
SOURCES = {"WNV3": "WeatherNext 3", "OPER": "Operational model", "NHC": "NHC official"}
LAGS = (24, 48, 72, 96, 120)


def _interp_obs(obs: pd.DataFrame, times: pd.Series) -> pd.DataFrame:
    """Observed lat/lon/wind at arbitrary times (NaN outside the observed period)."""
    t_obs = obs["valid_time"].astype("int64").to_numpy()
    t = pd.to_datetime(times).astype("int64").to_numpy()
    inside = (t >= t_obs.min()) & (t <= t_obs.max())
    out = {}
    for col in ("lat", "lon", "wind_kt"):
        vals = np.interp(t, t_obs, obs[col].astype(float).to_numpy())
        out[f"obs_{col}"] = np.where(inside, vals, np.nan)
    return pd.DataFrame(out, index=times.index)


def gather(storm: str, obs: pd.DataFrame, lags=LAGS, anchor=None) -> list[dict]:
    """For each lag: the three forecasts made that long before `anchor` (default: the latest observation),
    with errors. For a finished storm the anchor is usually landfall."""
    if obs.empty:
        return []
    latest = pd.Timestamp(anchor) if anchor is not None else obs["valid_time"].max()
    first = obs["valid_time"].min()
    official = nhc.official_history(storm)
    runs = []
    for lag in lags:
        init = (latest - timedelta(hours=lag)).floor("6h")
        if init < first:
            continue
        sources = {}
        for model in ("WNV3", "OPER"):
            df = weatherlab.load(model, init.to_pydatetime(), storm=storm)
            if not df.empty:
                sources[model] = df[["valid_time", "lead_time_hours", "lat", "lon", "wind_kt"]].copy()
        if not official.empty:
            df = official[official["init_time"] == init]
            if not df.empty:
                sources["NHC"] = df[["valid_time", "lead_time_hours", "lat", "lon", "wind_kt"]].copy()
        for name, df in sources.items():
            df = df.sort_values("valid_time").reset_index(drop=True)
            df = pd.concat([df, _interp_obs(obs, df["valid_time"])], axis=1)
            df["verified"] = df["obs_lat"].notna()
            df["err_mi"] = np.where(df["verified"], great_circle_km(df["lat"], df["lon"], df["obs_lat"],
                                                                    df["obs_lon"]) * MI_PER_KM, np.nan)
            sources[name] = df
        if sources:
            runs.append({"lag": lag, "init": init, "latest": latest, "sources": sources})
    return runs


def _at(df: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """The forecast row valid at time t, interpolated between forecast points if t falls between them."""
    exact = df[df["valid_time"] == t]
    if not exact.empty or not df["verified"].any():
        return exact
    before, after = df[df["valid_time"] < t].tail(1), df[df["valid_time"] > t].head(1)
    if before.empty or after.empty:
        return exact
    w = (t - before["valid_time"].iloc[0]) / (after["valid_time"].iloc[0] - before["valid_time"].iloc[0])
    row = before.iloc[0].copy()
    for col in ("lat", "lon", "wind_kt", "obs_lat", "obs_lon", "obs_wind_kt"):
        row[col] = before[col].iloc[0] + w * (after[col].iloc[0] - before[col].iloc[0])
    row["valid_time"] = t
    row["err_mi"] = float(great_circle_km(row["lat"], row["lon"], row["obs_lat"], row["obs_lon"])) * MI_PER_KM
    return pd.DataFrame([row])


def scoreboard_html(runs: list[dict], name: str, anchor_label: str = "") -> str:
    """Table: for each forecast time, how far each source's forecast was from the latest observed position,
    plus the average miss over all verified points."""
    if not runs:
        return ""
    latest = runs[0]["latest"]
    head = "".join(f"<th>{SOURCES[s]}</th>" for s in SOURCES)
    rows = []
    for r in runs:
        cells = []
        for s in SOURCES:
            df = r["sources"].get(s)
            if df is None:
                cells.append("<td style='color:#8a8984'>n/a</td>")
                continue
            at_latest = _at(df, latest)
            miss = f"{at_latest['err_mi'].iloc[0]:.0f} mi" if not at_latest.empty and pd.notna(at_latest["err_mi"].iloc[0]) else "–"
            avg = df.loc[df["verified"] & (df["lead_time_hours"] > 0), "err_mi"].mean()
            wind = ""
            if not at_latest.empty and pd.notna(at_latest["wind_kt"].iloc[0]) and pd.notna(at_latest["obs_wind_kt"].iloc[0]):
                d = (at_latest["wind_kt"].iloc[0] - at_latest["obs_wind_kt"].iloc[0]) * MPH_PER_KT
                wind = f"<br><span style='color:#52514e'>wind {'+' if d >= 0 else '−'}{abs(d):.0f} mph</span>"
            cells.append(f"<td><b>{miss}</b>{wind}<br><span style='color:#52514e'>avg {avg:.0f} mi</span></td>"
                         if pd.notna(avg) else f"<td><b>{miss}</b>{wind}</td>")
        rows.append(f"<tr><td style='text-align:left'><b>{r['lag']} h before</b><br>"
                    f"<span style='color:#52514e'>{r['init']:%a %b %d %HZ}</span></td>{''.join(cells)}</tr>")
    return (f"<h3>Scoreboard: how far off each forecast was</h3>"
            f"<p>Big number: distance between the forecast position and where {name} actually was "
            f"{anchor_label or 'at its latest observed position'} ({latest:%a %b %d %HZ}). \"wind\" is the forecast minus the actual max sustained wind at that time. "
            f"\"avg\" is the average miss over every forecast point that has already happened. Smaller is better.</p>"
            f"<table><tr><th style='text-align:left'>Forecast made</th>{head}</tr>{''.join(rows)}</table>")
