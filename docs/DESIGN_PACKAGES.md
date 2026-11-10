# Design package guide

## What belongs where

COMSOL MCP Verifier owns transport, validation, generic LiveLink execution, job state,
and artifact summaries. A design package owns everything that can change the
meaning of a simulation: model files, tags, parameter ranges, objectives,
parsers, verifiers, reference candidates, and engineering notes.

```text
<package>/
  em-design-package.yaml       discovery manifest
  README.md                    model assumptions and reproduction steps
  <model>.mph                  authoritative executable model
  <model>.m                    exported, reviewable reconstruction source
  profiles/*.yaml              safe physical knobs and COMSOL bindings
  problems/*.yaml              objectives, limits, and execution policy
  plugins/*_parser.py          exported-table to structured output
  plugins/*_verifier.py        deterministic metrics and margins
  references/                  optional material data and citations
  tests/                       optional package-level synthetic data/tests
  runs/                        generated job evidence; normally ignored
```

Store packages outside this repository and register their parent directory with
`EM_DESIGN_PACKAGE_ROOTS`. The default sibling name `em_design_modals` is retained
for compatibility; it is not a required package location. Synthetic examples in
`tests/fixtures/designs` demonstrate discovery without distributing model assets.

## Manifest

```yaml
schema_version: em_design_package_v1
package_id: my-model-family
description: One concise physical scope statement.
profiles: [profiles/*.yaml]
problems: [problems/*.yaml]
plugins:
  parsers:
    my_spectrum:
      path: plugins/my_spectrum_parser.py
      callable: parse_table_file
  verifiers:
    my_objective_verifier:
      path: plugins/my_objective_verifier.py
      callable: verify
      version: "1.0"
      description: Deterministic objective and validity checks.
      required_outputs: [my_spectrum]
```

Package, profile, problem, parser, and verifier IDs must be globally unique
across all configured roots. Manifest profile/problem/plugin entries may not
escape the package. Model artifact and declared evidence paths are trusted
configuration and may point elsewhere. Plugins execute locally with the service
user's privileges; only register packages you trust.

## Existing-model optimization

Expose only parameters that are stable in the saved model and safe for an agent
to vary. Every numeric field needs a physically justified minimum and maximum;
enums represent trusted structural switches. Keep study, feature, dataset,
table, and export tags in `model_bindings`, not in prompts or Python core.

Before agent use:

1. Save the authoritative `.mph` and retain a reviewable builder or `.m` export.
   Test reconstruction before claiming the source reproduces the saved model.
2. Verify each declared tag in the exported source and saved model.
3. Make the output table deterministic and declare its column mapping.
4. Add schema constraints and a real-run cost policy. Real runs need an explicit
   `execution_policy.allow_real_backend: true`; bound declared sweeps with
   `max_sweep_points`. Bind every candidate field in `model_bindings`, or list
   fields used only by the parser/verifier in `model_bindings.unapplied_fields`.
5. Test one known-good and one known-bad candidate.
6. Bind named measurements and preflight expectations to observed model facts;
   declare additional calibration/source dependencies in `provenance_files`.
7. Return continuous normalized margins and one limiting constraint so an agent
   can make the next change without reading full arrays.

## From-scratch models

A new geometry is a package-authoring task, not an unrestricted solver command.
Build and smoke-test the model first, then freeze a profile version around its
stable parameters. Structural changes create a new profile or package version.

Codex should author `automation/build_model.m` and `automation/smoke_model.m`
inside the new package, run them from its normal terminal, and make them write a
small `build_report.json` plus the authoritative `.mph`/exported `.m`. This is an
authoring-plane workflow owned by the coding agent and package; it is not exposed
as a raw-command MCP tool. Check the report's required cases and independent
physical validation, then register the bounded profile and use MCP jobs for
optimization. The core does not enforce a build-report admission gate. This
preserves the agent's ability to build from scratch without giving every MCP
consumer arbitrary code execution.

Prefer a coarse-to-fine mechanism:

1. analytical or mock feasibility check;
2. coarse mesh/spectrum screening problem;
3. narrowed confirmation problem;
4. final mesh/tolerance/robustness verifier.

Use separate ProblemSpecs when the objectives, limits, or output contracts
differ. This lets the agent change physics based on verifier evidence while
the MCP remains stateless about the design domain.

Candidate schema validation supports a limited top-level subset, and cost limits
depend on declared sweeps. See [contract limits](ARCHITECTURE.md#contract-limits)
before relying on schema keywords or treating policy fields as quotas. An
onboarding checker pass establishes configuration consistency, not physical validity.

## Run storage

The default run root is `<package>/runs/<job_id>/`. The service creates unique,
time-stamped job IDs and defaults solver outputs to a directory within the run.
Profiles may override solver output locations; use returned artifact paths. Set
`EM_DESIGN_MCP_RUNS_DIR` only when a central compatibility location is required.

Do not delete failed runs automatically. They retain the request and whatever
evidence was produced before failure; a table or final summary may not exist.
Use the recorded status, errors, and available artifacts for diagnosis.
