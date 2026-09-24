from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
import yaml

from em_design_mcp.backends.base import BackendExecutionError
from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.runs.job_store import JobStore
from em_design_mcp.server import create_server
from em_design_mcp.tools.candidate_tools import evaluate_candidate_payload
from em_design_mcp.tools.model_tools import inspect_model_payload
from em_design_mcp.utils.provenance import file_sha256
from em_design_mcp.utils.provenance import capture_provenance, require_provenance


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "package"
    shutil.copytree(Path(__file__).parent / "fixtures" / "designs", root)
    monkeypatch.setenv("EM_DESIGN_PACKAGE_ROOTS", str(root))
    monkeypatch.setenv("EM_DESIGN_MCP_RUNS_DIR", str(tmp_path / "runs"))
    registry = PackageRegistry()
    profiles = ModelProfileRegistry(packages=registry)
    problems = ProblemSpecRegistry(packages=registry)
    return root, registry, profiles, problems


def test_provenance_changes_with_model_bytes_contract_plugins_and_declared_evidence(package):
    root, registry, profiles, problems = package
    profile = profiles.as_dict("generic_mock_profile")
    problem = problems.as_dict("generic_mock_problem")
    model = root / "test.mph"
    model.write_bytes(b"first")
    profile["backend"] = {"type": "matlab_livelink", "model_artifact": {"path": "test.mph"}}
    evidence = root / "calibration.json"
    evidence.write_text("{}")
    profile["provenance_files"] = ["calibration.json"]
    original = capture_provenance(profile, problem, registry)
    assert original == capture_provenance(profile, problem, registry)
    for path, content in [(model, b"other"), (root / "plugins" / "helper.py", b"X=1"), (evidence, b'{"revision":2}')]:
        path.write_bytes(content)
        changed = capture_provenance(profile, problem, registry)
        assert original["id"] != changed["id"]
        with pytest.raises(BackendExecutionError, match="changed"):
            require_provenance(original, changed)
        original = changed
    updated = deepcopy(profile)
    updated["measurements"] = [{"id": "a", "expression": "x", "dataset": "other"}]
    assert capture_provenance(updated, problem, registry)["id"] != original["id"]


def test_start_rejects_stale_contract_before_launch(package, monkeypatch):
    _, registry, profiles, problems = package
    jobs = JobStore(registry, profiles)
    def no_launch(*args, **kwargs):
        pytest.fail("Stale requests must fail before launching a process")
    monkeypatch.setattr("em_design_mcp.runs.job_store.subprocess.Popen", no_launch)
    with pytest.raises(BackendExecutionError) as caught:
        jobs.start(model_profile_id="generic_mock_profile", problem_id="generic_mock_problem", candidate={}, backend="mock",
                   expected_provenance="old-receipt")
    assert caught.value.failure_category == "stale_provenance"


def test_public_contract_reload_and_plugin_source_reload(package):
    root, _, _, _ = package
    server = create_server()
    inspect = server._tool_manager._tools["inspect_contract"].fn
    first = inspect("generic_mock_profile", "generic_mock_problem")
    assert first["provenance"]["contract_hash"] == first["contract_hash"]
    problem_path = root / "problems" / "generic_mock_problem.example.yaml"
    data = yaml.safe_load(problem_path.read_text())
    data["objectives"][0]["target"] = 9
    problem_path.write_text(yaml.safe_dump(data))
    second = inspect("generic_mock_profile", "generic_mock_problem")
    assert second["thresholds"]["score"] == 9
    assert second["provenance"]["id"] != first["provenance"]["id"]
    plugin = root / "plugins" / "mock_generic_verifier.py"
    before = plugin.read_text()
    plugin.write_text(before + "\n# source revision\n")
    third = inspect("generic_mock_profile", "generic_mock_problem")
    assert third["provenance"]["id"] != second["provenance"]["id"]


def test_running_server_discovers_new_external_profile_without_restart(package):
    root, _, _, _ = package
    server = create_server()
    discover = server._tool_manager._tools["discover_designs"].fn
    assert discover("new_registered_design")["count"] == 0
    profile = yaml.safe_load((root / "profiles/generic_mock_profile.example.yaml").read_text())
    profile["model_profile_id"] = "new_registered_design"
    (root / "profiles/new.example.yaml").write_text(yaml.safe_dump(profile))
    manifest_path = root / "em-design-package.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["profiles"] = list(dict.fromkeys(manifest["profiles"] + ["profiles/new.example.yaml"]))
    # Existing fixture uses globs: keep a single matching declaration.
    manifest["profiles"] = ["profiles/*.yaml"]
    manifest_path.write_text(yaml.safe_dump(manifest))
    assert discover("new_registered_design")["count"] == 1


def test_input_drift_during_run_cannot_receive_passing_validation(package, monkeypatch):
    root, registry, profiles, problems = package
    class ChangingBackend:
        def run(self, **kwargs):
            (root / "plugins" / "changed.py").write_text("NEW = True")
            return {"summary_metrics": {"score": 100}}
    monkeypatch.setattr("em_design_mcp.tools.candidate_tools.create_backend", lambda *a, **kw: ChangingBackend())
    result = evaluate_candidate_payload("generic_mock_profile", "generic_mock_problem",
        {"width_nm": 80, "gap_nm": 10, "length_um": 2.5}, "mock", profiles, problems, VerifierRegistry(registry))
    assert result["status"] == "stale_provenance" and result["overall_pass"] is False


@pytest.mark.parametrize("recomputed", [False, True])
def test_solved_artifact_identity_does_not_imply_all_solutions_are_fresh(package, recomputed):
    root, registry, profiles, _ = package
    profile = profiles.as_dict("generic_mock_profile")
    source = root / "model.mph"
    source.write_bytes(b"unchanged-source")
    solved = root / "solved.mph"
    solved.write_bytes(b"saved-solutions")
    profile["backend"] = {"type": "matlab_livelink", "model_artifact": {"path": "model.mph"}}
    profile["measurements"] = [{"id": "power", "expression": "P", "unit": "W", "method": "global",
                                 "study": "study", "solution": "sol", "dataset": "data"}]
    provenance = capture_provenance(profile, {}, registry)
    request = {"job_id": "job_receipt", "topics": ["studies"], "measurement_ids": ["power"],
               "provenance": provenance,
               "source": {"path": str(solved), "sha256": file_sha256(solved), "recomputed_solutions": ["sol"] if recomputed else []}}
    class Reader:
        def inspect(self, **kwargs):
            folder = root.parent / "runs" / "job_receipt"
            folder.mkdir(parents=True, exist_ok=True)
            return {"model_facts": {"schema_version": "em_model_facts_v1", "studies": {}},
                    "measurements": [], "preflight": {"valid": True}, "facts_path": str(folder / "output.json")}
    result = inspect_model_payload(request, profile, {}, registry, backend=Reader())
    assert result["artifact_receipt_verified"] is True
    assert result["solution_freshness"] == ("verified_measurement_solutions" if recomputed else "unverified_saved_solution")
    solved.write_bytes(b"modified")
    with pytest.raises(BackendExecutionError) as error:
        inspect_model_payload(request, profile, {}, registry, backend=Reader())
    assert error.value.failure_category == "stale_provenance"
