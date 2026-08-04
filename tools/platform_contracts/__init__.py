"""FedDroneLab's versioned experiment and lineage contracts.

The public imports below are intentionally small and stable.  Construct records
through ``from_dict`` or the file loaders so strict validation always runs.
"""
from .canonical import canonical_json, digest_payload, sha256_file
from .errors import (
    ArtifactVerificationError,
    ContractError,
    ContractValidationError,
    LineageValidationError,
    SerializationError,
    SpecValidationError,
    ValidationIssue,
)
from .experiment_spec import ExperimentSpec, SCHEMA_VERSION
from .io import (
    load_document,
    load_experiment_spec,
    load_model_artifact,
    load_run_artifact,
)
from .lineage import (
    MODEL_ARTIFACT_SCHEMA_VERSION,
    RUN_ARTIFACT_SCHEMA_VERSION,
    EvaluationDataRef,
    FileRef,
    ModelArtifact,
    RunArtifact,
    validate_full_lineage,
    validate_lineage,
    verify_file_ref,
    verify_file_refs,
)

__all__ = (
    "ArtifactVerificationError",
    "ContractError",
    "ContractValidationError",
    "EvaluationDataRef",
    "ExperimentSpec",
    "FileRef",
    "LineageValidationError",
    "MODEL_ARTIFACT_SCHEMA_VERSION",
    "ModelArtifact",
    "RUN_ARTIFACT_SCHEMA_VERSION",
    "RunArtifact",
    "SCHEMA_VERSION",
    "SerializationError",
    "SpecValidationError",
    "ValidationIssue",
    "canonical_json",
    "digest_payload",
    "load_document",
    "load_experiment_spec",
    "load_model_artifact",
    "load_run_artifact",
    "sha256_file",
    "validate_full_lineage",
    "validate_lineage",
    "verify_file_ref",
    "verify_file_refs",
)
