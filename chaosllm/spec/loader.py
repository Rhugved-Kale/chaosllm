"""YAML loader for experiment specs, with validation errors that point at
the offending line in the source file rather than just a pydantic loc path.

Hand-written experiment YAML is exactly the place a typo (wrong fault param
name, a string where a number belongs) should fail loudly at the line it
happened on, not as a wall of `loc` tuples the author has to map back to the
file themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chaosllm.spec.models import ExperimentSpec


class SpecValidationError(Exception):
    """One or more validation errors, each annotated with a source line."""

    def __init__(self, path: Path, errors: list[tuple[int | None, str]]) -> None:
        self.path = path
        self.errors = errors
        lines = [
            f"{path}:{line if line is not None else '?'}: {message}" for line, message in errors
        ]
        super().__init__("\n".join(lines))


def load_experiment_spec(path: Path) -> ExperimentSpec:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    try:
        return ExperimentSpec.model_validate(data)
    except ValidationError as exc:
        node = yaml.compose(text)
        errors = [(_line_for_loc(node, error["loc"]), error["msg"]) for error in exc.errors()]
        raise SpecValidationError(path, errors) from exc


def _line_for_loc(node: yaml.Node | None, loc: tuple[Any, ...]) -> int | None:
    """Walk a composed YAML node tree along a pydantic error `loc` path.

    Stops and returns the nearest ancestor's line as soon as a step can't be
    resolved (for example, a discriminated union's tag is part of `loc` but
    isn't itself a YAML key), rather than failing outright.
    """
    if node is None:
        return None
    line = node.start_mark.line + 1
    for key in loc:
        step = _step(node, key)
        if step is None:
            return line
        node, line = step
    return line


def _step(node: yaml.Node, key: Any) -> tuple[yaml.Node, int] | None:
    if isinstance(node, yaml.MappingNode) and isinstance(key, str):
        for key_node, value_node in node.value:
            if key_node.value == key:
                return value_node, value_node.start_mark.line + 1
        return None
    if isinstance(node, yaml.SequenceNode) and isinstance(key, int):
        if 0 <= key < len(node.value):
            value_node = node.value[key]
            return value_node, value_node.start_mark.line + 1
        return None
    return None
