# Architecture and trust boundaries

The system separates model knowledge from reusable execution infrastructure.
The unit of engineering work is a profile/problem pair plus a candidate, not an
arbitrary solver command.

## Components

| Component | Responsibility | Implementation |
|---|---|---|
| Package registry | Discover manifests, contracts, and trusted Python plugins | `registries/` |
| ModelProfile | Candidate schema, model artifact, trusted tags/bindings, measurements, preflight | `schemas/model_profile.py` |
| ProblemSpec | Compatible profiles, objectives, constraints, verifier and policy overrides | `schemas/problem_spec.py` |
| Validation and policy | Reject incompatible/invalid candidates and declared excessive sweeps | `validation/`, `execution_policy.py` |
| MCP interface | Seven compact agent tools and fresh registry reads | `tools/agent_tools.py` |
| CLI interface | Synchronous `em_design_mcp_cli_v1` requests | `cli.py` |
| Job store and worker | Persist requests/state, launch independent local processes, wait by revision | `runs/job_store.py`, `worker.py` |
| LiveLink adapter | Fixed JSON entrypoint, isolated loaded model, bounded bindings, artifacts | `backends/matlab_livelink_backend.py` and repository `matlab/` |
| Provenance | Fingerprint active inputs and reject drift across execution | `utils/provenance.py` |

Python paths above are relative to `src/em_design_mcp/`.
Both interfaces share the validation/backend/verifier pipeline in
`tools/candidate_tools.py`. The CLI remains synchronous; MCP runs use workers.
The deterministic mock backend exercises this pipeline without solving physics.

## Execution and evidence

1. Discover a package and inspect the selected contract. The response includes the
   effective candidate schema, objectives, expected outputs, and provenance ID.
2. Validate compatibility, schema constraints, and execution policy.
   `prepare_run` is optional because `start_run` repeats these checks.
3. Capture provenance and persist a request. The worker reloads the current
   package and rejects changes relative to that request.
4. If checks are declared, a separate MATLAB invocation loads the model, applies
   the candidate, rebuilds geometry, and collects preflight evidence. A failed
   required check prevents study execution. No declarations means
   `not_configured`, not physics approval.
5. The evaluation invocation loads an isolated model, applies trusted parameter
   and switch bindings, executes the declared studies, evaluates measurements,
   and exports artifacts. It cleans up its owned COMSOL model tag.
6. Python parses the outputs and calls the package verifier. Fingerprints are
   checked after simulation and verification before returning a current result.

`inspect_model` uses the same fixed adapter and job machinery. It loads a saved
artifact without applying a candidate, rebuilding geometry, solving, or saving.
Facts, measurements, and provenance have deliberately separate meanings; see
[model observation](MODEL_OBSERVATION.md).

## Local job lifecycle

Each job has a unique directory, `request.json`, `state.json`, and a recorded
worker PID. State writes use temporary-file replacement. Completion adds a
`result.json`; simulation evidence includes provenance, summaries, and backend
artifacts as applicable. Failed runs are retained.

`get_run` waits until the revision changes, the job becomes terminal, or a bounded
wait expires (at most 55 seconds). It does not stream solver iterations. An agent
can reconnect and inspect files while a surviving worker continues, but there is
no heartbeat, dead-worker reconciliation, automatic retry, checkpoint resume, or
multi-machine scheduling. A killed worker can leave a stale `running` state.

Cancellation attempts to terminate the recorded process tree on Windows or
process group on POSIX and records `cancelled`. This is best effort: PID identity
is not independently revalidated, termination success is not confirmed, and an
existing COMSOL server is outside that worker tree. Backend timeout bounds each
MATLAB invocation, not an entire multi-invocation workflow or external server.
Use an operator-managed solver session and avoid concurrent jobs competing for
the same model resources.

## Contract limits

Candidate schemas support required fields, additional-field rejection, basic
top-level string/number/integer/object/array types, enums, and finite numeric
bounds. This is a **JSON Schema subset**: nested validation, array item schemas,
boolean type enforcement, string patterns, and general combinators are not
implemented. Package authors must not assume unsupported keywords are enforced.

Problem policy values override profile policy values. The active real-backend
gate, sweep limit, and MATLAB timeout are enforced; sweep estimates depend on
declared bindings and are not memory/runtime estimates. Legacy batch/request
count fields are retained in policy metadata but are not global quotas. Validation
is always performed by the public evaluation path.

Build and smoke reports are package-authoring conventions, not a core-enforced
certification gate. Verifier success applies only to the checks implemented by
that package. A numerically solved model may still represent the wrong physics.

## Trust model

The supported deployment is a trusted local user with trusted design packages.
Manifest profile/plugin paths are checked against the package root; artifact and
declared evidence paths may refer elsewhere. This is not filesystem isolation.
Python parser/verifier plugins execute with the service user's privileges.
Trusted package bindings and expressions are also executable model knowledge.

Candidates cannot supply raw code or arbitrary COMSOL commands through public
tools. This limits agent-facing authority but does not sandbox a malicious
package, secure an exposed network service, or authenticate multiple users.
Keep the STDIO service and solver access local to the intended operator.

Provenance hashes the model, contracts, manifests, core adapters, plugin sources,
and declared dependencies. Undeclared data, external software installations,
licenses, and hardware are not captured automatically. Hashes detect input drift;
they are not signatures, a complete reproducibility environment, or proof of
physical correctness. They include local paths and should be reviewed before
sharing run artifacts.

## Context efficiency

Discovery includes compatible problem IDs, and the contract bundles the schema
and verification requirements. Selective inspection avoids full model trees.
Revision-aware waits avoid short polling loops. Normal results bound strings,
lists, and dictionaries, with omission markers and paths to full artifacts.
Verifier metrics and limiting constraints are the primary iteration signal.

The optional agent skill recommends delegating routine reads and existing checks
to a specialist, retaining ambiguous physical and architectural decisions in the
main agent. This is a workflow convention, not an orchestration dependency.
