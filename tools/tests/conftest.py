"""Make the server package and the tool scripts importable for every tools test."""

import sys
from pathlib import Path

PDOS_NEXT = Path(__file__).resolve().parents[2]
for path in (PDOS_NEXT / "server", PDOS_NEXT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
