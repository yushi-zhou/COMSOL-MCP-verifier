from __future__ import annotations

import re
from pathlib import Path


REQUIRED_KEYS = {
    "COMSOL_SERVER_PORT",
    "EM_DESIGN_PACKAGE_ROOTS",
    "EM_DESIGN_MCP_RUNS_DIR",
    "MATLAB_EXE",
    "COMSOL_MLI",
}


def test_env_example_has_only_runtime_configuration_and_no_local_paths() -> None:
    path = Path(__file__).resolve().parents[1] / ".env.example"
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value

    assert REQUIRED_KEYS == set(values)
    for value in values.values():
        assert not re.search(r"^[A-Za-z]:[\\/]", value)
        assert not value.startswith(("/", "\\"))
