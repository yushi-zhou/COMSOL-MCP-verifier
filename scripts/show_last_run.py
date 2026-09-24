from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from em_design_mcp.runs.result_summary import find_latest_result_summary, load_result_summary
from em_design_mcp.registries.package_registry import PackageRegistry
from em_design_mcp.utils.paths import configured_runs_dir


def main() -> int:
    _load_dotenv(ROOT / ".env")
    if os.environ.get("EM_DESIGN_MCP_RUNS_DIR"):
        run_roots = [configured_runs_dir()]
    else:
        run_roots = [package.root / "runs" for package in PackageRegistry().packages()]
        run_roots.append(configured_runs_dir())
    candidates = [find_latest_result_summary(root) for root in run_roots if root.exists()]
    candidates = [path for path in candidates if path is not None]
    summary_path = max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    if summary_path is None:
        print("No run summaries found under configured package/global run roots.")
        return 0

    summary = load_result_summary(summary_path)
    _print_summary(summary_path, summary)
    return 0


def _print_summary(summary_path: Path, summary: dict[str, Any]) -> None:
    print(f"Summary: {summary_path}")
    print(f"Run ID: {summary.get('run_id', '')}")
    print(f"Backend: {summary.get('backend', '')}")
    print(f"Model profile: {summary.get('model_profile_id', '')}")
    print(f"Problem: {summary.get('problem_id', '')}")
    print(f"Status: {summary.get('status', '')}")
    print(f"Overall pass: {summary.get('overall_pass', '')}")
    print(f"Failure category: {summary.get('failure_category', '')}")
    print(f"Verifier: {summary.get('verifier_id', '')}")
    print("Candidate:")
    _print_mapping(summary.get("candidate") or {})
    print("Summary metrics:")
    _print_mapping(summary.get("summary_metrics") or {})
    print("Simulation output:")
    _print_mapping(summary.get("simulation_output_summary") or {})
    verifier_result = summary.get("verifier_result") if isinstance(summary.get("verifier_result"), dict) else {}
    per_condition = verifier_result.get("per_condition_results") if isinstance(verifier_result, dict) else {}
    print("Per-condition results:")
    _print_nested_mapping(per_condition or {})
    print("Artifacts:")
    _print_mapping(summary.get("artifacts") or {})


def _print_mapping(mapping: Any) -> None:
    if not isinstance(mapping, dict) or not mapping:
        print("  (none)")
        return
    for key in sorted(mapping):
        print(f"  {key}: {mapping[key]}")


def _print_nested_mapping(mapping: Any) -> None:
    if not isinstance(mapping, dict) or not mapping:
        print("  (none)")
        return
    for key in sorted(mapping):
        print(f"  {key}:")
        value = mapping[key]
        if isinstance(value, dict):
            for inner_key in sorted(value):
                print(f"    {inner_key}: {value[inner_key]}")
        else:
            print(f"    {value}")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
