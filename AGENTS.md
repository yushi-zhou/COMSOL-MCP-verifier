# Repository instructions

- Keep this repository model-agnostic. Production profiles, problems, model
  sources, parsers, and verifiers belong in an external `em_design_package_v1`
  package.
- Preserve the `em_design_mcp_cli_v1` JSON envelope for EM-harness unless a
  versioned migration is explicitly requested.
- Public MCP tools must remain compact and agent-oriented. Prefer server-side
  waits and artifact paths over repeated status calls or embedded solver arrays.
- Do not add raw MATLAB, Java, shell, or unrestricted COMSOL command execution.
- Use `tests/fixtures/designs` for COMSOL-free core tests. Real solver tests are
  opt-in and should use an external package.
