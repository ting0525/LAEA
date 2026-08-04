"""Lineage records: what a campaign actually produced, and what was trained from it.

Two immutable record types close the loop from an :class:`ExperimentSpec` to a
deployed detector:

``RunArtifact``
    one accepted flight, joined to its experiment by ``experiment_digest`` and
    identified by the composite ``"<world>/<run_id>"`` used by
    ``build_normal_campaign_registry.py`` (per-map run numbering restarts at
    ``run_001``, so the bare run id is not unique across a campaign).

``ModelArtifact``
    one trained detector, pinning normal train/validation/test separately from
    allowlisted cross-campaign attack evaluation runs, plus ordered feature
    columns, threshold provenance, and deployable files.

:func:`validate_lineage` cross-checks a model against the run artifacts it
claims to be trained from, which is where split leakage and feature-schema
drift are caught.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .base import Record, prune
from .canonical import sha256_file
from .errors import ArtifactVerificationError, LineageValidationError
from .experiment_spec import (
    ATTACK_MODES_BY_SOURCE,
    ATTACK_SEVERITIES,
    ATTACK_SOURCES,
    CAMPAIGN_KINDS,
    ExperimentSpec,
    FeatureSetRef,
    Provenance,
    RUN_OUTCOMES,
    TRANSPORT_MODES,
    WorldRef,
)
from .validation import (
    IDENTIFIER_RE,
    IssueLog,
    NAME_RE,
    UINT32_MAX,
    as_mapping,
    child,
    get_bool,
    get_digest,
    get_float,
    get_int,
    get_str,
    get_str_list,
    get_list,
    get_timestamp,
    index_path,
    reject_unknown_keys,
)

RUN_ARTIFACT_SCHEMA_VERSION = "platform-run-artifact-v2"
MODEL_ARTIFACT_SCHEMA_VERSION = "platform-model-artifact-v2"

SPLITS = ("train", "val", "test", "unassigned")
TRAINING_SPLITS = ("train", "val", "test")
DATA_FILE_ROLES = (
    "kpi_log",
    "run_manifest",
    "quality_manifest",
    "collection_card",
    "features",
    "other",
)
MODEL_FILE_ROLES = (
    "model",
    "threshold",
    "feature_columns",
    "training_config",
    "metrics",
    "deploy_bundle",
    "scored_samples",
)
REQUIRED_MODEL_FILE_ROLES = ("model", "threshold")
THRESHOLD_SELECTION_SPLITS = ("val",)
TIMING_TOLERANCE_S = 0.01


@dataclass(frozen=True)
class FileRef(Record):
    """A file on disk, pinned by SHA-256.

    The digest is an integrity and deduplication fingerprint; it says nothing
    about who produced the file.
    """

    FIELDS = ("role", "path", "sha256", "relative_path", "size_bytes", "num_rows")
    REQUIRED = ("role", "path", "sha256")

    role: str
    path: str
    sha256: str
    relative_path: Optional[str] = None
    size_bytes: Optional[int] = None
    num_rows: Optional[int] = None

    @classmethod
    def from_dict(
        cls, data: Any, issues: IssueLog, path: str, *, roles: Sequence[str]
    ) -> Optional["FileRef"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        role = get_str(issues, mapping, "role", path, choices=roles)
        file_path = get_str(issues, mapping, "path", path)
        sha256 = get_digest(issues, mapping, "sha256", path)
        relative_path = get_str(issues, mapping, "relative_path", path, required=False)
        size_bytes = get_int(issues, mapping, "size_bytes", path, required=False, minimum=0)
        num_rows = get_int(issues, mapping, "num_rows", path, required=False, minimum=0)
        if role is None or file_path is None or sha256 is None:
            return None
        return cls(
            role=role,
            path=file_path,
            sha256=sha256,
            relative_path=relative_path,
            size_bytes=size_bytes,
            num_rows=num_rows,
        )

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "role": self.role,
                "path": self.path,
                "sha256": self.sha256,
                "relative_path": self.relative_path,
                "size_bytes": self.size_bytes,
                "num_rows": self.num_rows,
            }
        )


@dataclass(frozen=True)
class QualityMetrics(Record):
    """Independent quality summary for one run.

    Field names match the columns emitted by ``tools/dt_ids/build_run_manifest.py``
    and copied into the campaign registry.
    """

    FIELDS = ("num_rows", "duration_s", "gps_valid_ratio", "e_pos_p95", "e_pos_max", "quality_ok")
    REQUIRED = FIELDS

    num_rows: int
    duration_s: float
    gps_valid_ratio: float
    e_pos_p95: float
    e_pos_max: float
    quality_ok: bool

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["QualityMetrics"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        num_rows = get_int(issues, mapping, "num_rows", path, minimum=1)
        duration_s = get_float(issues, mapping, "duration_s", path, minimum=0.0)
        gps_valid_ratio = get_float(issues, mapping, "gps_valid_ratio", path, minimum=0.0, maximum=1.0)
        e_pos_p95 = get_float(issues, mapping, "e_pos_p95", path, minimum=0.0)
        e_pos_max = get_float(issues, mapping, "e_pos_max", path, minimum=0.0)
        quality_ok = get_bool(issues, mapping, "quality_ok", path)
        values = (num_rows, duration_s, gps_valid_ratio, e_pos_p95, e_pos_max, quality_ok)
        if any(value is None for value in values):
            return None
        if e_pos_p95 > e_pos_max:
            issues.add(child(path, "e_pos_p95"), "the 95th percentile cannot exceed the maximum")
            return None
        return cls(
            num_rows=num_rows,
            duration_s=duration_s,
            gps_valid_ratio=gps_valid_ratio,
            e_pos_p95=e_pos_p95,
            e_pos_max=e_pos_max,
            quality_ok=quality_ok,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_rows": self.num_rows,
            "duration_s": self.duration_s,
            "gps_valid_ratio": self.gps_valid_ratio,
            "e_pos_p95": self.e_pos_p95,
            "e_pos_max": self.e_pos_max,
            "quality_ok": self.quality_ok,
        }


@dataclass(frozen=True)
class RunTiming(Record):
    """Mission clock for one run, using the run manifest's field names."""

    FIELDS = ("started_at_s", "ended_at_s", "duration_s")
    REQUIRED = FIELDS

    started_at_s: float
    ended_at_s: float
    duration_s: float

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["RunTiming"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        started = get_float(issues, mapping, "started_at_s", path, minimum=0.0)
        ended = get_float(issues, mapping, "ended_at_s", path, minimum=0.0)
        duration = get_float(issues, mapping, "duration_s", path, minimum=0.0)
        if started is None or ended is None or duration is None:
            return None
        if abs((ended - started) - duration) > TIMING_TOLERANCE_S:
            issues.add(
                path,
                f"duration_s {duration} does not match ended_at_s - started_at_s ({ended - started})",
            )
            return None
        return cls(started_at_s=started, ended_at_s=ended, duration_s=duration)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at_s": self.started_at_s,
            "ended_at_s": self.ended_at_s,
            "duration_s": self.duration_s,
        }


@dataclass(frozen=True)
class AttackRunRecord(Record):
    """What the injector actually did during one attack run.

    ``attributable`` encodes the rule ``tools/dt_ids/build_attack_eval.py``
    applies: a run only counts as attack evidence when the attack fired and the
    flight survived at least until the onset.  A run that failed before onset
    failed on its own.
    """

    FIELDS = (
        "profile",
        "source",
        "mode",
        "severity",
        "seed",
        "scheduled_onset_s",
        "actual_onset_s",
        "attributable",
    )
    REQUIRED = ("profile", "source", "mode", "severity", "attributable")

    profile: str
    source: str
    mode: str
    severity: str
    attributable: bool
    seed: Optional[int] = None
    scheduled_onset_s: Optional[float] = None
    actual_onset_s: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["AttackRunRecord"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        profile = get_str(issues, mapping, "profile", path, pattern=NAME_RE)
        source = get_str(issues, mapping, "source", path, choices=ATTACK_SOURCES)
        mode = get_str(issues, mapping, "mode", path)
        severity = get_str(issues, mapping, "severity", path, choices=ATTACK_SEVERITIES)
        attributable = get_bool(issues, mapping, "attributable", path)
        seed = get_int(issues, mapping, "seed", path, required=False, minimum=0, maximum=UINT32_MAX)
        scheduled = get_float(issues, mapping, "scheduled_onset_s", path, required=False, minimum=0.0)
        actual = get_float(issues, mapping, "actual_onset_s", path, required=False, minimum=0.0)
        if source is not None and mode is not None and mode not in ATTACK_MODES_BY_SOURCE[source]:
            issues.add(child(path, "mode"), f"{mode!r} is not a source-layer mode for {source!r}")
            mode = None
        required = (profile, source, mode, severity, attributable)
        if any(value is None for value in required):
            return None
        if attributable and not actual:
            issues.add(
                child(path, "actual_onset_s"),
                "an attributable run needs a positive actual onset",
            )
            return None
        return cls(
            profile=profile,
            source=source,
            mode=mode,
            severity=severity,
            attributable=attributable,
            seed=seed,
            scheduled_onset_s=scheduled,
            actual_onset_s=actual,
        )

    def scenario_label(self) -> str:
        return f"{self.source}_{self.mode}_{self.severity}"

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "profile": self.profile,
                "source": self.source,
                "mode": self.mode,
                "severity": self.severity,
                "attributable": self.attributable,
                "seed": self.seed,
                "scheduled_onset_s": self.scheduled_onset_s,
                "actual_onset_s": self.actual_onset_s,
            }
        )


@dataclass(frozen=True)
class RunArtifact(Record):
    """One immutable, accepted run, joined to the experiment that planned it."""

    FIELDS = (
        "schema_version",
        "run_uid",
        "run_id",
        "experiment_id",
        "experiment_digest",
        "campaign_id",
        "campaign_kind",
        "world",
        "transport_mode",
        "seed",
        "outcome",
        "split",
        "feature_schema",
        "data_files",
        "quality",
        "timing",
        "attack",
        "recorded_at_utc",
        "provenance",
    )
    REQUIRED = (
        "schema_version",
        "run_uid",
        "run_id",
        "experiment_id",
        "experiment_digest",
        "campaign_id",
        "campaign_kind",
        "world",
        "transport_mode",
        "seed",
        "outcome",
        "split",
        "feature_schema",
        "data_files",
        "quality",
        "timing",
        "recorded_at_utc",
        "provenance",
    )

    schema_version: str
    run_uid: str
    run_id: str
    experiment_id: str
    experiment_digest: str
    campaign_id: str
    campaign_kind: str
    world: WorldRef
    transport_mode: str
    seed: int
    outcome: str
    split: str
    feature_schema: FeatureSetRef
    data_files: Tuple[FileRef, ...]
    quality: QualityMetrics
    timing: RunTiming
    recorded_at_utc: str
    provenance: Provenance
    attack: Optional[AttackRunRecord] = None

    @classmethod
    def from_dict(cls, data: Any, *, path: str = "run_artifact") -> "RunArtifact":
        issues = IssueLog()
        artifact = cls._parse(data, issues, path)
        if issues or artifact is None:
            if not issues:
                issues.add(path, "document could not be parsed")
            raise LineageValidationError("RunArtifact", issues.sorted_issues())
        return artifact

    @classmethod
    def _parse(cls, data: Any, issues: IssueLog, path: str) -> Optional["RunArtifact"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)

        schema_version = get_str(
            issues, mapping, "schema_version", path, choices=(RUN_ARTIFACT_SCHEMA_VERSION,)
        )
        run_uid = get_str(issues, mapping, "run_uid", path)
        run_id = get_str(issues, mapping, "run_id", path, pattern=NAME_RE)
        experiment_id = get_str(issues, mapping, "experiment_id", path, pattern=IDENTIFIER_RE)
        experiment_digest = get_digest(issues, mapping, "experiment_digest", path)
        campaign_id = get_str(issues, mapping, "campaign_id", path, pattern=IDENTIFIER_RE)
        campaign_kind = get_str(issues, mapping, "campaign_kind", path, choices=CAMPAIGN_KINDS)
        transport_mode = get_str(issues, mapping, "transport_mode", path, choices=TRANSPORT_MODES)
        outcome = get_str(issues, mapping, "outcome", path, choices=RUN_OUTCOMES)
        split = get_str(issues, mapping, "split", path, choices=SPLITS)
        seed = get_int(issues, mapping, "seed", path, minimum=0, maximum=UINT32_MAX)
        recorded_at_utc = get_timestamp(issues, mapping, "recorded_at_utc", path)

        world = _parse_child(WorldRef, mapping, issues, path, "world")
        if world is not None and world.sha256 is None:
            issues.add(
                child(path, "world.sha256"),
                "a lineage record must pin the world file fingerprint",
            )
            world = None

        feature_schema = None
        if "feature_schema" in mapping and mapping["feature_schema"] is not None:
            feature_schema = FeatureSetRef.from_dict(
                mapping["feature_schema"], issues, child(path, "feature_schema"), require_columns=True
            )
        else:
            issues.add(child(path, "feature_schema"), "required field is missing")

        quality = _parse_child(QualityMetrics, mapping, issues, path, "quality")
        timing = _parse_child(RunTiming, mapping, issues, path, "timing")
        provenance = _parse_child(Provenance, mapping, issues, path, "provenance")
        attack = _parse_child(AttackRunRecord, mapping, issues, path, "attack", required=False)
        data_files = _parse_files(
            mapping, issues, path, "data_files", roles=DATA_FILE_ROLES, required_roles=("kpi_log",)
        )

        required = (
            schema_version,
            run_uid,
            run_id,
            experiment_id,
            experiment_digest,
            campaign_id,
            campaign_kind,
            world,
            transport_mode,
            seed,
            outcome,
            split,
            feature_schema,
            data_files,
            quality,
            timing,
            recorded_at_utc,
            provenance,
        )
        if any(value is None for value in required):
            return None

        artifact = cls(
            schema_version=schema_version,
            run_uid=run_uid,
            run_id=run_id,
            experiment_id=experiment_id,
            experiment_digest=experiment_digest,
            campaign_id=campaign_id,
            campaign_kind=campaign_kind,
            world=world,
            transport_mode=transport_mode,
            seed=seed,
            outcome=outcome,
            split=split,
            feature_schema=feature_schema,
            data_files=data_files,
            quality=quality,
            timing=timing,
            attack=attack,
            recorded_at_utc=recorded_at_utc,
            provenance=provenance,
        )
        artifact._check_consistency(issues, path)
        return artifact

    def _check_consistency(self, issues: IssueLog, path: str) -> None:
        expected_uid = f"{self.world.name}/{self.run_id}"
        if self.run_uid != expected_uid:
            issues.add(
                child(path, "run_uid"),
                f"expected '{expected_uid}' (world/run_id), got {self.run_uid!r}",
            )
        if self.campaign_kind == "attack" and self.attack is None:
            issues.add(child(path, "attack"), "an attack run must record what was injected")
        if self.campaign_kind == "normal" and self.attack is not None:
            issues.add(child(path, "attack"), "a normal run must not carry an attack record")
        if self.attack is not None and self.attack.seed is not None and self.attack.seed != self.seed:
            issues.add(
                child(path, "attack.seed"),
                f"attack seed {self.attack.seed} does not match run seed {self.seed}",
            )
        if self.campaign_kind == "normal" and self.split in TRAINING_SPLITS:
            if self.outcome != "SUCCESS_FINISH":
                issues.add(
                    child(path, "split"),
                    f"normal run outcome {self.outcome} cannot be assigned to {self.split!r}; "
                    "normal train/val/test runs must finish successfully",
                )
            if not self.quality.quality_ok:
                issues.add(
                    child(path, "split"),
                    f"normal run quality_ok is false, so it cannot be assigned to {self.split!r}",
                )
        if self.campaign_kind == "attack":
            if self.split in ("train", "val"):
                issues.add(
                    child(path, "split"),
                    "attack runs cannot enter normal model training or threshold-selection splits",
                )
            if self.split == "test" and (self.attack is None or not self.attack.attributable):
                issues.add(
                    child(path, "split"),
                    "an attack test run must have attack.attributable=true",
                )
        if self.attack is not None and self.attack.attributable:
            onset = self.attack.actual_onset_s or 0.0
            if self.timing.duration_s < onset:
                issues.add(
                    child(path, "attack.attributable"),
                    f"the run ended after {self.timing.duration_s} s, before the attack onset at "
                    f"{onset} s, so the outcome is not attributable to the attack",
                )
        if abs(self.quality.duration_s - self.timing.duration_s) > 1.0:
            issues.add(
                child(path, "quality.duration_s"),
                f"quality duration {self.quality.duration_s} s disagrees with the run manifest "
                f"duration {self.timing.duration_s} s",
            )

    def kpi_log(self) -> FileRef:
        for reference in self.data_files:
            if reference.role == "kpi_log":
                return reference
        raise LookupError("run artifact has no kpi_log data file")  # pragma: no cover - validated away

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "schema_version": self.schema_version,
                "run_uid": self.run_uid,
                "run_id": self.run_id,
                "experiment_id": self.experiment_id,
                "experiment_digest": self.experiment_digest,
                "campaign_id": self.campaign_id,
                "campaign_kind": self.campaign_kind,
                "world": self.world.to_dict(),
                "transport_mode": self.transport_mode,
                "seed": self.seed,
                "outcome": self.outcome,
                "split": self.split,
                "feature_schema": self.feature_schema.to_dict(),
                "data_files": [reference.to_dict() for reference in self.data_files],
                "quality": self.quality.to_dict(),
                "timing": self.timing.to_dict(),
                "attack": self.attack.to_dict() if self.attack is not None else None,
                "recorded_at_utc": self.recorded_at_utc,
                "provenance": self.provenance.to_dict(),
            }
        )


@dataclass(frozen=True)
class TrainingDataRef(Record):
    """Exactly which runs went into which split, by composite run uid."""

    FIELDS = ("train_run_uids", "val_run_uids", "test_run_uids", "registry_path", "registry_digest")
    REQUIRED = ("train_run_uids",)

    train_run_uids: Tuple[str, ...]
    val_run_uids: Tuple[str, ...] = ()
    test_run_uids: Tuple[str, ...] = ()
    registry_path: Optional[str] = None
    registry_digest: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["TrainingDataRef"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        train = get_str_list(issues, mapping, "train_run_uids", path, min_items=1)
        val = get_str_list(issues, mapping, "val_run_uids", path, required=False) or ()
        test = get_str_list(issues, mapping, "test_run_uids", path, required=False) or ()
        registry_path = get_str(issues, mapping, "registry_path", path, required=False)
        registry_digest = get_digest(issues, mapping, "registry_digest", path, required=False)
        if train is None:
            return None
        if (registry_path is None) != (registry_digest is None):
            issues.add(
                path,
                "registry_path and registry_digest must either both be present or both be absent",
            )
            return None
        overlap = (set(train) & set(val)) | (set(train) & set(test)) | (set(val) & set(test))
        if overlap:
            issues.add(
                path,
                f"the same run appears in more than one split: {', '.join(sorted(overlap))}",
            )
            return None
        return cls(
            train_run_uids=train,
            val_run_uids=tuple(val),
            test_run_uids=tuple(test),
            registry_path=registry_path,
            registry_digest=registry_digest,
        )

    def split_of(self, run_uid: str) -> Optional[str]:
        if run_uid in self.train_run_uids:
            return "train"
        if run_uid in self.val_run_uids:
            return "val"
        if run_uid in self.test_run_uids:
            return "test"
        return None

    def all_run_uids(self) -> Tuple[str, ...]:
        return tuple(self.train_run_uids) + tuple(self.val_run_uids) + tuple(self.test_run_uids)

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "train_run_uids": list(self.train_run_uids),
                "val_run_uids": list(self.val_run_uids),
                "test_run_uids": list(self.test_run_uids),
                "registry_path": self.registry_path,
                "registry_digest": self.registry_digest,
            }
        )


@dataclass(frozen=True)
class EvaluationDataRef(Record):
    """Allowlisted attack runs from one independent evaluation experiment.

    ``run_uid`` is only unique inside an experiment.  Keeping the attack
    experiment ID and digest beside every group prevents an identically named
    run from a normal campaign (or another attack campaign) being substituted.
    """

    FIELDS = ("experiment_id", "experiment_digest", "test_run_uids")
    REQUIRED = FIELDS

    experiment_id: str
    experiment_digest: str
    test_run_uids: Tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        data: Any,
        issues: IssueLog,
        path: str,
    ) -> Optional["EvaluationDataRef"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        experiment_id = get_str(
            issues,
            mapping,
            "experiment_id",
            path,
            pattern=IDENTIFIER_RE,
        )
        experiment_digest = get_digest(
            issues,
            mapping,
            "experiment_digest",
            path,
        )
        test_run_uids = get_str_list(
            issues,
            mapping,
            "test_run_uids",
            path,
            min_items=1,
        )
        if experiment_id is None or experiment_digest is None or test_run_uids is None:
            return None
        return cls(
            experiment_id=experiment_id,
            experiment_digest=experiment_digest,
            test_run_uids=test_run_uids,
        )

    def lineage_keys(self) -> Tuple[Tuple[str, str], ...]:
        return tuple((self.experiment_digest, uid) for uid in self.test_run_uids)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_digest": self.experiment_digest,
            "test_run_uids": list(self.test_run_uids),
        }


@dataclass(frozen=True)
class ThresholdRecord(Record):
    """The decision threshold and, more importantly, how it was chosen."""

    FIELDS = ("name", "value", "selection_policy", "selected_on", "target_false_positive_rate")
    REQUIRED = ("name", "value", "selection_policy", "selected_on")

    name: str
    value: float
    selection_policy: str
    selected_on: str
    target_false_positive_rate: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["ThresholdRecord"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        name = get_str(issues, mapping, "name", path, pattern=NAME_RE)
        value = get_float(issues, mapping, "value", path)
        selection_policy = get_str(issues, mapping, "selection_policy", path)
        selected_on = get_str(issues, mapping, "selected_on", path, choices=THRESHOLD_SELECTION_SPLITS)
        target_fpr = get_float(
            issues, mapping, "target_false_positive_rate", path, required=False, minimum=0.0, maximum=1.0
        )
        required = (name, value, selection_policy, selected_on)
        if any(item is None for item in required):
            return None
        return cls(
            name=name,
            value=value,
            selection_policy=selection_policy,
            selected_on=selected_on,
            target_false_positive_rate=target_fpr,
        )

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "name": self.name,
                "value": self.value,
                "selection_policy": self.selection_policy,
                "selected_on": self.selected_on,
                "target_false_positive_rate": self.target_false_positive_rate,
            }
        )


@dataclass(frozen=True)
class ModelArtifact(Record):
    """One trained detector plus everything needed to redeploy or audit it."""

    FIELDS = (
        "schema_version",
        "model_uid",
        "experiment_id",
        "experiment_digest",
        "algorithm",
        "framework",
        "feature_schema",
        "training_data",
        "evaluation_data",
        "threshold",
        "artifacts",
        "metrics",
        "trained_at_utc",
        "provenance",
    )
    REQUIRED = (
        "schema_version",
        "model_uid",
        "experiment_id",
        "experiment_digest",
        "algorithm",
        "feature_schema",
        "training_data",
        "threshold",
        "artifacts",
        "trained_at_utc",
        "provenance",
    )

    schema_version: str
    model_uid: str
    experiment_id: str
    experiment_digest: str
    algorithm: str
    feature_schema: FeatureSetRef
    training_data: TrainingDataRef
    threshold: ThresholdRecord
    artifacts: Tuple[FileRef, ...]
    trained_at_utc: str
    provenance: Provenance
    evaluation_data: Tuple[EvaluationDataRef, ...] = ()
    framework: Optional[str] = None
    metrics: Optional[Tuple[Tuple[str, float], ...]] = None

    @classmethod
    def from_dict(cls, data: Any, *, path: str = "model_artifact") -> "ModelArtifact":
        issues = IssueLog()
        artifact = cls._parse(data, issues, path)
        if issues or artifact is None:
            if not issues:
                issues.add(path, "document could not be parsed")
            raise LineageValidationError("ModelArtifact", issues.sorted_issues())
        return artifact

    @classmethod
    def _parse(cls, data: Any, issues: IssueLog, path: str) -> Optional["ModelArtifact"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)

        schema_version = get_str(
            issues, mapping, "schema_version", path, choices=(MODEL_ARTIFACT_SCHEMA_VERSION,)
        )
        model_uid = get_str(issues, mapping, "model_uid", path, pattern=IDENTIFIER_RE)
        experiment_id = get_str(issues, mapping, "experiment_id", path, pattern=IDENTIFIER_RE)
        experiment_digest = get_digest(issues, mapping, "experiment_digest", path)
        algorithm = get_str(issues, mapping, "algorithm", path, pattern=NAME_RE)
        framework = get_str(issues, mapping, "framework", path, required=False)
        trained_at_utc = get_timestamp(issues, mapping, "trained_at_utc", path)

        feature_schema = None
        if "feature_schema" in mapping and mapping["feature_schema"] is not None:
            feature_schema = FeatureSetRef.from_dict(
                mapping["feature_schema"], issues, child(path, "feature_schema"), require_columns=True
            )
        else:
            issues.add(child(path, "feature_schema"), "required field is missing")

        training_data = _parse_child(TrainingDataRef, mapping, issues, path, "training_data")
        evaluation_data = _parse_evaluation_data(mapping, issues, path)
        threshold = _parse_child(ThresholdRecord, mapping, issues, path, "threshold")
        provenance = _parse_child(Provenance, mapping, issues, path, "provenance")
        artifacts = _parse_files(
            mapping,
            issues,
            path,
            "artifacts",
            roles=MODEL_FILE_ROLES,
            required_roles=REQUIRED_MODEL_FILE_ROLES,
        )
        metrics = _parse_metrics(mapping, issues, path)

        required = (
            schema_version,
            model_uid,
            experiment_id,
            experiment_digest,
            algorithm,
            feature_schema,
            training_data,
            threshold,
            artifacts,
            trained_at_utc,
            provenance,
        )
        if any(value is None for value in required):
            return None

        artifact = cls(
            schema_version=schema_version,
            model_uid=model_uid,
            experiment_id=experiment_id,
            experiment_digest=experiment_digest,
            algorithm=algorithm,
            framework=framework,
            feature_schema=feature_schema,
            training_data=training_data,
            evaluation_data=evaluation_data or (),
            threshold=threshold,
            artifacts=artifacts,
            metrics=metrics,
            trained_at_utc=trained_at_utc,
            provenance=provenance,
        )
        artifact._check_consistency(issues, path)
        return artifact

    def _check_consistency(self, issues: IssueLog, path: str) -> None:
        selected_uids = getattr(
            self.training_data,
            f"{self.threshold.selected_on}_run_uids",
        )
        if not selected_uids:
            issues.add(
                child(path, "threshold.selected_on"),
                f"threshold selection declares {self.threshold.selected_on!r}, "
                "but that split contains no runs",
            )
        seen_ids: Dict[str, str] = {}
        seen_digests: Dict[str, str] = {}
        seen_keys = set()
        for position, evaluation in enumerate(self.evaluation_data):
            evaluation_path = index_path(child(path, "evaluation_data"), position)
            if (
                evaluation.experiment_id == self.experiment_id
                or evaluation.experiment_digest == self.experiment_digest
            ):
                issues.add(
                    evaluation_path,
                    "attack evaluation must reference an experiment separate from normal training",
                )
            previous_digest = seen_ids.get(evaluation.experiment_id)
            if previous_digest is not None and previous_digest != evaluation.experiment_digest:
                issues.add(
                    evaluation_path,
                    f"experiment id {evaluation.experiment_id!r} is paired with multiple digests",
                )
            previous_id = seen_digests.get(evaluation.experiment_digest)
            if previous_id is not None:
                issues.add(
                    evaluation_path,
                    f"experiment digest is already declared for {previous_id!r}",
                )
            seen_ids[evaluation.experiment_id] = evaluation.experiment_digest
            seen_digests[evaluation.experiment_digest] = evaluation.experiment_id
            for key in evaluation.lineage_keys():
                if key in seen_keys:
                    issues.add(
                        evaluation_path,
                        f"evaluation run {key[1]!r} is allowlisted more than once",
                    )
                seen_keys.add(key)

    def artifact_by_role(self, role: str) -> Optional[FileRef]:
        for reference in self.artifacts:
            if reference.role == role:
                return reference
        return None

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "schema_version": self.schema_version,
                "model_uid": self.model_uid,
                "experiment_id": self.experiment_id,
                "experiment_digest": self.experiment_digest,
                "algorithm": self.algorithm,
                "framework": self.framework,
                "feature_schema": self.feature_schema.to_dict(),
                "training_data": self.training_data.to_dict(),
                "evaluation_data": (
                    [reference.to_dict() for reference in self.evaluation_data]
                    if self.evaluation_data
                    else None
                ),
                "threshold": self.threshold.to_dict(),
                "artifacts": [reference.to_dict() for reference in self.artifacts],
                "metrics": dict(self.metrics) if self.metrics is not None else None,
                "trained_at_utc": self.trained_at_utc,
                "provenance": self.provenance.to_dict(),
            }
        )


def validate_lineage(model: ModelArtifact, runs: Iterable[RunArtifact]) -> None:
    """Cross-check a model against the runs it claims to be trained from.

    Training and evaluation are intentionally separate. Normal train/val/test
    runs are resolved inside the model's training experiment; attack test runs
    are resolved only through explicit :class:`EvaluationDataRef` allowlists.
    The lookup key is ``(experiment_digest, run_uid)`` because run numbering
    restarts in every campaign.
    """
    issues = IssueLog()
    by_key: Dict[Tuple[str, str], RunArtifact] = {}
    for run in runs:
        key = (run.experiment_digest, run.run_uid)
        if key in by_key:
            issues.add(
                "runs",
                f"duplicate lineage key ({run.experiment_digest[:12]}…, {run.run_uid!r}) "
                "in the supplied run artifacts",
            )
            continue
        by_key[key] = run

    model_columns_digest = model.feature_schema.columns_digest()
    referenced: List[Tuple[Tuple[str, str], str, RunArtifact]] = []

    def check_feature_schema(run: RunArtifact, path: str, uid: str) -> None:
        if run.feature_schema.name != model.feature_schema.name:
            issues.add(
                path,
                f"run {uid!r} carries feature set {run.feature_schema.name!r} but the model was "
                f"trained on {model.feature_schema.name!r}",
            )
        elif run.feature_schema.columns_digest() != model_columns_digest:
            issues.add(
                path,
                f"run {uid!r} pins a different column order for feature set "
                f"{run.feature_schema.name!r}",
            )

    for split in TRAINING_SPLITS:
        uids = getattr(model.training_data, f"{split}_run_uids")
        for uid in uids:
            path = f"training_data.{split}_run_uids"
            key = (model.experiment_digest, uid)
            run = by_key.get(key)
            if run is None:
                issues.add(
                    path,
                    f"normal run {uid!r} is referenced under experiment digest "
                    f"{model.experiment_digest[:12]}… but no exact matching artifact was supplied",
                )
                continue
            referenced.append((key, split, run))
            if run.experiment_id != model.experiment_id:
                issues.add(
                    path,
                    f"run {uid!r} belongs to experiment id {run.experiment_id!r} "
                    f"but the model declares {model.experiment_id!r}",
                )
            if run.campaign_kind != "normal":
                issues.add(
                    path,
                    f"run {uid!r} is {run.campaign_kind!r}; model training_data accepts only "
                    "normal campaign runs",
                )
            check_feature_schema(run, path, uid)
            if run.split != split:
                issues.add(
                    path,
                    f"run {uid!r} is recorded as split {run.split!r} but the model uses it for {split!r}",
                )

    for position, evaluation in enumerate(model.evaluation_data):
        path = f"evaluation_data[{position}].test_run_uids"
        for uid in evaluation.test_run_uids:
            key = (evaluation.experiment_digest, uid)
            run = by_key.get(key)
            if run is None:
                issues.add(
                    path,
                    f"attack run {uid!r} is allowlisted under experiment digest "
                    f"{evaluation.experiment_digest[:12]}… but no exact matching artifact was supplied",
                )
                continue
            referenced.append((key, "attack_test", run))
            if run.experiment_id != evaluation.experiment_id:
                issues.add(
                    path,
                    f"run {uid!r} belongs to experiment id {run.experiment_id!r} but the "
                    f"evaluation allowlist declares {evaluation.experiment_id!r}",
                )
            if run.campaign_kind != "attack":
                issues.add(
                    path,
                    f"run {uid!r} is {run.campaign_kind!r}; evaluation_data accepts only "
                    "attack campaign runs",
                )
            check_feature_schema(run, path, uid)
            if run.split != "test":
                issues.add(
                    path,
                    f"attack run {uid!r} is recorded as split {run.split!r}, not 'test'",
                )
            if run.attack is None or not run.attack.attributable:
                issues.add(
                    path,
                    f"attack run {uid!r} is not attributable and cannot be evaluated",
                )

    seen_kpi_digests: Dict[str, Tuple[Tuple[str, str], str]] = {}
    for key, split, run in referenced:
        kpi_digest = run.kpi_log().sha256
        previous = seen_kpi_digests.get(kpi_digest)
        if previous is not None and previous[0] != key:
            issues.add(
                "lineage",
                f"kpi_log digest {kpi_digest[:12]}… is reused by {previous[0][1]!r} "
                f"({previous[1]}) and {key[1]!r} ({split}); duplicated flight content "
                "cannot cross lineage entries or splits",
            )
        else:
            seen_kpi_digests[kpi_digest] = (key, split)

    if issues:
        raise LineageValidationError("ModelArtifact lineage", issues.sorted_issues())


def validate_full_lineage(
    model: ModelArtifact,
    training_spec: ExperimentSpec,
    evaluation_specs: Iterable[ExperimentSpec],
    runs: Iterable[RunArtifact],
) -> None:
    """Anchor model and run lineage to validated experiment specifications.

    Unlike :func:`validate_lineage`, this API proves that the IDs/digests in
    lineage records come from the actual supplied specs, then cross-checks
    campaign kind, transport, world fingerprint, seed, and ordered feature
    schema.  It remains side-effect free and does not read artifact files.
    """
    issues = IssueLog()
    run_records = tuple(runs)
    evaluation_spec_records = tuple(evaluation_specs)

    try:
        validate_lineage(model, run_records)
    except LineageValidationError as error:
        issues.extend(error.issues)

    training_digest = training_spec.spec_digest()
    if training_spec.campaign_kind != "normal":
        issues.add("training_spec.campaign_kind", "model training requires a normal experiment spec")
    if model.experiment_id != training_spec.experiment_id:
        issues.add(
            "model.experiment_id",
            f"model declares {model.experiment_id!r}, training spec declares "
            f"{training_spec.experiment_id!r}",
        )
    if model.experiment_digest != training_digest:
        issues.add(
            "model.experiment_digest",
            f"model declares {model.experiment_digest[:12]}…, actual training spec digest is "
            f"{training_digest[:12]}…",
        )

    specs_by_digest: Dict[str, ExperimentSpec] = {}
    for position, spec in enumerate(evaluation_spec_records):
        path = f"evaluation_specs[{position}]"
        digest = spec.spec_digest()
        if spec.campaign_kind != "attack":
            issues.add(child(path, "campaign_kind"), "evaluation specs must be attack campaigns")
        if digest in specs_by_digest:
            issues.add(path, f"duplicate evaluation spec digest {digest[:12]}…")
        else:
            specs_by_digest[digest] = spec

    declared_digests = {reference.experiment_digest for reference in model.evaluation_data}
    for position, reference in enumerate(model.evaluation_data):
        path = f"model.evaluation_data[{position}]"
        spec = specs_by_digest.get(reference.experiment_digest)
        if spec is None:
            issues.add(
                path,
                f"no evaluation spec with digest {reference.experiment_digest[:12]}… was supplied",
            )
        elif spec.experiment_id != reference.experiment_id:
            issues.add(
                child(path, "experiment_id"),
                f"allowlist declares {reference.experiment_id!r}, supplied spec declares "
                f"{spec.experiment_id!r}",
            )
    for digest, spec in specs_by_digest.items():
        if digest not in declared_digests:
            issues.add(
                "evaluation_specs",
                f"attack spec {spec.experiment_id!r} ({digest[:12]}…) is supplied but not "
                "declared in model.evaluation_data",
            )

    by_key: Dict[Tuple[str, str], RunArtifact] = {}
    for run in run_records:
        key = (run.experiment_digest, run.run_uid)
        if key not in by_key:
            by_key[key] = run

    def check_against_spec(
        run: RunArtifact,
        spec: ExperimentSpec,
        path: str,
        expected_kind: str,
    ) -> None:
        spec_digest = spec.spec_digest()
        if run.experiment_id != spec.experiment_id:
            issues.add(
                path,
                f"run experiment id {run.experiment_id!r} does not match spec "
                f"{spec.experiment_id!r}",
            )
        if run.experiment_digest != spec_digest:
            issues.add(
                path,
                f"run experiment digest {run.experiment_digest[:12]}… does not match actual "
                f"spec digest {spec_digest[:12]}…",
            )
        if run.campaign_kind != expected_kind or spec.campaign_kind != expected_kind:
            issues.add(
                path,
                f"expected {expected_kind!r} campaign, got run={run.campaign_kind!r}, "
                f"spec={spec.campaign_kind!r}",
            )
        if run.transport_mode != spec.transport_mode:
            issues.add(
                path,
                f"run transport {run.transport_mode!r} does not match spec "
                f"{spec.transport_mode!r}",
            )
        worlds = {world.name: world for world in spec.worlds}
        expected_world = worlds.get(run.world.name)
        if expected_world is None:
            issues.add(path, f"world {run.world.name!r} is not declared by the experiment spec")
        elif run.world.sha256 != expected_world.sha256:
            issues.add(
                path,
                f"world {run.world.name!r} SHA-256 does not match the experiment spec",
            )
        if run.seed not in spec.resolved_seeds():
            issues.add(
                path,
                f"seed {run.seed} is not declared by the experiment spec",
            )
        if run.feature_schema.name != spec.feature_set.name:
            issues.add(
                path,
                f"run feature set {run.feature_schema.name!r} does not match spec "
                f"{spec.feature_set.name!r}",
            )
        elif run.feature_schema.columns_digest() != spec.feature_set.columns_digest():
            issues.add(path, "run feature column order does not match the experiment spec")

    for split in TRAINING_SPLITS:
        for uid in getattr(model.training_data, f"{split}_run_uids"):
            key = (model.experiment_digest, uid)
            run = by_key.get(key)
            if run is not None:
                check_against_spec(
                    run,
                    training_spec,
                    f"training_data.{split}_run_uids[{uid!r}]",
                    "normal",
                )

    for position, reference in enumerate(model.evaluation_data):
        spec = specs_by_digest.get(reference.experiment_digest)
        if spec is None:
            continue
        for uid in reference.test_run_uids:
            key = (reference.experiment_digest, uid)
            run = by_key.get(key)
            if run is not None:
                check_against_spec(
                    run,
                    spec,
                    f"evaluation_data[{position}].test_run_uids[{uid!r}]",
                    "attack",
                )

    if issues:
        raise LineageValidationError("Full model lineage", issues.sorted_issues())


def verify_file_ref(reference: FileRef) -> None:
    """Verify one file's existence, size (when pinned), and SHA-256.

    This is deliberately separate from schema parsing and lineage validation:
    constructing a contract never performs hidden filesystem I/O.
    """
    issues = IssueLog()
    path = Path(reference.path)
    try:
        stat = path.stat()
    except OSError as error:
        issues.add("file.path", f"{reference.path}: cannot stat file: {error}")
    else:
        if not path.is_file():
            issues.add("file.path", f"{reference.path}: expected a regular file")
        if reference.size_bytes is not None and stat.st_size != reference.size_bytes:
            issues.add(
                "file.size_bytes",
                f"recorded {reference.size_bytes}, actual {stat.st_size}",
            )
        if path.is_file():
            try:
                actual_digest = sha256_file(path)
            except OSError as error:
                issues.add("file.sha256", f"{reference.path}: could not read file: {error}")
            else:
                if actual_digest != reference.sha256:
                    issues.add(
                        "file.sha256",
                        f"recorded {reference.sha256}, actual {actual_digest}",
                    )
    if issues:
        raise ArtifactVerificationError("FileRef verification", issues.sorted_issues())


def verify_file_refs(references: Iterable[FileRef]) -> None:
    """Verify multiple files and report all failures in one exception."""
    issues = IssueLog()
    for position, reference in enumerate(references):
        try:
            verify_file_ref(reference)
        except ArtifactVerificationError as error:
            for issue in error.issues:
                issues.add(f"files[{position}].{issue.path}", issue.message)
    if issues:
        raise ArtifactVerificationError("FileRef verification", issues.sorted_issues())


# ---- shared parsing helpers ----------------------------------------------
def _parse_child(
    record_cls: Any,
    mapping: Mapping[str, Any],
    issues: IssueLog,
    path: str,
    key: str,
    *,
    required: bool = True,
) -> Any:
    if key not in mapping or mapping[key] is None:
        if required:
            issues.add(child(path, key), "required field is missing")
        return None
    return record_cls.from_dict(mapping[key], issues, child(path, key))


def _parse_files(
    mapping: Mapping[str, Any],
    issues: IssueLog,
    path: str,
    key: str,
    *,
    roles: Sequence[str],
    required_roles: Sequence[str],
) -> Optional[Tuple[FileRef, ...]]:
    raw = get_list(issues, mapping, key, path, min_items=1)
    if raw is None:
        return None
    field = child(path, key)
    references: List[FileRef] = []
    for position, item in enumerate(raw):
        reference = FileRef.from_dict(item, issues, index_path(field, position), roles=roles)
        if reference is not None:
            references.append(reference)
    if len(references) != len(raw):
        return None
    paths = [reference.path for reference in references]
    if len(set(paths)) != len(paths):
        issues.add(field, "file paths must be unique")
        return None
    present = [reference.role for reference in references]
    for role in required_roles:
        count = present.count(role)
        if count != 1:
            issues.add(field, f"expected exactly one {role!r} entry, found {count}")
            return None
    return tuple(references)


def _parse_evaluation_data(
    mapping: Mapping[str, Any],
    issues: IssueLog,
    path: str,
) -> Optional[Tuple[EvaluationDataRef, ...]]:
    if "evaluation_data" not in mapping or mapping["evaluation_data"] is None:
        return ()
    raw = get_list(issues, mapping, "evaluation_data", path, min_items=1)
    if raw is None:
        return None
    field = child(path, "evaluation_data")
    references: List[EvaluationDataRef] = []
    for position, item in enumerate(raw):
        reference = EvaluationDataRef.from_dict(
            item,
            issues,
            index_path(field, position),
        )
        if reference is not None:
            references.append(reference)
    if len(references) != len(raw):
        return None
    return tuple(references)


def _parse_metrics(
    mapping: Mapping[str, Any], issues: IssueLog, path: str
) -> Optional[Tuple[Tuple[str, float], ...]]:
    if "metrics" not in mapping or mapping["metrics"] is None:
        return None
    field = child(path, "metrics")
    raw = as_mapping(issues, mapping["metrics"], field)
    if raw is None:
        return None
    values: List[Tuple[str, float]] = []
    for name in sorted(raw):
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.add(child(field, name), f"expected a number, got {type(value).__name__}")
            continue
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            issues.add(child(field, name), "must be a finite number")
            continue
        values.append((name, number))
    return tuple(values)
