#!/usr/bin/env python3
"""
INDRA — the Patna demo, run against the live backend.

Since Phase 3 T10 this is `run_hazard_demo.py --hazard flood --city patna
--heatmap`: the same five Kankarbagh reports at the same coordinates, now each
from its own reporter id, followed by their dockets to the event they joined,
and the same options. Every number printed is read back from the API.

History worth keeping: until 20 Sep this script printed a hand-written
narrative (127 signals, confidence 0.94, AUTO_PUBLISHED, IMD and CWC sensors
that do not exist) and made no call at all. It was rewritten to exercise the
real pipeline and print only what the API returns, and that rule stands.

Usage
-----
    ./start.sh -b
    backend/.venv/bin/python scripts/run_patna_demo.py
    backend/.venv/bin/python scripts/run_patna_demo.py --corroborate  # one extra report
    backend/.venv/bin/python scripts/run_patna_demo.py --official     # + one official dispatch

Exit code is non-zero if no flood event formed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_hazard_demo import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["--hazard", "flood", "--city", "patna", "--heatmap", *sys.argv[1:]]))
