from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from em_design_mcp.registries.model_profile_registry import ModelProfileRegistry
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.registries.problem_spec_registry import ProblemSpecRegistry
from em_design_mcp.registries.verifier_registry import VerifierRegistry
from em_design_mcp.tools.candidate_tools import get_contract_bundle_payload


def main() -> int:
    packages = PackageRegistry()
    model_profiles = ModelProfileRegistry(packages=packages)
    problems = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)
    for profile in model_profiles.list_profiles():
        model_profiles.get(profile["model_profile_id"])
    for problem in problems.list_specs():
        problem_data = problems.as_dict(problem["problem_id"])
        for profile_id in problem_data.get("compatible_model_profiles") or []:
            get_contract_bundle_payload(
                profile_id,
                problem["problem_id"],
                model_profiles,
                problems,
                verifiers,
            )
    for verifier in verifiers.list_verifiers():
        verifiers.get(verifier["verifier_id"])
    print(f"Design package validation succeeded: {len(packages.packages())} packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
