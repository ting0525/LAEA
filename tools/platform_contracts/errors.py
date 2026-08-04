"""Error types for the platform contracts layer.

Validation deliberately collects *every* problem before raising.  A campaign
operator fixing a specification wants the full list in one pass, the same way
``build_normal_campaign_registry.py`` reports all ``blocking_reasons`` instead
of stopping at the first one.
"""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Sequence


class ContractError(Exception):
    """Base class for every error raised by this package."""


class SerializationError(ContractError):
    """A document could not be read, parsed, or written."""


class ValidationIssue(NamedTuple):
    """One problem found at one location inside a document."""

    path: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {"path": self.path, "message": self.message}

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        return f"{self.path}: {self.message}"


class ContractValidationError(ContractError):
    """Raised when a document violates its contract.

    ``issues`` holds every problem found, sorted by document path, so the CLI
    can print a complete report and callers can serialise it as JSON.
    """

    def __init__(self, subject: str, issues: Sequence[ValidationIssue]) -> None:
        self.subject = subject
        self.issues = tuple(issues)
        super().__init__(self._render())

    def _render(self) -> str:
        header = f"{self.subject}: {len(self.issues)} validation issue(s)"
        body = "\n".join(f"  - {issue}" for issue in self.issues)
        return f"{header}\n{body}" if body else header

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "issue_count": len(self.issues),
            "issues": [issue.as_dict() for issue in self.issues],
        }

    def paths(self) -> List[str]:
        return [issue.path for issue in self.issues]


class SpecValidationError(ContractValidationError):
    """An ExperimentSpec document is invalid or internally contradictory."""


class LineageValidationError(ContractValidationError):
    """A RunArtifact / ModelArtifact record is invalid or inconsistent."""


class ArtifactVerificationError(ContractValidationError):
    """A referenced file is missing or disagrees with its recorded metadata."""
