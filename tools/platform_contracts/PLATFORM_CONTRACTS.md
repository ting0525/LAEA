# FedDroneLab platform contracts

This package is the first, deliberately non-invasive platform foundation:
versioned experiment intent, run lineage, and model lineage. It does not start
Gazebo/ROS, modify a collection registry, schedule Kubernetes jobs, or write to
campaign logs.

## Quick start

Run from the LAEA repository root:

```bash
python3 -m tools.platform_contracts validate spec \
  tools/platform_contracts/examples/normal_experiment.json

python3 -m tools.platform_contracts validate spec \
  tools/platform_contracts/examples/attack_experiment.json --json

python3 -m tools.platform_contracts digest spec \
  tools/platform_contracts/examples/normal_experiment.json --identity

python3 -m tools.platform_contracts validate model model_artifact.json \
  --spec normal_experiment.json \
  --evaluation-spec gps_attack_experiment.json \
  --run train_run.json --run validation_run.json --run attack_test_run.json

python3 -m tools.platform_contracts file-digest model.onnx
```

When model `--run` inputs are provided, `--spec` is mandatory.
`--evaluation-spec` is repeatable and must exactly cover the model's declared
attack evaluation groups.

Validation and digest commands are read-only. Exit status is `0` for success
and `2` for a parse, validation, lineage, or file error.

JSON works with the Python standard library. `.yaml` / `.yml` work when
PyYAML is installed; otherwise the loader returns an actionable error. Both
loaders reject duplicate keys.

## Intended lifecycle

1. Validate and freeze one `ExperimentSpec` before a campaign starts.
2. Store its `spec_digest()` in every accepted `RunArtifact`.
3. Assign complete runs—not CSV rows—to disjoint train/validation/test splits.
4. Record exact ordered feature columns and file SHA-256 values.
5. Train a model and write a `ModelArtifact` referencing those run UIDs.
6. Keep attack test allowlists in separate `evaluation_data` groups identified
   by attack experiment ID and digest.
7. Call `validate_full_lineage` with the actual normal and attack specs before
   export/deployment.
8. Explicitly call `verify_file_ref(s)` when current on-disk artifact
   existence, size, and content digest must also be verified.

Pure contract parsing and lineage checks never read the paths recorded inside
`FileRef`; this keeps validation deterministic and free of hidden I/O. File
verification is a separate opt-in API. The contracts do not yet adapt existing active registries. A later, separately
reviewed adapter can translate completed campaign cards/manifests into
`RunArtifact` documents without changing the source logs.

See [SCHEMA.md](SCHEMA.md) for field semantics and
[examples](examples) for valid normal/attack specifications.

## Compatibility

- Python 3.8+.
- Standard library only for JSON and all validation/digest operations.
- Optional PyYAML only for YAML input.
- No pydantic/jsonschema/ROS dependency.

## Tests

```bash
python3 -m unittest discover -s tools/platform_contracts/tests -v
python3 -m py_compile tools/platform_contracts/*.py \
  tools/platform_contracts/tests/*.py
```
