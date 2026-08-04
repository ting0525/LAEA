"""Canonical JSON encoding and SHA-256 fingerprints.

The canonical form is intentionally boring and fully specified so that two
hosts (the simulation workstation and the GPU training server) derive the same
digest from the same validated record:

* keys sorted with ``sort_keys=True``
* no insignificant whitespace (``separators=(",", ":")``)
* ``ensure_ascii=False`` and the result encoded as UTF-8
* ``NaN`` / ``Infinity`` rejected, because they have no JSON representation
* only JSON scalar types, lists, and string-keyed mappings are accepted

SHA-256 here is a *content fingerprint* used for integrity, deduplication, and
lineage joins.  It is not a signature, it provides no confidentiality, and it
does not authenticate the producer of a file.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Union

from .errors import ContractError

DIGEST_ALGORITHM = "sha256"
HEX_DIGEST_LENGTH = 64
_READ_CHUNK_BYTES = 1024 * 1024

PathLike = Union[str, "os.PathLike[str]"]


def _check_encodable(payload: Any, path: str = "$") -> None:
    """Reject values that would encode ambiguously or not at all."""
    if payload is None or isinstance(payload, (str, bool)):
        return
    if isinstance(payload, int):
        return
    if isinstance(payload, float):
        if payload != payload or payload in (float("inf"), float("-inf")):
            raise ContractError(f"{path}: non-finite float cannot be canonicalised")
        return
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if not isinstance(key, str):
                raise ContractError(f"{path}: mapping keys must be strings, got {type(key).__name__}")
            _check_encodable(value, f"{path}.{key}")
        return
    if isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _check_encodable(value, f"{path}[{index}]")
        return
    raise ContractError(f"{path}: {type(payload).__name__} is not JSON-encodable")


def canonical_json(payload: Any) -> str:
    """Return the canonical JSON text for ``payload``."""
    _check_encodable(payload)
    return json.dumps(
        _plain_json_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _plain_json_value(payload: Any) -> Any:
    """Copy generic Mapping/tuple containers into types json.dumps supports."""
    if isinstance(payload, Mapping):
        return {key: _plain_json_value(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_plain_json_value(value) for value in payload]
    return payload


def canonical_bytes(payload: Any) -> bytes:
    """Return the canonical JSON text for ``payload`` encoded as UTF-8."""
    return canonical_json(payload).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_payload(payload: Any) -> str:
    """Return the SHA-256 hex digest of the canonical encoding of ``payload``."""
    return sha256_hex(canonical_bytes(payload))


def sha256_file(path: PathLike) -> str:
    """Stream a file and return its SHA-256 hex digest.

    Matches the helper used by ``tools/dt_ids/build_normal_campaign_registry.py``
    so world files and KPI CSVs keep one fingerprint across both tools.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_hex_digest(value: Any) -> bool:
    """True when ``value`` looks like a lowercase SHA-256 hex digest."""
    if not isinstance(value, str) or len(value) != HEX_DIGEST_LENGTH:
        return False
    return all(character in "0123456789abcdef" for character in value)


def pretty_json(payload: Any) -> str:
    """Human-readable, still deterministic, JSON text with a trailing newline.

    Used for files a person reads or diffs; ``canonical_json`` remains the only
    input to a digest.
    """
    _check_encodable(payload)
    return (
        json.dumps(
            _plain_json_value(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def write_json_atomic(path: PathLike, payload: Any) -> Path:
    """Write ``payload`` as pretty JSON via a temporary file and ``os.replace``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(pretty_json(payload))
    os.replace(temporary, target)
    return target
