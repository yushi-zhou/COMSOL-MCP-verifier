from __future__ import annotations

import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ["EM_DESIGN_PACKAGE_ROOTS"] = str(ROOT / "tests" / "fixtures" / "designs")
os.environ["PYTHONPATH"] = os.pathsep.join(
    value for value in (str(SRC), os.environ.get("PYTHONPATH", "")) if value
)
