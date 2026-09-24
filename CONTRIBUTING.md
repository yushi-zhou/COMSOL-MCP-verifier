# Contributing

Changes should make bounded simulation workflows easier to inspect, verify, and
reproduce. Start with [architecture](docs/ARCHITECTURE.md) and [AGENTS.md](AGENTS.md).
Contributions to this repository are provided under its [MIT License](LICENSE).
Only contribute material you have the right to distribute. Commercial solver
software, external models and third-party data are not covered by this license.

## Scope

- Keep the core model-agnostic. Production models, builders, profiles, objectives,
  parsers, verifiers, calibration evidence, and physics regressions belong in
  external design packages.
- Prefer extending an existing mechanism to adding tools. Do not expose raw code,
  shell commands, arbitrary expressions, or unrestricted COMSOL mutations.
- Preserve the `em_design_mcp_cli_v1` envelope and existing public operations.
  Propose an explicit migration for intentional incompatibilities.
- Treat package plugins as trusted executable code. A validation check should
  state what it proves and fail clearly when its required evidence is unavailable.

## Development

Use an editable source installation: `python -m pip install -e ".[test]"`.
Run `python -m pytest -q` and `git diff --check`. See [testing](docs/TESTING.md)
for the distinction between mock, adapter, source-only, and licensed solver tests.
No formatter or typing migration is required for an unrelated fix.

Keep PRs focused. Explain the concrete failure or user need, the resulting
behavior, relevant checks, and remaining limits. Add regression tests for runtime
fixes; documentation-only changes should verify links and executable examples.
Use synthetic fixtures under `tests/fixtures/`; do not copy production packages
into the test suite. Real solver tests and their model assets belong in external
packages. Do not claim a model is physically validated from a passing mock test
or a successful solve.

## Reporting issues

Include the revision, Python/platform information, selected operation, expected
behavior, and a minimal sanitized reproducer. For LiveLink failures include the
COMSOL/MATLAB versions and error category. Inspect logs and provenance for personal
paths, unpublished parameters, credentials, and licensed content before sharing.
Never post credentials or private model files in a public issue.

Follow [the release checklist](docs/PUBLICATION.md) before publishing a version.
Keep generated models, run evidence, local configuration, and solver logs out of
source commits.
