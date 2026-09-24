# `matlab/` — generic LiveLink adapters

This repository is model-agnostic (see [`../AGENTS.md`](../AGENTS.md) and
[`../docs/DESIGN_PACKAGES.md`](../docs/DESIGN_PACKAGES.md)). These generic MATLAB
adapters belong here:

- `run_em_design_from_json.m` — reads a candidate/contract JSON, drives COMSOL via
  LiveLink, and writes the result table. It contains no model-specific knowledge.
- `em_model_facts.m` — selective actual model facts with explicit read issues.
- `em_named_measurements.m` — package-owned measurements with checked dataset,
  solution, study, selection, and units.

Everything model-specific — geometry builders, sweep/analysis helpers, per-family
post-processing — lives in an external **design package** registered through
`EM_DESIGN_PACKAGE_ROOTS`,
never in this folder. `.gitignore` restricts `matlab/` to these adapters and this
README so model scripts do not re-accumulate in the engine.
