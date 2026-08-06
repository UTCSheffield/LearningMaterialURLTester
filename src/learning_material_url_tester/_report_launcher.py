"""Launcher for the Streamlit reporting app.

Called via the `learning-material-url-tester-report` script entry point,
or directly:  python -m learning_material_url_tester.report_launcher
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    from streamlit.web import cli as stcli

    report_path = str(Path(__file__).parent / "report.py")
    # Pass any extra args (e.g. --db path/to/results.db) through to the app.
    sys.argv = ["streamlit", "run", report_path, "--"] + sys.argv[1:]
    sys.exit(stcli.main())
