# Installation and operation

## Supported installation

Python 3.10 or newer is required. Install from a checkout into a virtual
environment with `python -m pip install -e ".[test]"`. The `test` extra adds
pytest; runtime dependencies are Pydantic, PyYAML, and the Python MCP SDK.

The checkout must remain available. Resource lookup and provenance currently
depend on its `src/` and `matlab/` directories; installing only a wheel or moving
the checkout after editable installation is unsupported. There is no claim of a
published PyPI release. The `report` extra is optional for image-report helpers.

The [README mock walkthrough](../README.md#try-it-without-comsol) requires no
MATLAB, COMSOL, model downloads, API key, or running language model. Fixture
verifiers are synthetic and must not be used to make physical claims.

## Runtime configuration

Copy `.env.example` to `.env` in the checkout, or set environment variables in
the process that starts the MCP server/CLI. Existing process variables take
precedence. The dotenv reader accepts literal `KEY=value` assignments and optional
surrounding quotes; it does not expand shell variables or interpolate paths.

| Variable | Meaning |
|---|---|
| `EM_DESIGN_PACKAGE_ROOTS` | Package search directories, separated by `;` on Windows or `:` on POSIX; overrides the sibling `../em_design_modals` default |
| `MATLAB_EXE` | Absolute path to the MATLAB executable; defaults to `matlab` on `PATH` |
| `COMSOL_MLI` | Absolute path to the installation's LiveLink for MATLAB `mli` directory |
| `COMSOL_SERVER_PORT` | Local COMSOL server port, default `2036` |
| `EM_DESIGN_MCP_RUNS_DIR` | Optional central run directory; otherwise each package uses its own `runs/` |

Use absolute runtime and model environment paths. Package/run roots may be
relative to the launching process's working directory; workers receive resolved
absolute roots. Inside a profile, relative model artifact paths resolve from the
package directory. Absolute artifact paths and legacy `path_env` bindings remain
supported for trusted local installations.

Register only trusted packages: loading a parser or verifier executes Python
code. Discovery recursively finds `em-design-package.yaml`, pruning generated
directories such as `runs/`. IDs must be unique across selected roots. See the
[package guide](DESIGN_PACKAGES.md) for the manifest and ownership boundary.

## MATLAB and COMSOL LiveLink

**COMSOL version compatibility:** COMSOL MCP Verifier targets COMSOL Multiphysics
6.0 and later. The core workflow was developed on COMSOL 6.0 and end-to-end
smoke-tested on COMSOL Multiphysics 6.4 Build 429 with MATLAB R2026a.
Version-specific installation paths and model-authoring APIs may differ between
releases.

This is **MCP workflow smoke-tested on COMSOL 6.4**, not full coverage of every
physics module, model-authoring API, or platform. Real execution and
`inspect_model` require your own licensed installations:

1. Install MATLAB, COMSOL Multiphysics, LiveLink for MATLAB, and the physics
   modules required by the external model. Use a MATLAB/COMSOL combination
   supported by that COMSOL release; this repository does not provide a version
   compatibility matrix.
2. Configure MATLAB's COMSOL Java/LiveLink integration using the installed
   product instructions. The batch MATLAB process must be able to import COMSOL
   classes and call `mphstart`; an interactive MATLAB session alone is not enough.
3. Start a local COMSOL server using your installation's server launcher. Match
   its port to `COMSOL_SERVER_PORT`. The adapter connects to an existing server;
   it does not launch or manage one, or provide remote authentication settings.
   Update the server executable/path and startup/login configuration for your
   installed release. Do not assume another machine's launcher or saved login
   settings will work locally; never put login credentials in a package.
4. Update `MATLAB_EXE` and `COMSOL_MLI` to the paths for your local release,
   and set package roots. Select a package whose saved
   model, bindings, parser, and verifier were validated for that setup.
5. Start with discovery and contract inspection, then inspect selected actual
   facts. `prepare_run` checks candidate/policy declarations without opening
   COMSOL. A small known baseline run checks the complete path.

The fixed entrypoint is `matlab/run_em_design_from_json.m`. Python starts MATLAB
with `-batch`; the entrypoint connects, loads a uniquely tagged copy, applies
package bindings, and writes JSON/tables. Source MPH files are not overwritten.
Logs stay in the run directory. Exported tables and optional solved copies default
to a directory within that run, but profiles may override their location through
`backend.output_dir` or `output_dir_env`; use the returned artifact paths.
Model construction remains a package-owned terminal workflow, not an MCP command tool.

Use the returned error category and artifact paths for diagnosis:

| Symptom | First check |
|---|---|
| No designs discovered | Package roots, manifest name/schema, unique IDs; no production packages ship here |
| Missing MATLAB entrypoint after installation | Use the supported editable source checkout |
| Missing executable/model | `MATLAB_EXE`, profile artifact path, package-relative resolution |
| License or connection error | Licensed modules, running server, port and MATLAB integration |
| `physics_preflight_failed` | Retained observed facts and declared expectations; do not bypass a failed check |
| `stale_provenance` | Changed model, contract, plugin or declared evidence; re-inspect before rerunning |
| Dataset/unit/measurement failure | Actual dataset-to-solution binding, saved samples, selection and native units |
| Job remains `running` after worker exits | Inspect local processes and artifacts; automatic dead-worker reconciliation is not implemented |

Cancellation and timeouts do not guarantee that a separately running COMSOL
server has stopped computing. See [job lifecycle limits](ARCHITECTURE.md#local-job-lifecycle).

## JSON CLI compatibility

```sh
python -m em_design_mcp.cli run-json --input request.json --output response.json --pretty
```

The input selects `tool`, `model_profile_id`, `problem_id`, and, where required,
`candidate` and `backend`. The checked-in [mock request](../tests/fixtures/mock-request.json)
is a runnable example. `--dotenv path/to/config.env` selects a different dotenv file.

The output envelope remains `em_design_mcp_cli_v1`. Supported operations are
`get_contract_bundle`, `get_candidate_schema`, `validate_candidate`,
`estimate_candidate_cost`, and `evaluate_candidate`.

`ok=true` means the boundary processed the request. Validation, policy, backend,
or verifier failure may still appear inside `result`; examine `status`, `valid`,
`overall_pass`, `failure_category`, and errors there. `ok=false` indicates a bad
CLI request or boundary failure. A process exit code alone is not a physics verdict.

## Artifacts and sharing

Jobs preserve requests, state, results, provenance and backend evidence as
applicable. The synchronous CLI also writes the requested envelope file; it does
not create the asynchronous worker's state files. Artifact paths refer to the
service host, not downloadable URLs. Do not delete failed runs automatically.

Artifacts may contain model parameters, full local paths, solver diagnostics,
and research data. Review them before attaching to an issue or publishing a
package. They are intentionally excluded from this repository's tracked demos.
