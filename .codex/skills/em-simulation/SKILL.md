---
name: em-simulation
description: "Operate agent-first COMSOL electromagnetic and photonic design workflows through external design packages. Use when Codex must discover an existing model, inspect allowed parameters, validate and run a candidate, iterate from verifier feedback, or scaffold a from-scratch model package without embedding model knowledge in COMSOL MCP Verifier."
---

# EM simulation workflow

Use the MCP as an execution service, not as an engineering notebook. Treat the
selected profile, problem, parser, and verifier as one versioned contract.

## Existing model

1. Call `discover_designs` once, with a narrow query when possible.
2. Call `inspect_contract` once for the selected profile/problem pair. Do not
   invent fields or exceed the returned candidate ranges.
   Use `inspect_model` with selected topics when actual excitation, periodic,
   material/selection, study/solution/dataset or output facts are needed. Select
   package `measurement_ids` for quantities; reuse `get_run` for its job receipt.
   Saved model facts do not prove solution freshness. Check `solution_freshness`
   and `recomputed_solutions`; use `source_job_id` for a saved run artifact.
3. Form the strongest justified candidate from the task, existing artifacts,
   and prior verifier metrics. Use `prepare_run` only when the candidate or
   expected cost is uncertain; `start_run` validates again.
4. Call `start_run` with the inspected `provenance_id` and a server-side wait. If it returns non-terminal, call
   `get_run` with its `revision` and a long wait. Do not poll on a timer.
5. Prefer compact metrics, normalized margins, limiting constraint, and agent
   feedback. Request `include_result=true` only when arrays or detailed evidence
   are necessary.
6. Change one physically meaningful cause per iteration. Stop on the task's
   declared target, budget, or a verifier-reported hard constraint.

## New model

Create an external package and register its root with `EM_DESIGN_PACKAGE_ROOTS`;
never put production model knowledge inside COMSOL MCP Verifier. The default sibling
directory `em_design_modals` is a compatibility convention. Use:

```text
<family>/
  em-design-package.yaml
  README.md
  model.mph
  model.m
  profiles/<profile>.yaml
  problems/<problem>.yaml
  plugins/<parser>.py
  plugins/<verifier>.py
  runs/                  # generated, ignored by version control
```

Retain a builder or `.m` export alongside `.mph`; test reconstruction before
claiming the source reproduces the model. Expose only stable, bounded,
high-level parameters. Keep COMSOL tags and output-column bindings in the
profile. Make the parser deterministic and the verifier return continuous
margins plus a limiting constraint. Test a baseline candidate before asking an
agent to optimize it.

For construction, write package-owned `automation/build_model.m` and
`automation/smoke_model.m`, run them from the normal Codex terminal, and emit a
compact `build_report.json`. Do not route arbitrary build commands through MCP.
Check required smoke cases and independent physical validation before freezing
the bounded profile for MCP jobs. Build-report review is a package workflow; the
core does not enforce a promotion gate. Record the validated scope and omissions.

## Safety and token discipline

- Never expose an unrestricted COMSOL or MATLAB command tool.
- Never mutate geometry tags outside the declared bindings for an existing
  profile; create a new profile/package version for structural changes.
- Keep full solver tables and logs on disk. Return paths and compact summaries.
- Reuse the provenance ID within one task; re-inspect when the artifact, contract,
  parser/verifier, or declared evidence changes. Never treat an old pass as current.
- Delegate routine inspection to the configured COMSOL specialist when available.
  Give it profile IDs, requested facts and artifact paths; request compact findings
  with uncertainties. Keep architectural and difficult physical judgments with the
  main agent. Do not relay full model trees, schemas, spectra or unchanged contracts.
- Establish uncertain COMSOL conventions from local/official references once, then
  encode reusable deterministic checks or package verifiers.
- Preserve failed runs as evidence unless the user explicitly requests cleanup.
