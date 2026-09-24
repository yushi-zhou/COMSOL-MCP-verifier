# Release checklist

COMSOL MCP Verifier is the canonical repository for the generic MCP/verifier
core. Release only reviewed source and COMSOL-free synthetic fixtures.

## Required checks

- [ ] Confirm that the MIT license notice and copyright attribution remain
  present. Dependencies, commercial solver software, external model packages,
  and third-party datasets retain their separate licensing terms.
- [ ] Review the current source tree and staged changes for credentials, private
  URLs, personal paths, unpublished research, and copied third-party material.
- [ ] Ensure no generated MPH files, run directories, logs, local environment
  files, agent checkpoints, or private audit reports are staged.
- [ ] Verify README commands, documentation links, supported installation, and
  compatibility wording against the release revision.
- [ ] Run an editable installation, `pip check`, the COMSOL-free tests, the mock
  CLI example, and `git diff --check`. Review the GitHub Actions result separately.
- [ ] If claiming new solver compatibility, run a small real LiveLink workflow
  with an external package and record the exact COMSOL build, MATLAB release,
  tested steps, and limitations. Keep that package and generated evidence out
  of core source commits.
- [ ] Keep COMSOL-free CI evidence separate from licensed real-solver evidence.
  A workflow smoke test is not a physics-module compatibility matrix.
- [ ] Choose the version and prepare release notes covering behavior changes,
  compatibility, fixes, known limits, and whether real solver checks were run.
- [ ] Review any release attachments independently; distribute source, not
  private design packages, generated models, or solver artifacts by default.

## Repository metadata

Description:

> Verification-first COMSOL MCP workflows with bounded contracts, model inspection, provenance, and deterministic verification.

Topics: `comsol`, `mcp`, `model-context-protocol`, `simulation`, `multiphysics`,
`scientific-computing`, `verification`, `reproducibility`, `python`,
`engineering-automation`.

Repository: <https://github.com/yushi-zhou/comsol-mcp-verifier>

Use the repository documentation as the homepage until a separate documentation
site is maintained. Do not add badges for unmeasured or unverified claims.

## Optional follow-ups

Standalone wheel/resource support, worker crash reconciliation, more reliable
cancellation, and additional licensed-platform smoke tests can be developed when
needed. They are not claims made by this source release.
