# Platform contract schemas

All three documents are strict, versioned mappings. Unknown fields, duplicate
JSON/YAML keys, non-finite numbers, wrong scalar types, and contradictory
field combinations are errors. Optional fields may be omitted; `null` is not a
substitute for a required value.

SHA-256 values are lowercase 64-character hexadecimal strings. Timestamps are
ISO-8601 values with an explicit offset (`Z` or `+00:00`). Seeds are unsigned
32-bit integers (`0..4294967295`).

## ExperimentSpec (`platform-experiment-spec-v2`)

Required top-level fields:

| Field | Contract |
|---|---|
| `schema_version` | Exact version above |
| `experiment_id` | Stable 3–128 character identifier |
| `campaign_kind` | `normal` or `attack` |
| `worlds` | Non-empty unique `WorldRef` list; every world pins its SHA-256 |
| `repetitions` | Attempts per world, `1..1000` |
| `seeds` / `seed_policy` | Exactly one; one seed per repetition |
| `transport_mode` | `nosip` or `aiottalk_rtp` |
| `feature_set` | Name, exact ordered columns, catalog path and catalog SHA-256 |
| `runtime` | Runtime limits and transport switches |
| `acceptance` | Retention, outcome, quality and attribution gates |
| `provenance` | Author, timestamp and tool version |

Optional top-level fields are `description`, `data_split`, `attack_plan`,
`network_profile`, and free-form `labels`.

`data_split.unit` is always `run`; row-level splitting is intentionally
unsupported. Its train/validation/test counts must total
`acceptance.accepted_runs_per_world`.

An attack spec must include an `attack_plan`, preserve non-success logs, use
the mission-aware runtime, and disable the normal-flight quality gate. A normal
spec must not include an attack plan.

Both the ordered columns and the catalog content digest are required in v2, so
changing a feature catalog changes the spec identity even if its path stays
the same. `feature_set.columns` must contain only signals available to the deployed
detector. `e_pos`, `px_gt`, `py_gt`, `pz_gt`, and names explicitly marked
`gt_*`, `*_gt`, `ground_truth`, or `groundtruth` are rejected. Ground truth remains valid in
quality/evaluation records, never in model input.

## RunArtifact (`platform-run-artifact-v2`)

A run record pins:

- composite `run_uid` (`world.name/run_id`);
- experiment ID and ExperimentSpec identity digest;
- campaign, world file digest, transport, required uint32 seed, outcome, and run-level split;
- exact ordered feature columns;
- one or more file references, including exactly one `kpi_log`;
- quality and timing summaries;
- the actual injected attack for attack runs;
- recording timestamp and provenance.

Every file reference carries `role`, `path`, and `sha256`; optional byte/row
counts help detect incomplete transfers. Normal training/validation/test runs
must have `SUCCESS_FINISH` and `quality_ok=true`. Attack runs cannot enter
train/validation. An attack test run must be attributable, but may have a
non-success outcome and `quality_ok=false`; those are evaluation results, not
normal training data.

## ModelArtifact (`platform-model-artifact-v2`)

A model record pins:

- model UID, experiment ID/digest, algorithm and optional framework;
- exact ordered feature columns;
- disjoint normal train, validation, and optional normal test `run_uid` lists;
- independent `evaluation_data` groups, each pinning one attack experiment ID,
  digest, and an explicit allowlist of attack `test_run_uids`;
- threshold value, selection policy, and the validation split used to choose it;
- exactly one `model` and one `threshold` file reference;
- optional numeric metrics, timestamp, and provenance.

`run_uid` is not globally unique. `validate_lineage(model, runs)` resolves all
references by `(experiment_digest, run_uid)`. Normal data must match the
model's training experiment; attack data must match an `evaluation_data`
allowlist, campaign kind, test split, attribution, feature-set name, and
ordered columns. Reusing the same KPI-log content digest for different
lineage entries is rejected.

`validate_full_lineage(model, training_spec, evaluation_specs, runs)` is the
deployment/release gate. In addition to the checks above, it recomputes every
actual spec identity and checks campaign kind, transport, world name and
SHA-256, seed, and feature schema. This prevents a self-consistent set of
invented IDs/digests from passing without the reviewed experiment specs.

## File verification boundary

Parsing and lineage validation perform no filesystem I/O. They validate the
recorded metadata only. Call `verify_file_ref` or `verify_file_refs`
explicitly to check that a file currently exists and that its size and
SHA-256 match. Row-count verification remains format-specific and is outside
this generic contract layer.

## Digests

`record.digest()` hashes deterministic canonical JSON for the complete record.
`ExperimentSpec.spec_digest()` excludes provenance and is the identity stored
by run/model lineage. File content uses `sha256_file(path)`. These are integrity
fingerprints, not digital signatures and not encryption.
