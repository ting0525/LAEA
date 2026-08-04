"""Small stdlib validation primitives shared by every contract record.

There is no pydantic / jsonschema dependency on purpose: this layer has to
import cleanly on the ROS Noetic workstation (Python 3.8) and on a bare GPU
training host with nothing but the standard library installed.

Every helper takes an :class:`IssueLog`, records what is wrong instead of
raising, and returns ``None`` when the value is unusable.  Callers therefore
collect a complete report in one pass.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from .canonical import canonical_json, is_hex_digest
from .errors import ContractError, ValidationIssue

# Campaign identifiers such as ``normal_four_maps_v1_20260728T031727Z`` contain
# upper case timestamp letters, so identifiers are not lowercase-only.
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
# Names that also have to survive as ROS parameters / directory names.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")

UINT32_MAX = 4294967295


class IssueLog:
    """Accumulates validation issues discovered while reading a document."""

    def __init__(self) -> None:
        self._issues: List[ValidationIssue] = []

    def add(self, path: str, message: str) -> None:
        self._issues.append(ValidationIssue(path, message))

    def extend(self, issues: Iterable[ValidationIssue]) -> None:
        self._issues.extend(issues)

    def __bool__(self) -> bool:
        return bool(self._issues)

    def __len__(self) -> int:
        return len(self._issues)

    def sorted_issues(self) -> Tuple[ValidationIssue, ...]:
        return tuple(sorted(self._issues, key=lambda issue: (issue.path, issue.message)))


def child(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def index_path(path: str, position: int) -> str:
    return f"{path}[{position}]"


def as_mapping(issues: IssueLog, value: Any, path: str) -> Optional[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        issues.add(path, f"expected a mapping, got {type(value).__name__}")
        return None
    bad_keys = sorted(str(key) for key in value if not isinstance(key, str))
    if bad_keys:
        issues.add(path, f"mapping keys must be strings: {', '.join(bad_keys)}")
        return None
    return value


def reject_unknown_keys(issues: IssueLog, data: Mapping[str, Any], allowed: Iterable[str], path: str) -> None:
    """Strict mode: an unexpected key is an error, never a silently ignored typo."""
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        issues.add(path, f"unknown field(s): {', '.join(unknown)}")


def _missing(issues: IssueLog, data: Mapping[str, Any], key: str, path: str, required: bool) -> bool:
    if key in data and data[key] is not None:
        return False
    if required:
        issues.add(child(path, key), "required field is missing")
    return True


def get_str(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    default: Optional[str] = None,
    pattern: Optional[re.Pattern] = None,
    choices: Optional[Sequence[str]] = None,
    allow_empty: bool = False,
) -> Optional[str]:
    if _missing(issues, data, key, path, required):
        return default
    field = child(path, key)
    value = data[key]
    if not isinstance(value, str):
        issues.add(field, f"expected a string, got {type(value).__name__}")
        return None
    if not allow_empty and not value.strip():
        issues.add(field, "must not be empty")
        return None
    if pattern is not None and not pattern.match(value):
        issues.add(field, f"{value!r} does not match {pattern.pattern}")
        return None
    if choices is not None and value not in choices:
        issues.add(field, f"{value!r} is not one of: {', '.join(sorted(choices))}")
        return None
    return value


def get_bool(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    default: Optional[bool] = None,
) -> Optional[bool]:
    if _missing(issues, data, key, path, required):
        return default
    value = data[key]
    if not isinstance(value, bool):
        issues.add(child(path, key), f"expected a boolean, got {type(value).__name__}")
        return None
    return value


def get_int(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    default: Optional[int] = None,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> Optional[int]:
    if _missing(issues, data, key, path, required):
        return default
    field = child(path, key)
    value = data[key]
    # bool is a subclass of int; a boolean is never an acceptable count.
    if isinstance(value, bool) or not isinstance(value, int):
        issues.add(field, f"expected an integer, got {type(value).__name__}")
        return None
    return _check_range(issues, field, value, minimum, maximum)


def get_float(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    default: Optional[float] = None,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Optional[float]:
    if _missing(issues, data, key, path, required):
        return default
    field = child(path, key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.add(field, f"expected a number, got {type(value).__name__}")
        return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        issues.add(field, "must be a finite number")
        return None
    return _check_range(issues, field, value, minimum, maximum)


def _check_range(issues: IssueLog, field: str, value: Any, minimum: Any, maximum: Any) -> Optional[Any]:
    if minimum is not None and value < minimum:
        issues.add(field, f"{value} is below the minimum {minimum}")
        return None
    if maximum is not None and value > maximum:
        issues.add(field, f"{value} is above the maximum {maximum}")
        return None
    return value


def get_list(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    min_items: int = 0,
    max_items: Optional[int] = None,
) -> Optional[List[Any]]:
    if _missing(issues, data, key, path, required):
        return None
    field = child(path, key)
    value = data[key]
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        issues.add(field, f"expected a list, got {type(value).__name__}")
        return None
    items = list(value)
    if len(items) < min_items:
        issues.add(field, f"needs at least {min_items} item(s), got {len(items)}")
        return None
    if max_items is not None and len(items) > max_items:
        issues.add(field, f"accepts at most {max_items} item(s), got {len(items)}")
        return None
    return items


def get_str_list(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    min_items: int = 0,
    unique: bool = True,
) -> Optional[Tuple[str, ...]]:
    items = get_list(issues, data, key, path, required=required, min_items=min_items)
    if items is None:
        return None
    field = child(path, key)
    values: List[str] = []
    for position, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            issues.add(index_path(field, position), "expected a non-empty string")
            continue
        values.append(item)
    if unique and len(set(values)) != len(values):
        issues.add(field, f"contains duplicate entries: {', '.join(sorted(_duplicates(values)))}")
        return None
    return tuple(values)


def get_int_list(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
    min_items: int = 0,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
    unique: bool = True,
) -> Optional[Tuple[int, ...]]:
    items = get_list(issues, data, key, path, required=required, min_items=min_items)
    if items is None:
        return None
    field = child(path, key)
    values: List[int] = []
    for position, item in enumerate(items):
        item_path = index_path(field, position)
        if isinstance(item, bool) or not isinstance(item, int):
            issues.add(item_path, f"expected an integer, got {type(item).__name__}")
            continue
        if _check_range(issues, item_path, item, minimum, maximum) is None:
            continue
        values.append(item)
    if unique and len(set(values)) != len(values):
        duplicates = sorted({str(value) for value in values if values.count(value) > 1})
        issues.add(field, f"contains duplicate entries: {', '.join(duplicates)}")
        return None
    return tuple(values)


def get_float_vector(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    length: int,
) -> Optional[Tuple[float, ...]]:
    items = get_list(issues, data, key, path, required=True)
    if items is None:
        return None
    field = child(path, key)
    if len(items) != length:
        issues.add(field, f"expected {length} numbers, got {len(items)}")
        return None
    values: List[float] = []
    for position, item in enumerate(items):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            issues.add(index_path(field, position), f"expected a number, got {type(item).__name__}")
            continue
        number = float(item)
        if number != number or number in (float("inf"), float("-inf")):
            issues.add(index_path(field, position), "must be a finite number")
            continue
        values.append(number)
    return tuple(values) if len(values) == length else None


def get_digest(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
) -> Optional[str]:
    """Read a bare lowercase SHA-256 hex digest (the repo-wide convention)."""
    if _missing(issues, data, key, path, required):
        return None
    field = child(path, key)
    value = data[key]
    if not is_hex_digest(value):
        issues.add(field, "expected a lowercase 64-character SHA-256 hex digest")
        return None
    return value


def get_timestamp(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
) -> Optional[str]:
    """Read an ISO-8601 timestamp that carries an explicit UTC offset."""
    value = get_str(issues, data, key, path, required=required, pattern=None)
    if value is None:
        return None
    if not ISO_UTC_RE.match(value):
        issues.add(
            child(path, key),
            "expected an ISO-8601 timestamp with an explicit offset, e.g. 2026-07-28T03:17:27+00:00",
        )
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        issues.add(child(path, key), f"{value!r} is not a valid calendar date/time")
        return None
    if parsed.utcoffset() is None:
        issues.add(child(path, key), "timestamp must carry an explicit UTC offset")
        return None
    return value


def get_absolute_path(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
) -> Optional[str]:
    value = get_str(issues, data, key, path, required=required)
    if value is None:
        return None
    if not value.startswith("/"):
        issues.add(child(path, key), "expected an absolute path")
        return None
    return value


def get_mapping(
    issues: IssueLog,
    data: Mapping[str, Any],
    key: str,
    path: str,
    *,
    required: bool = True,
) -> Optional[Mapping[str, Any]]:
    if _missing(issues, data, key, path, required):
        return None
    field = child(path, key)
    mapping = as_mapping(issues, data[key], field)
    if mapping is None:
        return None
    try:
        canonical_json(mapping)
    except ContractError as error:
        issues.add(field, f"must contain only canonical JSON values: {error}")
        return None
    return mapping


def _duplicates(values: Sequence[Any]) -> List[str]:
    seen = set()
    duplicated = set()
    for value in values:
        if value in seen:
            duplicated.add(str(value))
        seen.add(value)
    return sorted(duplicated)
