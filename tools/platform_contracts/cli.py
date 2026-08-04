"""Read-only command line interface for validating contract documents."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from .canonical import sha256_file
from .errors import ContractError, ContractValidationError
from .io import load_experiment_spec, load_model_artifact, load_run_artifact
from .lineage import validate_full_lineage

Loader = Callable[[str], Any]
LOADERS: Dict[str, Loader] = {
    "spec": load_experiment_spec,
    "run": load_run_artifact,
    "model": load_model_artifact,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.platform_contracts",
        description="Validate and fingerprint FedDroneLab platform contracts (read only).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one contract")
    validate.add_argument("kind", choices=tuple(LOADERS))
    validate.add_argument("document")
    validate.add_argument(
        "--run",
        dest="runs",
        action="append",
        default=[],
        metavar="RUN_ARTIFACT",
        help="for a model, cross-check one referenced run artifact (repeatable)",
    )
    validate.add_argument(
        "--spec",
        dest="training_spec",
        metavar="TRAINING_SPEC",
        help="normal ExperimentSpec used to train a model",
    )
    validate.add_argument(
        "--evaluation-spec",
        dest="evaluation_specs",
        action="append",
        default=[],
        metavar="ATTACK_SPEC",
        help="attack ExperimentSpec allowlisted by a model (repeatable)",
    )
    validate.add_argument("--json", action="store_true", help="emit machine-readable output")

    digest = subparsers.add_parser("digest", help="print a validated record digest")
    digest.add_argument("kind", choices=tuple(LOADERS))
    digest.add_argument("document")
    digest.add_argument(
        "--identity",
        action="store_true",
        help="for a spec, exclude provenance and print its reproducibility identity",
    )

    file_digest = subparsers.add_parser("file-digest", help="print SHA-256 of any file")
    file_digest.add_argument("file")
    return parser


def _error_payload(error: ContractError) -> Dict[str, Any]:
    if isinstance(error, ContractValidationError):
        return {"ok": False, "error": error.as_dict()}
    return {"ok": False, "error": {"message": str(error)}}


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    lineage_options = args.runs or args.training_spec or args.evaluation_specs
    if lineage_options and args.kind != "model":
        parser.error("--run/--spec/--evaluation-spec are only valid for a model")
    if args.runs and not args.training_spec:
        parser.error("model lineage validation with --run requires --spec")
    if (args.training_spec or args.evaluation_specs) and not args.runs:
        parser.error("--spec/--evaluation-spec require the referenced --run artifacts")
    record = LOADERS[args.kind](args.document)
    if args.kind == "model" and args.runs:
        validate_full_lineage(
            record,
            load_experiment_spec(args.training_spec),
            [load_experiment_spec(path) for path in args.evaluation_specs],
            [load_run_artifact(path) for path in args.runs],
        )
    payload = {
        "ok": True,
        "kind": args.kind,
        "document": str(Path(args.document)),
        "digest": record.digest(),
    }
    if args.kind == "spec":
        payload["identity_digest"] = record.spec_digest()
    if args.json:
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    else:
        suffix = (
            f", identity {payload['identity_digest']}"
            if "identity_digest" in payload
            else ""
        )
        sys.stdout.write(f"OK {args.kind}: {args.document} ({payload['digest']}{suffix})\n")
    return 0


def _digest(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.identity and args.kind != "spec":
        parser.error("--identity is only valid for a spec")
    record = LOADERS[args.kind](args.document)
    value = record.spec_digest() if args.identity else record.digest()
    sys.stdout.write(value + "\n")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args, parser)
        if args.command == "digest":
            return _digest(args, parser)
        if args.command == "file-digest":
            sys.stdout.write(sha256_file(args.file) + "\n")
            return 0
    except ContractError as error:
        if getattr(args, "json", False):
            sys.stderr.write(json.dumps(_error_payload(error), sort_keys=True) + "\n")
        else:
            sys.stderr.write(str(error) + "\n")
        return 2
    except OSError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    parser.error(f"unknown command {args.command!r}")
    return 2
