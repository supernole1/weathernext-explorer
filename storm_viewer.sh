#!/usr/bin/env sh
# Mac/Linux launcher: sets up .venv on first run, then starts the storm viewer.
# Keep the terminal open while viewing - it powers the report's Refresh button.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "First run: setting things up..."
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ is required."; exit 1; }
    python3 -m venv .venv && .venv/bin/python -m pip install --quiet -r requirements.txt || exit 1
fi
exec .venv/bin/python scripts/serve.py
