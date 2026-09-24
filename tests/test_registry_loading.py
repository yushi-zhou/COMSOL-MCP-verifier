from __future__ import annotations

from pathlib import Path

import pytest

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_model_profile_registry_loads_example_local_and_ignores_disabled(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    _write(
        root / "profile.example.yaml",
        """model_profile_id: example_profile
version: '1.0'
domain: test
description: example
backend:
  type: mock
  model_artifact:
    kind: none
    path_env: null
    companion_paths_env: []
  output_dir_env: null
compatible_problem_families: [test]
design_schema:
  type: object
  required: [a]
  properties:
    a:
      type: number
  additionalProperties: false
model_bindings: {}
output_schema:
  type: object
  required: [summary_metrics]
  properties:
    summary_metrics:
      type: object
""",
    )
    _write(
        root / "profile.local.yaml",
        """model_profile_id: local_profile
version: '1.0'
domain: test
description: local
backend:
  type: mock
  model_artifact:
    kind: none
    path_env: null
    companion_paths_env: []
  output_dir_env: null
compatible_problem_families: [test]
design_schema:
  type: object
  required: [b]
  properties:
    b:
      type: number
  additionalProperties: false
model_bindings: {}
output_schema:
  type: object
  required: [summary_metrics]
  properties:
    summary_metrics:
      type: object
""",
    )
    _write(
        root / "profile.disabled.yaml",
        """model_profile_id: disabled_profile
version: '1.0'
domain: test
description: disabled
backend:
  type: mock
  model_artifact:
    kind: none
    path_env: null
    companion_paths_env: []
  output_dir_env: null
compatible_problem_families: [test]
design_schema:
  type: object
  required: [c]
  properties:
    c:
      type: number
  additionalProperties: false
model_bindings: {}
output_schema:
  type: object
  required: [summary_metrics]
  properties:
    summary_metrics:
      type: object
""",
    )
    registry = ModelProfileRegistry(root)
    ids = [entry["model_profile_id"] for entry in registry.list_profiles()]
    assert "example_profile" in ids
    assert "local_profile" in ids
    assert "disabled_profile" not in ids


def test_problem_spec_registry_loads_example_local_and_ignores_disabled(tmp_path: Path) -> None:
    root = tmp_path / "problems"
    root.mkdir()
    _write(
        root / "problem.example.yaml",
        """problem_id: example_problem
version: '1.0'
family: test
difficulty: easy
description: example
compatible_model_profiles: [example_profile]
independent_variables:
  wavelength_nm: [750]
objectives: []
constraints: []
verifier_id: mock_generic_verifier
expected_outputs: [summary_metrics]
""",
    )
    _write(
        root / "problem.local.yaml",
        """problem_id: local_problem
version: '1.0'
family: test
difficulty: easy
description: local
compatible_model_profiles: [local_profile]
independent_variables:
  wavelength_nm: [750]
objectives: []
constraints: []
verifier_id: mock_generic_verifier
expected_outputs: [summary_metrics]
""",
    )
    _write(
        root / "problem.disabled.yaml",
        """problem_id: disabled_problem
version: '1.0'
family: test
difficulty: easy
description: disabled
compatible_model_profiles: [local_profile]
independent_variables:
  wavelength_nm: [750]
objectives: []
constraints: []
verifier_id: mock_generic_verifier
expected_outputs: [summary_metrics]
""",
    )
    registry = ProblemSpecRegistry(root)
    ids = [entry["problem_id"] for entry in registry.list_specs()]
    assert "example_problem" in ids
    assert "local_problem" in ids
    assert "disabled_problem" not in ids


def test_duplicate_profile_ids_raise(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    yaml_template = """model_profile_id: dup_profile
version: '1.0'
domain: test
description: dup
backend:
  type: mock
  model_artifact:
    kind: none
    path_env: null
    companion_paths_env: []
  output_dir_env: null
compatible_problem_families: [test]
design_schema:
  type: object
  required: [a]
  properties:
    a:
      type: number
  additionalProperties: false
model_bindings: {}
output_schema:
  type: object
  required: [summary_metrics]
  properties:
    summary_metrics:
      type: object
"""
    _write(root / "a.example.yaml", yaml_template)
    _write(root / "b.local.yaml", yaml_template)
    registry = ModelProfileRegistry(root)
    with pytest.raises(ValueError, match="Duplicate model_profile_id"):
        registry.list_profiles()


def test_missing_configured_directory_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    registry = ProblemSpecRegistry(missing)
    with pytest.raises(FileNotFoundError, match="Configured problem spec directory does not exist"):
        registry.list_specs()
