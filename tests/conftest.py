"""Test configuration.

Adds the backend research package to sys.path so tests and the FadeStrategy adapter
can import `research.lib.*`. This coupling is deliberate (anti-drift guarantee) and
isolated here — no other file should manipulate sys.path.
"""

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).parents[3] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.append(str(_BACKEND_ROOT))
