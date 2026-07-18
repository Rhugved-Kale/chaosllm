"""The experiment specs shipped in experiments/ must always parse.

Not much of a test in isolation, but it's cheap insurance against the spec
models drifting out from under the starter content DESIGN.md 6 promises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaosllm.spec.loader import load_experiment_spec

REPO_ROOT = Path(__file__).parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"


@pytest.mark.parametrize("spec_path", sorted(EXPERIMENTS_DIR.glob("*.yaml")))
def test_shipped_spec_parses(spec_path: Path) -> None:
    spec = load_experiment_spec(spec_path)
    assert spec.name
    assert spec.load.concurrency > 0
