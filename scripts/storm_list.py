"""This season's storms (Atlantic, East and Central Pacific), with a button to open each one's forecast report.

    python scripts/storm_list.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wnx import plots, season  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GRID, INK_2 = "#e6e5e0", "#52514e"
STRENGTH_COLORS = {"Category 5 hurricane": "#8b0000", "Category 4 hurricane": "#c1121f",
                   "Category 3 hurricane": "#e85d04", "Category 2 hurricane": "#f48c06",
                   "Category 1 hurricane": "#faa307", "Tropical storm": "#2a78d6", "Tropical depression": "#8a8984"}

OPEN_JS = """
<script>
(function () {
  const st = document.getElementById("wnx-list-status");
  document.querySelectorAll("button[data-storm]").forEach(function (b) {
    b.onclick = async function () {
      const id = b.dataset.storm, name = b.dataset.name, page = id + "_report.html";
      if (!location.protocol.startsWith("http")) {
        st.textContent = "Open this list from storm_report.bat (option L) to build reports.";
        return;
      }
      document.querySelectorAll("button[data-storm]").forEach(x => x.disabled = true);
      st.textContent = "Building the " + name + " report (about a minute the first time)...";
      try {
        const r = await fetch("/refresh/" + page, {method: "POST"});
        const j = await r.json();
        if (j.ok) { location.href = page; return; }
        st.textContent = name + ": " + j.error;
      } catch (e) {
        st.textContent = "The viewer isn't running. Start storm_report.bat and choose L.";
      }
      document.querySelectorAll("button[data-storm]").forEach(x => x.disabled = false);
    };
  });
})();
</script>"""


def table(df, title: str) -> str:
    if df.empty:
        return ""
    rows = []
    for r in df.to_dict("records"):
        color = STRENGTH_COLORS[r["strength"]]
        if r["forecasts"]:
            action = (f"<button data-storm='{r['id']}' data-name='{r['name']}' style='font:600 13px system-ui,"
                      "sans-serif;padding:5px 12px;border-radius:6px;border:1px solid #1c5cab;background:#2a78d6;"
                      "color:#fff;cursor:pointer'>Open</button>")
        else:
            action = f"<span style='color:{INK_2};font-size:12px'>no WeatherNext forecasts</span>"
        rows.append(
            f"<tr><td style='text-align:left'><b>{r['name']}</b></td>"
            f"<td style='text-align:left;color:{INK_2}'>{r['id']}</td>"
            f"<td style='text-align:left'>{r['basin']}</td><td style='text-align:left'>{season.dates(r)}</td>"
            f"<td style='text-align:left'><span style='color:{color}'>●</span> {r['strength']}</td>"
            f"<td>{r['peak_mph']} mph</td><td>{action}</td></tr>")
    return (f"<h3>{title}</h3><div style='overflow-x:auto'><table style='width:100%'><tr>"
            "<th style='text-align:left'>Name</th><th style='text-align:left'>ID</th><th style='text-align:left'>Basin</th>"
            "<th style='text-align:left'>Dates</th><th style='text-align:left'>Peak strength</th><th>Peak wind</th>"
            f"<th></th></tr>{''.join(rows)}</table></div>")


def main() -> None:
    df = season.storms()
    year = df["first"].dt.year.max() if not df.empty else ""
    print(f"{year} storms (Atlantic, East and Central Pacific): {len(df)}\n")
    for r in df.to_dict("records"):
        flag = "  ACTIVE" if r["active"] else ("" if r["forecasts"] else "  (no WeatherNext forecasts)")
        print(f"  {r['id']}  {r['name']:<11} {season.dates(r):<14} {r['strength']:<21} {r['peak_mph']:>4} mph{flag}")

    intro = (f"<p>Every named storm and depression NHC has tracked in {year}. Pick one to open its report: "
             "for an active storm, the newest forecasts; for a finished one, every forecast made during its life "
             "against where it actually went, with the landfall comparison. Times and tracks come from NHC's best "
             "track. Western Pacific storms aren't listed (NHC doesn't track them), but you can still type their "
             "ID in the viewer, e.g. WP272026.</p>"
             "<p id='wnx-list-status' style='font-weight:600;color:#1c5cab;min-height:1.2em'></p>")
    figs = [intro,
            table(df[df["active"]], "Active now"),
            table(df[(~df["active"]) & (df["basin"] == "Atlantic")], "Atlantic: finished"),
            table(df[(~df["active"]) & (df["basin"] != "Atlantic")], "East and Central Pacific: finished"),
            OPEN_JS]
    out = plots.write_report(figs, ROOT / "outputs" / "storm_list.html", f"{year} storm season",
                             notes="From NHC's best-track files, updated with every advisory. Peak wind is the "
                                   "highest 1-minute sustained wind NHC recorded, rounded to the nearest 10 mph.")
    print(f"\nList written: {out}")


if __name__ == "__main__":
    main()
