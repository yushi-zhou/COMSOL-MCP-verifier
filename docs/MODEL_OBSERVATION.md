# Inspecting existing models

Discover a design and read its contract once. Use `inspect_model` with a profile
ID and selected topics. Omit `problem_id` when only model facts are needed.

```json
{"model_profile_id":"example_model","topics":["excitation","periodic","studies"]}
```

The inspection loads the saved model; it never solves, rebuilds geometry, or
saves the model. Like `start_run`, it returns a persistent job with a revision;
use `get_run` with that revision and a server-side wait if it is still running.
Full facts and arrays remain in `facts_path`/`result_path`. Compact responses
limit lists, dictionaries, and strings and explicitly report omitted entries.
`get_run(include_result=true)` retrieves the full result when necessary.

| Topic | Facts |
|---|---|
| `studies` | Study features and physics activation settings; solutions, saved sample values, emptiness; dataset-to-solution-to-study links |
| `physics` | Interface types, activation and selections |
| `excitation` | Port/scattering/background settings, local and inherited activation, raw field vectors and evaluable parameter expressions |
| `periodic` | Periodic/Floquet feature settings, wave-vector expressions and selections |
| `materials` | Material groups, declared constitutive properties and assigned entities |
| `selections` | Named selections, dimensions, geometry, entity counts and IDs |
| `mesh` | Mesh statistics and sizing/copy-feature settings |
| `outputs` | Numerical evaluations, exports and referenced plots: expressions, units, datasets, axes, tables and selections |

COMSOL properties are reported by their actual names. Unsupported reads appear
in `issues`; absent fields are not inferred. Numeric configuration expressions
are evaluated without selecting a saved solution. Field-dependent material
properties may remain unevaluated. Interface activation and per-study activation
are distinct facts; a locally active port is not proof that a study excites it.
This is a selective inspector, not a complete COMSOL tree or a general expression
evaluation endpoint. Plot rendering and arbitrary postprocessing remain external.

## Package declarations

Add `preflight`, `measurements`, and (when needed) `provenance_files` to an external
ModelProfile. ProblemSpecs may also declare preflight checks and provenance files.
No core source changes or model-name registration are required. Public requests
select measurement IDs; expressions and bindings come only from trusted packages.

Example declarations below use illustrative tags that a package author must
replace with observed model tags:

```yaml
preflight:
  - id: driven_port
    kind: excitation
    target: comp1/wave/port1
    expected: {PortExcitation: "on", InputType: H}
    expected_values:
      alpha1_inc: {value: 0.0, unit: rad, atol: 1.0e-12}
  - id: solution_binding
    kind: dataset_binding
    target: data_optical
    study: study_optical
    solution: solution_optical
    require_nonempty: false
measurements:
  - id: absorbed_power
    expression: Q
    method: integrate
    study: study_optical
    solution: solution_optical
    dataset: data_optical
    unit: W
    selection: illuminated_body
    dimension: volume
    solnum: all
    outersolnum: all
    normalization: {expression: incident_power, unit: W}
  - id: peak_temperature
    expression: T
    method: maximum
    study: study_thermal
    solution: solution_thermal
    dataset: data_thermal
    unit: K
    selection: heated_body
    dimension: volume
provenance_files:
  - validation/calibration.json
  - sources/build_model.m
```

Methods are `global`, `integrate`, `average`, and `maximum`. Spatial methods
require a nonempty named selection and `line`, `surface`, or `volume` dimension.
Global expressions cannot also declare a selection; package coupling operators
can be part of the expression. A selection's material assignment can be inspected
or separately checked. `solnum` and `outersolnum` default to `all`, or accept a
positive integer. Complex values retain real/imaginary arrays and shape metadata;
bindings include saved solution sample values, not just current model parameters.

Each measurement verifies its dataset's unambiguous source chain, declared
solution and study, nonempty solution, selection and returned units. Multi-source
datasets are rejected. Different measurements may use different physics datasets.
COMSOL 6.0 spatial helpers return native units without a unit conversion option;
the declared unit must exactly match that returned unit. Global measurements use
COMSOL's requested unit and verify the returned unit. Optional normalization
evaluates a global denominator on the same dataset and solution indices, checks
matching numerator/denominator units and nonzero finite values, and returns a
dimensionless ratio. Missing/invalid values fail instead of becoming zeros.

To read saved quantities, pass `measurement_ids` to `inspect_model`. Without
IDs, no measurements are evaluated; their definitions remain discoverable.
`start_run` evaluates all declared measurements after the configured ordered
`model_bindings.tags.studies` (or existing single `study`) completes. Legacy table
exports and parser plugins continue to work alongside named measurements.

## Deterministic preflight

Supported checks are deliberately small:

| Kind | Requirement |
|---|---|
| `physics_active` | Identified interface is active |
| `excitation` / `periodic` | Feature and parents are active; explicit expected properties match exactly |
| `selection_nonempty` | Named selection has observed entities |
| `material_selection` | Active material covers exactly the declared selection's component, geometry, dimension and entity set |
| `dataset_binding` | Dataset resolves to specified solution/study; optionally requires nonempty data |
| `mesh_present` | Observed mesh contains elements |

Targets use `component/tag` or `component/physics/feature` IDs, except datasets
which use their COMSOL tag. Check IDs must be unique across profile and problem.
Unknown check kinds, unsupported options, missing targets and unavailable required
facts fail explicitly. No declarations returns `not_configured`, not a physics
approval. `prepare_run` validates declarations but does not open COMSOL.

`expected` compares raw configuration values. For a parameter expression such as
an incidence angle, use `expected_values` to compare its evaluated real scalar,
explicit returned unit and absolute tolerance. An unchanged expression name does
not imply an unchanged physical value. This intentionally small check rejects
unavailable, complex or vector values and performs no guessed unit conversions.

Before a real solve, preflight inspects a loaded copy after applying the candidate
and rebuilding geometry so entity selections describe that candidate. Failure
stops before study execution and preserves inspection evidence. This currently
requires a separate MATLAB invocation; standalone inspection never applies a
candidate. Saved mesh/solution checks concern existing state, so template packages
should not demand already-computed data that their study is intended to produce.

These checks do not prove Maxwell-equation correctness, convergence, correct
port normal conventions, or physical normalization. Package verifiers retain
those responsibilities. Official COMSOL references are needed when establishing
a new uncertain convention, not during every preflight execution.

## Provenance and freshness

`inspect_contract` and `prepare_run` return a provenance ID. Pass it as
`start_run(provenance_id=...)` to reject changes since inspection. Runs always
capture their inputs and recheck at worker startup, after simulation and after
verification. Changed inputs produce `stale_provenance`, never a passing result.
Fingerprints cover model bytes, complete active contracts, manifests, companion
files, core Python/MATLAB adapters, parser/verifier sources and adjacent Python
helpers. Declare additional imported sources, calibration files, or other
dependencies in `provenance_files`; undeclared external data cannot be inferred.
Public requests rediscover manifests, avoiding stale in-memory contracts.

File identity and solution freshness are separate. An arbitrary saved `.mph`
may contain old solutions even when dataset tags and current parameters look
correct. Inspection labels these `unverified_saved_solution`.

For named measurements in a new solve, the isolated loaded copy clears only
referenced solution data before executing the declared studies. The measurement
adapter then requires these solutions to be nonempty and correctly bound. This
prevents reusing an untouched solution that happens to belong to the same study.
`recomputed_solutions` records that limited guarantee. Continuation/warm-start
from those saved solution vectors is not supported by this measurement workflow;
it needs an explicit future package policy. Source `.mph` files are unchanged.

With `model_bindings.outputs.save_solved_model: true`, a run records the solved
artifact's SHA-256. Pass its job ID as `inspect_model(source_job_id=...)` to inspect
that exact artifact; changed model/contract/code or modified solved bytes reject
reuse. Only solutions in the producing run's `recomputed_solutions` receive a
freshness receipt. Unrelated saved solutions and legacy table-only outputs remain
unverified. Old run results remain readable as historical artifacts.

The version-sensitive API choices were checked against the installed COMSOL 6.0
LiveLink function documentation (`mphglobal`, `mphint2`, `mphmean`, `mphmax`,
`mphsolinfo`, `mphevaluate`) and the Java API reference for
`SolverSequence.clearSolutionData()` / `isEmpty()`. These references establish
adapter behavior; they are not runtime dependencies.
