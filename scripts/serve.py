"""Storm viewer: serves the reports on http://127.0.0.1 and powers each page's Refresh button.

Started by storm_report.bat. Lists active storms, asks which one to show, builds its report and
opens it in your browser. Keep the window open while you use the Refresh button; close it to stop.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
PY = sys.executable
BUILD_LOCK = threading.Lock()  # one rebuild at a time


def command_for(page: str) -> list[str] | None:
    """Which script rebuilds a given report page."""
    if m := re.fullmatch(r"([A-Za-z]{2}\d{6})_report\.html", page):
        return [PY, str(ROOT / "scripts" / "storm_report.py"), m.group(1), "--latest"]
    if m := re.fullmatch(r"active_storms_(\w+)\.html", page):
        return [PY, str(ROOT / "scripts" / "active_storms.py"), "--model", m.group(1)]
    if page == "storm_list.html":
        return [PY, str(ROOT / "scripts" / "storm_list.py")]
    if page == "gulf_outlook.html":
        return [PY, str(ROOT / "scripts" / "gulf_outlook.py")]
    if m := re.fullmatch(r"forecast_(\d{5})\.html", page):
        return [PY, str(ROOT / "scripts" / "my_forecast.py"), m.group(1)]
    if m := re.fullmatch(r"winter_(\d{5})\.html", page):
        return [PY, str(ROOT / "scripts" / "winter_outlook.py"), m.group(1)]
    return None


ZIP_FILE = ROOT / "data" / "my_zip.txt"   # remembered between sessions (data/ is not in git)


def open_for_zip(base: str, kind: str) -> None:
    """Local forecast (kind 'forecast') or winter outlook (kind 'winter') for a ZIP, remembering the ZIP."""
    what = "your forecast" if kind == "forecast" else "your winter outlook"
    saved = ZIP_FILE.read_text().strip() if ZIP_FILE.exists() else ""
    prompt = f"ZIP code for {what} [{saved}]: " if saved else f"ZIP code for {what}: "
    zip_code = input(prompt).strip() or saved
    if not re.fullmatch(r"\d{5}", zip_code):
        print("Please enter a 5-digit US ZIP code.")
        return
    ZIP_FILE.parent.mkdir(exist_ok=True)
    ZIP_FILE.write_text(zip_code)
    split = "\nForecast written" if kind == "forecast" else "\nOutlook written"
    open_page(base, f"{kind}_{zip_code}.html", f"Building {what} for {zip_code}...", split)


def open_page(base: str, page: str, message: str, split: str) -> None:
    print(message, flush=True)
    result = run(command_for(page))
    if result.returncode != 0:
        print((result.stderr or result.stdout).strip().splitlines()[-1])
        return
    print(result.stdout.split(split)[0].strip())
    webbrowser.open(f"{base}/{page}")
    print(f"\nOpened {base}/{page}")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    # stdin=DEVNULL: the main thread sits in input(), and a child that inherits that same stdin
    # can hang at startup on Windows.
    with BUILD_LOCK:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600,
                              stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})  # e.g. the ° in forecasts


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always show the newest build
        super().end_headers()

    def do_POST(self):
        page = self.path.removeprefix("/refresh/")
        cmd = command_for(page) if self.path.startswith("/refresh/") else None
        if cmd is None:
            return self._json(404, {"ok": False, "error": "this page can't be refreshed"})
        print(f"\n[refresh] rebuilding {page} ...", flush=True)
        try:
            result = run(cmd)
        except subprocess.TimeoutExpired:
            return self._json(500, {"ok": False, "error": "timed out"})
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["unknown error"]
            print(f"[refresh] failed: {tail[0]}", flush=True)
            return self._json(500, {"ok": False, "error": tail[0]})
        print(f"[refresh] done: {page}", flush=True)
        self._json(200, {"ok": True})

    def _json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # keep the console readable
        pass


class ExclusiveServer(ThreadingHTTPServer):
    # Python's HTTP server sets SO_REUSEADDR, which on Windows lets a second viewer bind a port that's
    # already in use, and then requests go to the wrong one. Refuse instead, so we move to the next port.
    allow_reuse_address = False


def start_server(first_port: int = 8913) -> int:
    OUT.mkdir(exist_ok=True)
    for port in range(first_port, first_port + 20):
        try:
            server = ExclusiveServer(("127.0.0.1", port), partial(Handler, directory=str(OUT)))
        except OSError:
            continue  # port busy (e.g. another viewer window is open)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return port
    sys.exit("Couldn't find a free local port.")


def main() -> None:
    sys.stdout.reconfigure(errors="replace")  # never crash on a character the console can't show
    port = start_server()
    base = f"http://127.0.0.1:{port}"
    print("Checking the latest forecast for active storms...\n", flush=True)
    listing = run(command_for("active_storms_WNV3.html"))
    print(listing.stdout.split("\nMap written")[0])
    print(f"\nAll-storms map: {base}/active_storms_WNV3.html")

    while True:
        print()
        storm = input("Storm ID to open (e.g. AL092026), L for a list of this season's storms, M for the all-storms map,\n"
                      "  F for your local forecast, G for the 15-day Gulf tropical outlook, W for your winter outlook, "
                      "Q to quit: ").strip()
        if storm.upper() == "Q":
            return
        if storm.upper() == "L":
            open_page(base, "storm_list.html", "Loading this season's storms...", "\nList written")
            continue
        if storm.upper() == "M":
            webbrowser.open(f"{base}/active_storms_WNV3.html")
            continue
        if storm.upper() == "G":
            open_page(base, "gulf_outlook.html", "Building the 15-day Gulf outlook (first time takes a few minutes)...",
                      "\nOutlook written")
            continue
        if storm.upper() in ("F", "W"):
            open_for_zip(base, "forecast" if storm.upper() == "F" else "winter")
            continue
        if not re.fullmatch(r"[A-Za-z]{2}\d{6}", storm):
            print("That doesn't look like a storm ID: two letters and six digits, like AL092026.")
            continue
        storm = storm.upper()
        print(f"Building {storm} report...", flush=True)
        result = run(command_for(f"{storm}_report.html"))
        if result.returncode != 0:
            print((result.stderr or result.stdout).strip().splitlines()[-1])
            continue
        print(result.stdout.split("\nReport written")[0].strip())
        webbrowser.open(f"{base}/{storm}_report.html")
        print(f"\nOpened {base}/{storm}_report.html")
        print("Keep this window open so the report's Refresh button works.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        pass
