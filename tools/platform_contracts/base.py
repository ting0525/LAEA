"""Shared behaviour for immutable contract records.

Records are frozen dataclasses.  Nested containers are frozen too (``tuple``
for sequences, ``MappingProxyType`` for free-form mappings), so a record handed
to a campaign runner or a training job cannot be edited in place after it was
validated.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Dict, List, Mapping

from .canonical import canonical_json, digest_payload


def freeze(value: Any) -> Any:
    """Return a deeply read-only view of ``value``."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return a plain mutable copy of a frozen structure (for serialisation)."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop ``None`` values so optional fields round-trip without null noise."""
    return {key: value for key, value in payload.items() if value is not None}


class Record:
    """Mixin giving every contract record the same serialisation surface."""

    def to_dict(self) -> Dict[str, Any]:  # pragma: no cover - overridden everywhere
        raise NotImplementedError

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def digest(self) -> str:
        """SHA-256 content fingerprint of the whole record, provenance included."""
        return digest_payload(self.to_dict())


def collect_dicts(records: Any) -> List[Dict[str, Any]]:
    return [record.to_dict() for record in records]
