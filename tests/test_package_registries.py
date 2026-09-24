from __future__ import annotations

from pathlib import Path

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry


def test_package_registries_discover_contracts_and_plugins() -> None:
    packages = PackageRegistry()
    profiles = ModelProfileRegistry(packages=packages)
    problems = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)

    assert {item["package_id"] for item in packages.summary()} == {"test-fixtures"}
    assert "generic_mock_profile" in {item["model_profile_id"] for item in profiles.list_profiles()}
    assert "generic_mock_problem" in {item["problem_id"] for item in problems.list_specs()}
    assert verifiers.get("mock_generic_verifier").required_outputs == ["summary_metrics"]

    profile = profiles.as_dict("generic_mock_profile")
    assert profile["_package_id"] == "test-fixtures"
    assert Path(profile["_source_path"]).is_file()


def test_duplicate_package_ids_are_rejected(tmp_path: Path) -> None:
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        (root / "em-design-package.yaml").write_text(
            "schema_version: em_design_package_v1\npackage_id: duplicate\nprofiles: []\nproblems: []\n",
            encoding="utf-8",
        )
    registry = PackageRegistry([tmp_path])
    try:
        registry.packages()
    except ValueError as exc:
        assert "Duplicate package_id" in str(exc)
    else:
        raise AssertionError("duplicate package IDs should fail")
