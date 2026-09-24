# Testing and evidence

## COMSOL-free suite

From an editable installation with the `test` extra:

```sh
python -m pytest -q
```

`tests/conftest.py` selects `tests/fixtures/designs`, independently of production
package roots. The fixture profiles and verifiers exercise infrastructure with
synthetic values. They are not validated electromagnetic models.

| Coverage | Representative tests | What it does not establish |
|---|---|---|
| Package discovery, contracts, validation | `test_package_registries.py`, `test_registry_loading.py`, `test_schema_driven_candidate_validation.py`, `test_constraint_validation.py`, `test_compatibility_rules.py` | Physical adequacy of external contracts |
| Policy and stable CLI | `test_execution_policy.py`, `test_cli.py`, `test_server_surface.py` | Resource prediction or global scheduling quotas |
| Deterministic mock and parser behavior | `test_mock_backend_determinism.py`, `test_comsol_table_parser.py` | Accuracy of any real simulation |
| Actual Python worker subprocesses | `test_agent_jobs.py` | COMSOL cancellation, crash recovery, or solver progress reporting |
| Fingerprints and stale evidence rejection | `test_provenance.py` | Undeclared dependency tracking or reproducible software/hardware environments |
| Fact checks, bindings, compaction | `test_model_observation.py` | Complete COMSOL property coverage or general physics correctness |
| LiveLink adapter handling | `test_matlab_livelink_backend.py` | A successful real MATLAB invocation; subprocess responses are mocked |
| MATLAB source invariants | `test_matlab_entrypoint_source.py` | MATLAB syntax/runtime correctness; these are source-text checks |

The GitHub Actions workflow runs this suite and the README mock CLI example on
Linux (Python 3.10 and 3.14) and Windows (Python 3.12). It installs no commercial
software and has read-only repository permissions. A green workflow means these
infrastructure checks passed on that revision, not that external models passed
physical validation. Test counts should be taken from the actual run, not a badge
or a historical README number.

## Real solver checks belong to external packages

This source release includes no real COMSOL model, example package, or portable
licensed-solver integration test. Its test suite needs neither MATLAB nor COMSOL.
Use an external package's opt-in regression or smoke workflow to exercise your
licensed installation; such tests consume licenses and compute resources and
must remain disabled in public COMSOL-free CI.

Configure the [LiveLink runtime](INSTALLATION.md#matlab-and-comsol-livelink),
then use discovery, contract inspection, model inspection, candidate preparation,
a bounded real run, named measurements, and the package verifier. When saving a
solved artifact, reload it through `inspect_model` with the source job ID to check
its receipt and named-measurement freshness. Record exact versions, inputs,
results, and limitations in the owning package. Do not copy generated models,
solver logs, or private evidence into this repository.

## COMSOL 6.4 workflow evidence

**COMSOL version compatibility:** COMSOL MCP Verifier targets COMSOL Multiphysics
6.0 and later. The core workflow was developed on COMSOL 6.0 and end-to-end
smoke-tested on COMSOL Multiphysics 6.4 Build 429 with MATLAB R2026a.
Version-specific installation paths and model-authoring APIs may differ between
releases.

**MCP workflow smoke-tested on COMSOL 6.4** describes a maintainer-reported real
LiveLink smoke test of the core workflow. The reported checks covered:

- MATLAB LiveLink connection and model load/save;
- package discovery, contract inspection, and candidate validation;
- model inspection, study/solution/dataset discovery, mesh inspection, and
  declared preflight;
- a real solve, solution clearing/recomputation, `mphsolinfo`, and `mphglobal`;
- named measurement extraction, verifier execution, and provenance/artifact
  reporting;
- solved-model reload, artifact receipt verification, and verified
  measurement-solution freshness.

This is a workflow smoke test, not a compatibility matrix for every physics
module, COMSOL API, model-authoring operation, or operating system. The temporary
synthetic package used for that test is not part of the product or this release.
The record summarizes completed maintainer testing; it is not a public CI run or
a bundled reproducible solver fixture. Report the exact versions and commit when
reproducing the workflow with your own package. Generated models, local logs,
and raw receipts are intentionally not published here.

## Interpreting solver evidence

A package should distinguish configuration/preflight checks, solver completion,
independent physics checks, convergence, and verified scope. For example, energy
balance does not establish local-field convergence, and a correctly bound saved
dataset does not prove that its solution is current. See
[provenance and freshness](MODEL_OBSERVATION.md#provenance-and-freshness).

## Before sending a change

Run affected tests and then the COMSOL-free suite, exercise any changed documented
commands, and run `git diff --check`. Preserve `em_design_mcp_cli_v1` and the small
public tool surface. Clearly label mocked, source-only, and actual solver checks
in the PR. Do not include private model data or solver logs as test fixtures.
