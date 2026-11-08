#!/usr/bin/env python3
"""Theme checks: start the local stack (tools/cloud_e2e.Stack) with a theme, then run
cloud/tools/theme-check.mjs (Playwright Firefox 500x940 + Chromium 412x915, axe, page weight,
off-host requests, one-scroll fit) and save screenshots.

    .venv/bin/python tools/theme_check.py [--theme dha|lab] [--host guest.lanpulse.com] [--out DIR]

Needs cloud/node_modules (npm ci) and the browsers (cd cloud && npx playwright install firefox chromium).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cloud_e2e import ROOT, Stack  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="dha", choices=["dha", "lab"])
    ap.add_argument("--host", default="guest.lanpulse.com", help="GUEST_HOST for the run (resolved to 127.0.0.1 in the browsers)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--browsers", default="firefox,chromium", choices=["firefox,chromium", "chromium"],
                    help="chromium: run the 500x940 kiosk profile in Chromium too (where Firefox can't start)")
    a = ap.parse_args()
    out = a.out or tempfile.mkdtemp(prefix=f"theme-{a.theme}-")
    with Stack({"PORTAL_THEME": a.theme, "GUEST_HOST": a.host}, prefix="theme-check-") as st:
        st.start_connector()
        rc = subprocess.call(
            ["node", "tools/theme-check.mjs", f"--port={st.wport}", f"--host={a.host}", f"--out={out}", f"--theme={a.theme}",
             f"--browsers={a.browsers}"],
            cwd=os.path.join(ROOT, "cloud"))
    print(f"     screenshots: {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
