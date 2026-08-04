"""Safe, side-effect-free document loading for platform contracts.

JSON is always available.  YAML support is deliberately optional so the same
package imports on the ROS Python 3.8 host without installing anything.  Both
formats reject duplicate mapping keys because silently keeping the last value
would make a reviewed experiment definition ambiguous.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from .canonical import canonical_json
from .errors import ContractError, SerializationError
from .experiment_spec import ExperimentSpec
from .lineage import ModelArtifact, RunArtifact

PathLike = Union[str, "Path"]


class _DuplicateKeyError(ValueError):
    pass


def _unique_json_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate mapping key {key!r}")
        result[key] = value
    return result


def _load_json(text: str) -> Any:
    def reject_nonstandard_constant(value: str) -> Any:
        raise ValueError(f"non-standard JSON constant {value!r} is not allowed")

    return json.loads(
        text,
        object_pairs_hook=_unique_json_object,
        parse_constant=reject_nonstandard_constant,
    )


def _load_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError as error:
        raise SerializationError(
            "YAML input requires optional dependency PyYAML; use JSON or install PyYAML"
        ) from error

    class UniqueKeySafeLoader(yaml.SafeLoader):
        pass

    def construct_unique_mapping(loader: Any, node: Any, deep: bool = False) -> Dict[Any, Any]:
        loader.flatten_mapping(node)
        result: Dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as error:
                raise SerializationError("YAML mapping keys must be scalar/hashable values") from error
            if duplicate:
                raise _DuplicateKeyError(f"duplicate mapping key {key!r}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_unique_mapping,
    )
    return yaml.load(text, Loader=UniqueKeySafeLoader)


def load_document(path: PathLike) -> Any:
    """Read one JSON/YAML document without mutating files or runtime state."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SerializationError(f"{source}: could not read UTF-8 document: {error}") from error

    suffix = source.suffix.lower()
    try:
        if suffix == ".json":
            document = _load_json(text)
        elif suffix in (".yaml", ".yml"):
            document = _load_yaml(text)
        else:
            raise SerializationError(
                f"{source}: unsupported document extension {suffix or '<none>'}; "
                "use .json, .yaml, or .yml"
            )
        canonical_json(document)
        return document
    except SerializationError:
        raise
    except ContractError as error:
        raise SerializationError(f"{source}: document is not canonical JSON data: {error}") from error
    except (ValueError, json.JSONDecodeError) as error:
        raise SerializationError(f"{source}: invalid {suffix.lstrip('.').upper()}: {error}") from error
    except Exception as error:
        # PyYAML exposes parser exception classes only when it is installed.
        # They are intentionally wrapped without importing PyYAML at module load.
        raise SerializationError(f"{source}: invalid YAML: {error}") from error

def load_experiment_spec(path: PathLike) -> ExperimentSpec:
    return ExperimentSpec.from_dict(load_document(path))


def load_run_artifact(path: PathLike) -> RunArtifact:
    return RunArtifact.from_dict(load_document(path))


def load_model_artifact(path: PathLike) -> ModelArtifact:
    return ModelArtifact.from_dict(load_document(path))
