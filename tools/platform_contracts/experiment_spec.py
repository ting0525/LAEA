"""The ExperimentSpec contract: what a campaign *intends* to collect.

An ExperimentSpec is written before a campaign starts and never edited
afterwards.  It pins the maps, the seeds, the transport, the feature set, the
acceptance rule, and (for attack campaigns) the injection plan, so that the
resulting data can be traced back to a single immutable statement of intent.

Vocabularies are taken from what the repository already runs:

* transport modes ``nosip`` / ``aiottalk_rtp`` (``EXP_TRANSPORT_MODE``)
* outcomes emitted by ``laea_twin_tools/scripts/experiment_manager.py``
* attack sources ``gps`` / ``imu`` / ``barometer`` and their modes, matching
  ``laea_twin_tools/config/attack_profiles.yaml`` (source layer only)
* world names and world files from ``laea_twin_tools/config/world_profiles.yaml``
* the acceptance rule and per-map run split used by
  ``tools/dt_ids/build_normal_campaign_registry.py``

Validation is strict: unknown fields are rejected, and combinations that cannot
both be true (an attack campaign that deletes non-success logs, a split whose
parts do not add up, a transport that disagrees with the runtime switches) are
reported as errors rather than silently accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .base import Record, freeze, prune, thaw
from .canonical import digest_payload
from .errors import SpecValidationError
from .validation import (
    GIT_COMMIT_RE,
    IDENTIFIER_RE,
    IssueLog,
    NAME_RE,
    UINT32_MAX,
    as_mapping,
    child,
    get_absolute_path,
    get_bool,
    get_digest,
    get_float,
    get_float_vector,
    get_int,
    get_int_list,
    get_list,
    get_mapping,
    get_str,
    get_str_list,
    get_timestamp,
    index_path,
    reject_unknown_keys,
)

SCHEMA_VERSION = "platform-experiment-spec-v2"

CAMPAIGN_KINDS = ("normal", "attack")
TRANSPORT_MODES = ("nosip", "aiottalk_rtp")
RUN_OUTCOMES = (
    "SUCCESS_FINISH",
    "FAIL_SLAM",
    "TIMEOUT_NO_FINISH",
    "FAIL_PREMATURE_FINISH",
    "FAIL_LOGGER_NO_DATA",
    "ABORTED",
)
ATTACK_SOURCES = ("gps", "imu", "barometer")
ATTACK_MODES_BY_SOURCE = {
    "gps": ("bias", "velocity_bias"),
    "imu": ("gyro_bias",),
    "barometer": ("drift",),
}
VECTOR_MODES = ("bias", "velocity_bias", "gyro_bias")
SCALAR_MODES = ("drift",)
ATTACK_SEVERITIES = ("low", "medium", "high", "sweep")
NETWORK_SCOPES = ("rtp_media", "sip_signalling", "all")
SPLIT_UNITS = ("run",)
SPLIT_METHODS = ("deterministic_per_world_shuffle",)

MAX_REPETITIONS = 1000

# Simulator ground truth is valid for quality control and evaluation, but it is
# unavailable on a real vehicle and must never become a detector input.  The
# naming rules include the repository's current e_pos/px_gt/py_gt/pz_gt fields
# and make future explicitly named ground-truth fields fail closed.
EVALUATION_ONLY_COLUMNS = ("e_pos", "px_gt", "py_gt", "pz_gt")


def is_evaluation_only_column(name: str) -> bool:
    normalized = name.strip().lower()
    return (
        normalized in EVALUATION_ONLY_COLUMNS
        or normalized.startswith("gt_")
        or normalized.endswith("_gt")
        or "ground_truth" in normalized
        or "groundtruth" in normalized
    )


@dataclass(frozen=True)
class WorldRef(Record):
    """One map the campaign runs in.

    ``sha256`` is the fingerprint of the ``.world`` file at the time the spec
    was written; the registry rejects a campaign whose world file changed
    afterwards, and this field is what it compares against.
    """

    FIELDS = ("name", "world_file", "sha256", "label", "planner")
    REQUIRED = ("name", "world_file")

    name: str
    world_file: str
    sha256: Optional[str] = None
    label: Optional[str] = None
    planner: Optional[Mapping[str, Any]] = None

    @classmethod
    def from_dict(
        cls,
        data: Any,
        issues: IssueLog,
        path: str,
        *,
        require_sha256: bool = False,
    ) -> Optional["WorldRef"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        name = get_str(issues, mapping, "name", path, pattern=NAME_RE)
        world_file = get_absolute_path(issues, mapping, "world_file", path)
        sha256 = get_digest(issues, mapping, "sha256", path, required=False)
        label = get_str(issues, mapping, "label", path, required=False)
        planner = get_mapping(issues, mapping, "planner", path, required=False)
        if require_sha256 and sha256 is None:
            issues.add(
                child(path, "sha256"),
                "an experiment spec must pin the world file fingerprint",
            )
        if name is None or world_file is None or (require_sha256 and sha256 is None):
            return None
        return cls(
            name=name,
            world_file=world_file,
            sha256=sha256,
            label=label,
            planner=freeze(planner) if planner is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "name": self.name,
                "world_file": self.world_file,
                "sha256": self.sha256,
                "label": self.label,
                "planner": thaw(self.planner) if self.planner is not None else None,
            }
        )


@dataclass(frozen=True)
class SeedPolicy(Record):
    """Rule that derives one seed per repetition.

    Mirrors the batch runner, which starts at ``base_seed`` and increments once
    per round (``batch_progress.json`` records the resulting ``current_seed``).
    """

    FIELDS = ("base_seed", "increment", "stride")
    REQUIRED = ("base_seed",)

    base_seed: int
    increment: bool = True
    stride: int = 1

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["SeedPolicy"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        base_seed = get_int(issues, mapping, "base_seed", path, minimum=0, maximum=UINT32_MAX)
        increment = get_bool(issues, mapping, "increment", path, required=False, default=True)
        stride = get_int(issues, mapping, "stride", path, required=False, default=1, minimum=1, maximum=UINT32_MAX)
        if base_seed is None or increment is None or stride is None:
            return None
        return cls(base_seed=base_seed, increment=increment, stride=stride)

    def resolve(self, repetitions: int) -> Tuple[int, ...]:
        if not self.increment:
            return tuple(self.base_seed for _ in range(repetitions))
        return tuple(self.base_seed + index * self.stride for index in range(repetitions))

    def to_dict(self) -> Dict[str, Any]:
        return {"base_seed": self.base_seed, "increment": self.increment, "stride": self.stride}


@dataclass(frozen=True)
class FeatureSetRef(Record):
    """The model input contract.

    ``name`` refers to a key in ``tools/dt_ids/feature_sets.yaml``.  ``columns``
    is optional in a spec (the catalog is the source of truth at collection
    time) but required in lineage records, where the exact column order has to
    be pinned for training and inference to agree.
    """

    FIELDS = ("name", "columns", "catalog_path", "catalog_sha256")
    REQUIRED = ("name",)

    name: str
    columns: Optional[Tuple[str, ...]] = None
    catalog_path: Optional[str] = None
    catalog_sha256: Optional[str] = None

    @classmethod
    def from_dict(
        cls,
        data: Any,
        issues: IssueLog,
        path: str,
        *,
        require_columns: bool = False,
        require_catalog_digest: bool = False,
    ) -> Optional["FeatureSetRef"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        name = get_str(issues, mapping, "name", path, pattern=NAME_RE)
        columns = get_str_list(
            issues,
            mapping,
            "columns",
            path,
            required=require_columns,
            min_items=1 if require_columns else 0,
        )
        if columns is not None:
            forbidden = sorted(column for column in columns if is_evaluation_only_column(column))
            if forbidden:
                issues.add(
                    child(path, "columns"),
                    "evaluation-only ground-truth columns cannot be model inputs: "
                    + ", ".join(forbidden),
                )
                columns = None
        catalog_path = get_str(issues, mapping, "catalog_path", path, required=False)
        catalog_sha256 = get_digest(
            issues,
            mapping,
            "catalog_sha256",
            path,
            required=False,
        )
        if (catalog_path is None) != (catalog_sha256 is None):
            issues.add(
                path,
                "catalog_path and catalog_sha256 must either both be present or both be absent",
            )
        if require_catalog_digest and (catalog_path is None or catalog_sha256 is None):
            issues.add(
                path,
                "an experiment spec must pin both catalog_path and catalog_sha256",
            )
        if name is None:
            return None
        if require_columns and not columns:
            return None
        if require_catalog_digest and (catalog_path is None or catalog_sha256 is None):
            return None
        if (catalog_path is None) != (catalog_sha256 is None):
            return None
        return cls(
            name=name,
            columns=columns,
            catalog_path=catalog_path,
            catalog_sha256=catalog_sha256,
        )

    def columns_digest(self) -> Optional[str]:
        """Fingerprint of the ordered column list; ``None`` when not pinned.

        Column *order* is part of the contract: a model trained on one order
        cannot be fed another.
        """
        if self.columns is None:
            return None
        return digest_payload(list(self.columns))

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "name": self.name,
                "columns": list(self.columns) if self.columns is not None else None,
                "catalog_path": self.catalog_path,
                "catalog_sha256": self.catalog_sha256,
            }
        )


@dataclass(frozen=True)
class AttackProfileRef(Record):
    """One source-layer injection profile, shaped like an ``attack_profiles.yaml`` entry.

    The vector/scalar contract follows that file: position, velocity, and gyro
    biases carry a three-component vector, barometer drift carries a scalar
    altitude-equivalent offset.
    """

    FIELDS = ("name", "source", "mode", "severity", "ramp_s", "duration_s", "recovery_s", "vector", "scalar")
    REQUIRED = ("name", "source", "mode", "severity", "ramp_s", "duration_s", "recovery_s")

    name: str
    source: str
    mode: str
    severity: str
    ramp_s: float
    duration_s: float
    recovery_s: float
    vector: Optional[Tuple[float, ...]] = None
    scalar: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["AttackProfileRef"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        name = get_str(issues, mapping, "name", path, pattern=NAME_RE)
        source = get_str(issues, mapping, "source", path, choices=ATTACK_SOURCES)
        mode = get_str(issues, mapping, "mode", path, required=True)
        severity = get_str(issues, mapping, "severity", path, choices=ATTACK_SEVERITIES)
        ramp_s = get_float(issues, mapping, "ramp_s", path, minimum=0.0, maximum=600.0)
        duration_s = get_float(issues, mapping, "duration_s", path, minimum=0.1, maximum=3600.0)
        recovery_s = get_float(issues, mapping, "recovery_s", path, minimum=0.0, maximum=600.0)

        if source is not None and mode is not None:
            allowed = ATTACK_MODES_BY_SOURCE[source]
            if mode not in allowed:
                issues.add(
                    child(path, "mode"),
                    f"{mode!r} is not a source-layer mode for {source!r}; allowed: {', '.join(allowed)}",
                )
                mode = None

        vector = None
        scalar = None
        if mode in VECTOR_MODES:
            if "scalar" in mapping:
                issues.add(child(path, "scalar"), f"mode {mode!r} is vector-valued; remove 'scalar'")
            vector = get_float_vector(issues, mapping, "vector", path, length=3)
            if vector is not None and not any(component != 0.0 for component in vector):
                issues.add(child(path, "vector"), "attack magnitude must be non-zero")
                vector = None
        elif mode in SCALAR_MODES:
            if "vector" in mapping:
                issues.add(child(path, "vector"), f"mode {mode!r} is scalar-valued; remove 'vector'")
            scalar = get_float(issues, mapping, "scalar", path, minimum=-1000.0, maximum=1000.0)
            if scalar is not None and scalar == 0.0:
                issues.add(child(path, "scalar"), "attack magnitude must be non-zero")
                scalar = None

        required = (name, source, mode, severity, ramp_s, duration_s, recovery_s)
        if any(value is None for value in required):
            return None
        if mode in VECTOR_MODES and vector is None:
            return None
        if mode in SCALAR_MODES and scalar is None:
            return None
        return cls(
            name=name,
            source=source,
            mode=mode,
            severity=severity,
            ramp_s=ramp_s,
            duration_s=duration_s,
            recovery_s=recovery_s,
            vector=vector,
            scalar=scalar,
        )

    def span_s(self) -> float:
        """Total time from onset to the end of recovery."""
        return self.ramp_s + self.duration_s + self.recovery_s

    def scenario_label(self) -> str:
        """``<source>_<mode>_<severity>``, the grouping key ``build_attack_eval.py`` writes."""
        return f"{self.source}_{self.mode}_{self.severity}"

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "name": self.name,
                "source": self.source,
                "mode": self.mode,
                "severity": self.severity,
                "ramp_s": self.ramp_s,
                "duration_s": self.duration_s,
                "recovery_s": self.recovery_s,
                "vector": list(self.vector) if self.vector is not None else None,
                "scalar": self.scalar,
            }
        )


@dataclass(frozen=True)
class AttackPlan(Record):
    """Which injections an attack campaign runs, and when they may fire.

    ``onset_window_s`` is the window the attack scheduler samples from,
    relative to ``/traj_start_trigger``.
    """

    FIELDS = ("profiles", "runs_per_profile", "onset_window_s")
    REQUIRED = ("profiles", "runs_per_profile", "onset_window_s")

    profiles: Tuple[AttackProfileRef, ...]
    runs_per_profile: int
    onset_window_s: Tuple[float, float]

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["AttackPlan"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)

        raw_profiles = get_list(issues, mapping, "profiles", path, min_items=1)
        profiles = []
        if raw_profiles is not None:
            for position, item in enumerate(raw_profiles):
                profile = AttackProfileRef.from_dict(
                    item, issues, index_path(child(path, "profiles"), position)
                )
                if profile is not None:
                    profiles.append(profile)
            names = [profile.name for profile in profiles]
            if len(set(names)) != len(names):
                issues.add(child(path, "profiles"), "profile names must be unique")
                profiles = []

        runs_per_profile = get_int(
            issues, mapping, "runs_per_profile", path, minimum=1, maximum=MAX_REPETITIONS
        )
        onset = get_float_vector(issues, mapping, "onset_window_s", path, length=2)
        if onset is not None:
            if onset[0] <= 0.0:
                issues.add(child(path, "onset_window_s"), "onset window must start after 0 s")
                onset = None
            elif onset[0] > onset[1]:
                issues.add(child(path, "onset_window_s"), "onset window minimum exceeds its maximum")
                onset = None

        if not profiles or runs_per_profile is None or onset is None:
            return None
        return cls(
            profiles=tuple(profiles),
            runs_per_profile=runs_per_profile,
            onset_window_s=(onset[0], onset[1]),
        )

    def total_runs_per_world(self) -> int:
        return len(self.profiles) * self.runs_per_profile

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profiles": [profile.to_dict() for profile in self.profiles],
            "runs_per_profile": self.runs_per_profile,
            "onset_window_s": list(self.onset_window_s),
        }


@dataclass(frozen=True)
class NetworkProfile(Record):
    """Declared transport impairment for the campaign.

    This records *intent* only.  Nothing in this package applies shaping; a
    later runner is responsible for realising the profile and for recording
    what it actually applied.
    """

    FIELDS = ("name", "applies_to", "added_latency_ms", "jitter_ms", "packet_loss_pct", "bandwidth_kbps")
    REQUIRED = ("name", "applies_to", "added_latency_ms", "jitter_ms", "packet_loss_pct")

    name: str
    applies_to: str
    added_latency_ms: float
    jitter_ms: float
    packet_loss_pct: float
    bandwidth_kbps: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["NetworkProfile"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        name = get_str(issues, mapping, "name", path, pattern=NAME_RE)
        applies_to = get_str(issues, mapping, "applies_to", path, choices=NETWORK_SCOPES)
        latency = get_float(issues, mapping, "added_latency_ms", path, minimum=0.0, maximum=10000.0)
        jitter = get_float(issues, mapping, "jitter_ms", path, minimum=0.0, maximum=10000.0)
        loss = get_float(issues, mapping, "packet_loss_pct", path, minimum=0.0, maximum=100.0)
        bandwidth = get_float(
            issues, mapping, "bandwidth_kbps", path, required=False, minimum=1.0, maximum=1000000.0
        )
        required = (name, applies_to, latency, jitter, loss)
        if any(value is None for value in required):
            return None
        return cls(
            name=name,
            applies_to=applies_to,
            added_latency_ms=latency,
            jitter_ms=jitter,
            packet_loss_pct=loss,
            bandwidth_kbps=bandwidth,
        )

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "name": self.name,
                "applies_to": self.applies_to,
                "added_latency_ms": self.added_latency_ms,
                "jitter_ms": self.jitter_ms,
                "packet_loss_pct": self.packet_loss_pct,
                "bandwidth_kbps": self.bandwidth_kbps,
            }
        )


@dataclass(frozen=True)
class RuntimeProfile(Record):
    """Runner switches that decide what the campaign actually produces.

    Field names follow ``collection_card.json``'s ``runtime`` block so a card
    written by the existing shell runner can be compared field by field.
    """

    FIELDS = (
        "max_duration_s",
        "delete_on_non_success",
        "mission_aware",
        "ditto_bridge",
        "aiottalk_rtp",
        "nosip_rtp",
        "sleep_between_rounds_s",
    )
    REQUIRED = ("max_duration_s", "delete_on_non_success", "mission_aware", "nosip_rtp", "aiottalk_rtp")

    max_duration_s: float
    delete_on_non_success: bool
    mission_aware: bool
    aiottalk_rtp: bool
    nosip_rtp: bool
    ditto_bridge: bool = False
    sleep_between_rounds_s: float = 5.0

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["RuntimeProfile"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        max_duration_s = get_float(issues, mapping, "max_duration_s", path, minimum=30.0, maximum=7200.0)
        delete_on_non_success = get_bool(issues, mapping, "delete_on_non_success", path)
        mission_aware = get_bool(issues, mapping, "mission_aware", path)
        aiottalk_rtp = get_bool(issues, mapping, "aiottalk_rtp", path)
        nosip_rtp = get_bool(issues, mapping, "nosip_rtp", path)
        ditto_bridge = get_bool(issues, mapping, "ditto_bridge", path, required=False, default=False)
        sleep_between = get_float(
            issues, mapping, "sleep_between_rounds_s", path, required=False, default=5.0,
            minimum=0.0, maximum=600.0,
        )
        required = (
            max_duration_s,
            delete_on_non_success,
            mission_aware,
            aiottalk_rtp,
            nosip_rtp,
            ditto_bridge,
            sleep_between,
        )
        if any(value is None for value in required):
            return None
        return cls(
            max_duration_s=max_duration_s,
            delete_on_non_success=delete_on_non_success,
            mission_aware=mission_aware,
            aiottalk_rtp=aiottalk_rtp,
            nosip_rtp=nosip_rtp,
            ditto_bridge=ditto_bridge,
            sleep_between_rounds_s=sleep_between,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_duration_s": self.max_duration_s,
            "delete_on_non_success": self.delete_on_non_success,
            "mission_aware": self.mission_aware,
            "aiottalk_rtp": self.aiottalk_rtp,
            "nosip_rtp": self.nosip_rtp,
            "ditto_bridge": self.ditto_bridge,
            "sleep_between_rounds_s": self.sleep_between_rounds_s,
        }


@dataclass(frozen=True)
class AcceptancePolicy(Record):
    """Which finished runs may enter the dataset.

    The normal-campaign default (``SUCCESS_FINISH`` plus an independent
    ``quality_ok``) is exactly the rule enforced by
    ``build_normal_campaign_registry.py``.
    """

    FIELDS = (
        "required_outcomes",
        "require_log_retained",
        "require_quality_ok",
        "require_attack_attributable",
        "accepted_runs_per_world",
    )
    REQUIRED = ("required_outcomes", "accepted_runs_per_world")

    required_outcomes: Tuple[str, ...]
    accepted_runs_per_world: int
    require_log_retained: bool = True
    require_quality_ok: bool = True
    require_attack_attributable: bool = False

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["AcceptancePolicy"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        outcomes = get_str_list(issues, mapping, "required_outcomes", path, min_items=1)
        if outcomes is not None:
            unknown = [outcome for outcome in outcomes if outcome not in RUN_OUTCOMES]
            if unknown:
                issues.add(
                    child(path, "required_outcomes"),
                    f"unknown outcome(s): {', '.join(sorted(unknown))}; allowed: {', '.join(RUN_OUTCOMES)}",
                )
                outcomes = None
        accepted = get_int(
            issues, mapping, "accepted_runs_per_world", path, minimum=1, maximum=MAX_REPETITIONS
        )
        retained = get_bool(issues, mapping, "require_log_retained", path, required=False, default=True)
        quality_ok = get_bool(issues, mapping, "require_quality_ok", path, required=False, default=True)
        attributable = get_bool(
            issues, mapping, "require_attack_attributable", path, required=False, default=False
        )
        required = (outcomes, accepted, retained, quality_ok, attributable)
        if any(value is None for value in required):
            return None
        if not retained:
            issues.add(
                child(path, "require_log_retained"),
                "a run whose CSV was deleted can never be accepted; must be true",
            )
            return None
        return cls(
            required_outcomes=tuple(outcomes),
            accepted_runs_per_world=accepted,
            require_log_retained=retained,
            require_quality_ok=quality_ok,
            require_attack_attributable=attributable,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_outcomes": list(self.required_outcomes),
            "accepted_runs_per_world": self.accepted_runs_per_world,
            "require_log_retained": self.require_log_retained,
            "require_quality_ok": self.require_quality_ok,
            "require_attack_attributable": self.require_attack_attributable,
        }


@dataclass(frozen=True)
class DataSplitPolicy(Record):
    """Run-level train/validation/test split, declared up front.

    The unit is the run, never the row: rows from one flight are correlated, so
    splitting by row leaks the same trajectory into training and test.
    """

    FIELDS = ("unit", "method", "seed", "train_per_world", "val_per_world", "test_per_world")
    REQUIRED = ("unit", "seed", "train_per_world", "val_per_world", "test_per_world")

    unit: str
    seed: int
    train_per_world: int
    val_per_world: int
    test_per_world: int
    method: str = SPLIT_METHODS[0]

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["DataSplitPolicy"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        unit = get_str(issues, mapping, "unit", path, choices=SPLIT_UNITS)
        method = get_str(
            issues, mapping, "method", path, required=False, default=SPLIT_METHODS[0], choices=SPLIT_METHODS
        )
        seed = get_int(issues, mapping, "seed", path, minimum=0, maximum=UINT32_MAX)
        train = get_int(issues, mapping, "train_per_world", path, minimum=1, maximum=MAX_REPETITIONS)
        val = get_int(issues, mapping, "val_per_world", path, minimum=0, maximum=MAX_REPETITIONS)
        test = get_int(issues, mapping, "test_per_world", path, minimum=0, maximum=MAX_REPETITIONS)
        required = (unit, method, seed, train, val, test)
        if any(value is None for value in required):
            return None
        return cls(
            unit=unit,
            method=method,
            seed=seed,
            train_per_world=train,
            val_per_world=val,
            test_per_world=test,
        )

    def total_per_world(self) -> int:
        return self.train_per_world + self.val_per_world + self.test_per_world

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit": self.unit,
            "method": self.method,
            "seed": self.seed,
            "train_per_world": self.train_per_world,
            "val_per_world": self.val_per_world,
            "test_per_world": self.test_per_world,
        }


@dataclass(frozen=True)
class Provenance(Record):
    """Who wrote this document, when, and from which source tree."""

    FIELDS = ("created_at_utc", "created_by", "tool_version", "source_repo", "git_commit", "notes")
    REQUIRED = ("created_at_utc", "created_by", "tool_version")

    created_at_utc: str
    created_by: str
    tool_version: str
    source_repo: Optional[str] = None
    git_commit: Optional[str] = None
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Any, issues: IssueLog, path: str) -> Optional["Provenance"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)
        created_at_utc = get_timestamp(issues, mapping, "created_at_utc", path)
        created_by = get_str(issues, mapping, "created_by", path)
        tool_version = get_str(issues, mapping, "tool_version", path)
        source_repo = get_str(issues, mapping, "source_repo", path, required=False)
        git_commit = get_str(issues, mapping, "git_commit", path, required=False, pattern=GIT_COMMIT_RE)
        notes = get_str(issues, mapping, "notes", path, required=False)
        if created_at_utc is None or created_by is None or tool_version is None:
            return None
        return cls(
            created_at_utc=created_at_utc,
            created_by=created_by,
            tool_version=tool_version,
            source_repo=source_repo,
            git_commit=git_commit,
            notes=notes,
        )

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "created_at_utc": self.created_at_utc,
                "created_by": self.created_by,
                "tool_version": self.tool_version,
                "source_repo": self.source_repo,
                "git_commit": self.git_commit,
                "notes": self.notes,
            }
        )


@dataclass(frozen=True)
class ExperimentSpec(Record):
    """Immutable statement of what a campaign will collect.

    Two digests are published, and they answer different questions:

    * :meth:`spec_digest` covers everything **except** ``provenance``.  It is
      the reproducibility identity — the same experiment definition written by
      a different person on a different day yields the same digest, and every
      lineage record joins on it.
    * :meth:`digest` covers the whole document including provenance, for
      "is this the exact file I reviewed?" audits.
    """

    FIELDS = (
        "schema_version",
        "experiment_id",
        "campaign_kind",
        "description",
        "worlds",
        "repetitions",
        "seeds",
        "seed_policy",
        "transport_mode",
        "feature_set",
        "runtime",
        "acceptance",
        "data_split",
        "attack_plan",
        "network_profile",
        "labels",
        "provenance",
    )
    REQUIRED = (
        "schema_version",
        "experiment_id",
        "campaign_kind",
        "worlds",
        "repetitions",
        "transport_mode",
        "feature_set",
        "runtime",
        "acceptance",
        "provenance",
    )

    schema_version: str
    experiment_id: str
    campaign_kind: str
    worlds: Tuple[WorldRef, ...]
    repetitions: int
    transport_mode: str
    feature_set: FeatureSetRef
    runtime: RuntimeProfile
    acceptance: AcceptancePolicy
    provenance: Provenance
    seeds: Optional[Tuple[int, ...]] = None
    seed_policy: Optional[SeedPolicy] = None
    data_split: Optional[DataSplitPolicy] = None
    attack_plan: Optional[AttackPlan] = None
    network_profile: Optional[NetworkProfile] = None
    description: Optional[str] = None
    labels: Optional[Mapping[str, Any]] = None

    # ---- construction -----------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any, *, path: str = "spec") -> "ExperimentSpec":
        """Validate ``data`` and return a spec, or raise :class:`SpecValidationError`."""
        issues = IssueLog()
        spec = cls._parse(data, issues, path)
        if issues or spec is None:
            if not issues:
                issues.add(path, "document could not be parsed")
            raise SpecValidationError("ExperimentSpec", issues.sorted_issues())
        return spec

    @classmethod
    def _parse(cls, data: Any, issues: IssueLog, path: str) -> Optional["ExperimentSpec"]:
        mapping = as_mapping(issues, data, path)
        if mapping is None:
            return None
        reject_unknown_keys(issues, mapping, cls.FIELDS, path)

        schema_version = get_str(issues, mapping, "schema_version", path, choices=(SCHEMA_VERSION,))
        experiment_id = get_str(issues, mapping, "experiment_id", path, pattern=IDENTIFIER_RE)
        campaign_kind = get_str(issues, mapping, "campaign_kind", path, choices=CAMPAIGN_KINDS)
        description = get_str(issues, mapping, "description", path, required=False)
        transport_mode = get_str(issues, mapping, "transport_mode", path, choices=TRANSPORT_MODES)
        repetitions = get_int(issues, mapping, "repetitions", path, minimum=1, maximum=MAX_REPETITIONS)
        labels = get_mapping(issues, mapping, "labels", path, required=False)

        worlds = cls._parse_worlds(mapping, issues, path)
        seeds, seed_policy = cls._parse_seeding(mapping, issues, path, repetitions)

        feature_set = None
        if "feature_set" in mapping:
            feature_set = FeatureSetRef.from_dict(
                mapping["feature_set"],
                issues,
                child(path, "feature_set"),
                require_columns=True,
                require_catalog_digest=True,
            )
        else:
            issues.add(child(path, "feature_set"), "required field is missing")

        runtime = cls._parse_child(RuntimeProfile, mapping, issues, path, "runtime")
        acceptance = cls._parse_child(AcceptancePolicy, mapping, issues, path, "acceptance")
        provenance = cls._parse_child(Provenance, mapping, issues, path, "provenance")
        data_split = cls._parse_child(DataSplitPolicy, mapping, issues, path, "data_split", required=False)
        attack_plan = cls._parse_child(AttackPlan, mapping, issues, path, "attack_plan", required=False)
        network_profile = cls._parse_child(
            NetworkProfile, mapping, issues, path, "network_profile", required=False
        )

        required = (
            schema_version,
            experiment_id,
            campaign_kind,
            worlds,
            repetitions,
            transport_mode,
            feature_set,
            runtime,
            acceptance,
            provenance,
        )
        if any(value is None for value in required):
            return None

        spec = cls(
            schema_version=schema_version,
            experiment_id=experiment_id,
            campaign_kind=campaign_kind,
            description=description,
            worlds=worlds,
            repetitions=repetitions,
            seeds=seeds,
            seed_policy=seed_policy,
            transport_mode=transport_mode,
            feature_set=feature_set,
            runtime=runtime,
            acceptance=acceptance,
            data_split=data_split,
            attack_plan=attack_plan,
            network_profile=network_profile,
            labels=freeze(labels) if labels is not None else None,
            provenance=provenance,
        )
        spec._check_consistency(issues, path)
        return spec

    @staticmethod
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

    @classmethod
    def _parse_worlds(
        cls, mapping: Mapping[str, Any], issues: IssueLog, path: str
    ) -> Optional[Tuple[WorldRef, ...]]:
        raw_worlds = get_list(issues, mapping, "worlds", path, min_items=1)
        if raw_worlds is None:
            return None
        worlds = []
        for position, item in enumerate(raw_worlds):
            world = WorldRef.from_dict(
                item,
                issues,
                index_path(child(path, "worlds"), position),
                require_sha256=True,
            )
            if world is not None:
                worlds.append(world)
        if len(worlds) != len(raw_worlds):
            return None
        names = [world.name for world in worlds]
        if len(set(names)) != len(names):
            issues.add(child(path, "worlds"), "world names must be unique")
            return None
        files = [world.world_file for world in worlds]
        if len(set(files)) != len(files):
            issues.add(child(path, "worlds"), "world files must be unique")
            return None
        return tuple(worlds)

    @classmethod
    def _parse_seeding(
        cls,
        mapping: Mapping[str, Any],
        issues: IssueLog,
        path: str,
        repetitions: Optional[int],
    ) -> Tuple[Optional[Tuple[int, ...]], Optional[SeedPolicy]]:
        has_seeds = mapping.get("seeds") is not None
        has_policy = mapping.get("seed_policy") is not None
        if has_seeds and has_policy:
            issues.add(path, "'seeds' and 'seed_policy' are mutually exclusive; keep exactly one")
            return None, None
        if not has_seeds and not has_policy:
            issues.add(path, "one of 'seeds' or 'seed_policy' is required")
            return None, None

        if has_seeds:
            seeds = get_int_list(
                issues, mapping, "seeds", path, min_items=1, minimum=0, maximum=UINT32_MAX
            )
            if seeds is not None and repetitions is not None and len(seeds) != repetitions:
                issues.add(
                    child(path, "seeds"),
                    f"explicit seed list has {len(seeds)} entries but repetitions is {repetitions}",
                )
                return None, None
            return seeds, None

        policy = SeedPolicy.from_dict(mapping["seed_policy"], issues, child(path, "seed_policy"))
        if policy is not None and repetitions is not None:
            last = policy.resolve(repetitions)[-1]
            if last > UINT32_MAX:
                issues.add(
                    child(path, "seed_policy"),
                    f"the last derived seed {last} exceeds the uint32 range accepted by the runner",
                )
                return None, None
        return None, policy

    # ---- cross-field consistency -----------------------------------------
    def _check_consistency(self, issues: IssueLog, path: str) -> None:
        self._check_attack_consistency(issues, path)
        self._check_transport_consistency(issues, path)
        self._check_acceptance_consistency(issues, path)
        self._check_split_consistency(issues, path)

    def _check_attack_consistency(self, issues: IssueLog, path: str) -> None:
        if self.campaign_kind == "attack":
            if self.attack_plan is None:
                issues.add(child(path, "attack_plan"), "an attack campaign requires an attack plan")
                return
            if self.runtime.delete_on_non_success:
                issues.add(
                    child(path, "runtime.delete_on_non_success"),
                    "attack runs usually end in a non-success outcome; deleting those logs would "
                    "discard the evaluation data this campaign exists to collect",
                )
            if not self.runtime.mission_aware:
                issues.add(
                    child(path, "runtime.mission_aware"),
                    "the attack scheduler only runs in the mission-aware runtime",
                )
            expected = self.attack_plan.total_runs_per_world()
            if expected != self.repetitions:
                issues.add(
                    child(path, "repetitions"),
                    f"{self.repetitions} does not match the attack plan "
                    f"({len(self.attack_plan.profiles)} profiles x {self.attack_plan.runs_per_profile} "
                    f"runs = {expected})",
                )
            budget = self.runtime.max_duration_s
            latest_onset = self.attack_plan.onset_window_s[1]
            for position, profile in enumerate(self.attack_plan.profiles):
                needed = latest_onset + profile.span_s()
                if needed > budget:
                    issues.add(
                        index_path(child(path, "attack_plan.profiles"), position),
                        f"latest onset {latest_onset} s plus ramp/duration/recovery {profile.span_s()} s "
                        f"exceeds runtime.max_duration_s ({budget} s); the attack could be cut short",
                    )
        elif self.attack_plan is not None:
            issues.add(
                child(path, "attack_plan"),
                "a normal campaign must not carry an attack plan",
            )

    def _check_transport_consistency(self, issues: IssueLog, path: str) -> None:
        if self.transport_mode == "nosip":
            if not self.runtime.nosip_rtp or self.runtime.aiottalk_rtp:
                issues.add(
                    child(path, "runtime"),
                    "transport_mode 'nosip' requires runtime.nosip_rtp=true and runtime.aiottalk_rtp=false",
                )
            if self.network_profile is not None and self.network_profile.applies_to == "sip_signalling":
                issues.add(
                    child(path, "network_profile.applies_to"),
                    "there is no SIP signalling to impair in 'nosip' transport mode",
                )
        elif self.transport_mode == "aiottalk_rtp":
            if not self.runtime.aiottalk_rtp or self.runtime.nosip_rtp:
                issues.add(
                    child(path, "runtime"),
                    "transport_mode 'aiottalk_rtp' requires runtime.aiottalk_rtp=true and "
                    "runtime.nosip_rtp=false",
                )

    def _check_acceptance_consistency(self, issues: IssueLog, path: str) -> None:
        acceptance = self.acceptance
        if acceptance.accepted_runs_per_world > self.repetitions:
            issues.add(
                child(path, "acceptance.accepted_runs_per_world"),
                f"{acceptance.accepted_runs_per_world} accepted runs cannot come out of "
                f"{self.repetitions} attempted runs per world",
            )
        non_success = [outcome for outcome in acceptance.required_outcomes if outcome != "SUCCESS_FINISH"]
        if non_success and self.runtime.delete_on_non_success:
            issues.add(
                child(path, "acceptance.required_outcomes"),
                f"accepts {', '.join(sorted(non_success))} while runtime.delete_on_non_success is true, "
                "so those logs would never survive",
            )
        if acceptance.require_attack_attributable and self.campaign_kind != "attack":
            issues.add(
                child(path, "acceptance.require_attack_attributable"),
                "attack attribution can only be required for an attack campaign",
            )
        if self.campaign_kind == "attack" and acceptance.require_quality_ok:
            issues.add(
                child(path, "acceptance.require_quality_ok"),
                "the normal-flight quality gate rejects the degraded flight an attack is meant to "
                "produce; use require_attack_attributable for attack campaigns",
            )

    def _check_split_consistency(self, issues: IssueLog, path: str) -> None:
        if self.data_split is None:
            return
        total = self.data_split.total_per_world()
        if total != self.acceptance.accepted_runs_per_world:
            issues.add(
                child(path, "data_split"),
                f"train+val+test per world is {total} but acceptance.accepted_runs_per_world is "
                f"{self.acceptance.accepted_runs_per_world}",
            )

    # ---- derived values ---------------------------------------------------
    def resolved_seeds(self) -> Tuple[int, ...]:
        """One seed per repetition, whether the spec listed them or derived them."""
        if self.seeds is not None:
            return self.seeds
        assert self.seed_policy is not None  # guaranteed by validation
        return self.seed_policy.resolve(self.repetitions)

    def world_names(self) -> Tuple[str, ...]:
        return tuple(world.name for world in self.worlds)

    def planned_runs(self) -> int:
        return len(self.worlds) * self.repetitions

    def spec_digest(self) -> str:
        """SHA-256 over the canonical form of everything except ``provenance``."""
        return digest_payload(self.to_identity_dict())

    def to_identity_dict(self) -> Dict[str, Any]:
        payload = self.to_dict()
        payload.pop("provenance", None)
        return payload

    def to_dict(self) -> Dict[str, Any]:
        return prune(
            {
                "schema_version": self.schema_version,
                "experiment_id": self.experiment_id,
                "campaign_kind": self.campaign_kind,
                "description": self.description,
                "worlds": [world.to_dict() for world in self.worlds],
                "repetitions": self.repetitions,
                "seeds": list(self.seeds) if self.seeds is not None else None,
                "seed_policy": self.seed_policy.to_dict() if self.seed_policy is not None else None,
                "transport_mode": self.transport_mode,
                "feature_set": self.feature_set.to_dict(),
                "runtime": self.runtime.to_dict(),
                "acceptance": self.acceptance.to_dict(),
                "data_split": self.data_split.to_dict() if self.data_split is not None else None,
                "attack_plan": self.attack_plan.to_dict() if self.attack_plan is not None else None,
                "network_profile": (
                    self.network_profile.to_dict() if self.network_profile is not None else None
                ),
                "labels": thaw(self.labels) if self.labels is not None else None,
                "provenance": self.provenance.to_dict(),
            }
        )


def validate_spec_mapping(data: Any, *, path: str = "spec") -> ExperimentSpec:
    """Convenience wrapper mirroring :meth:`ExperimentSpec.from_dict`."""
    return ExperimentSpec.from_dict(data, path=path)


def spec_issues(data: Any, *, path: str = "spec") -> Sequence[Any]:
    """Return the validation issues for ``data`` without raising."""
    try:
        ExperimentSpec.from_dict(data, path=path)
    except SpecValidationError as error:
        return error.issues
    return ()
