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
worker PID. State writes use temporary-file replacement, retried briefly while
another process (for example a polling reader on Windows) holds the file open.
Transitions take a per-job file lock, and terminal states are final. Completion
adds a `result.json`; simulation evidence includes provenance, summaries, and
backend artifacts as applicable. Failed runs are retained. A worker result
without a valid terminal status becomes `worker_failed` (kept as
`invalid_result.json`), and a result that arrives after cancellation is kept as
`late_result.json` without changing the `cancelled` verdict.

MCP tools are asynchronous: file I/O, hashing and plugin loading run in worker
threads, and waits sleep cooperatively, so one long-poll does not delay other
tool calls. `get_run` waits until the revision changes, the job becomes terminal,
or a bounded wait expires (at most 55 seconds). It does not stream solver
iterations. An agent can reconnect and inspect files while a surviving worker
continues, but there is no heartbeat, dead-worker reconciliation, automatic
retry, checkpoint resume, or multi-machine scheduling. A killed worker can leave
a stale `running` state.

LiveLink jobs (and CLI LiveLink evaluations) hold an operating-system lock for
the configured `COMSOL_SERVER_PORT`, so solves against one local server run one
at a time. A waiting job reports the non-terminal status `queued` and moves back
to `running` when it obtains the server.

Cancellation records `cancelled` first and then terminates the recorded worker
process tree (`taskkill /T` on Windows, the worker's process group on POSIX, where
the worker forwards termination to MATLAB's own group). The response reports
whether a termination signal was delivered. This is best effort: PID identity
is not independently revalidated, delivery is not proof that every descendant
exited, and an existing COMSOL server is outside that worker tree. Backend
timeout bounds each MATLAB invocation, not an entire multi-invocation workflow or
external server; on timeout the adapter terminates MATLAB's whole process tree
(the `matlab` launcher and the MATLAB process it starts), with output captured in
files rather than pipes so that the timeout cannot wait on a surviving child.

## Contract limits

Candidate schemas are a **JSON Schema subset**: `type` (string, number, integer,
boolean, object, array, null, or a list of these), `enum`, `const`, finite
numeric bounds and `multipleOf`, `minLength`/`maxLength`/`pattern`,
`items`/`minItems`/`maxItems`/`uniqueItems`, nested `properties`/`required`/
`additionalProperties`, and top-level `default`. Defaults are applied to the
normalized candidate, so the recorded values are the ones the contract
advertises. Combinators, references, conditionals and other unimplemented
validation keywords (`oneOf`, `$ref`, `format`, ...) are rejected with an error
instead of being silently ignored; other keys such as `description` or `unit`
are annotations. Non-finite numbers are rejected anywhere in a candidate.

For LiveLink profiles every candidate field must reach the model through
`model_bindings` (parameters, switches, or sweeps); a field that only a parser or
verifier uses must be listed in `model_bindings.unapplied_fields`. Parameter-bound
values must be numbers, and misspelled binding or ProblemSpec keys are reported.
A backend may only evaluate profiles declared for it: `backend="mock"` cannot
produce a verdict for a `matlab_livelink` profile.

Problem policy values override profile policy values. Policies are strict:
unknown keys, non-boolean switches and non-positive or non-integer limits are
errors, never silent fallbacks. Real solver runs require an explicit
`allow_real_backend: true`. The real-backend gate, sweep limit, and MATLAB timeout
are enforced; sweep estimates count every value the adapter will apply
(nested arrays included), candidate-supplied sweep values must be numbers so
COMSOL cannot expand an unbounded expression, and unsupported sweep bindings fail
before MATLAB starts. Estimates are not memory/runtime predictions. Legacy
batch/request count fields are retained in policy metadata but are not global
quotas. Validation is always performed by the public evaluation path.

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
