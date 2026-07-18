"""The three run phases and their durations.

DESIGN.md 4.4: "warmup (baseline, faults off) -> chaos (faults on) -> recovery
(faults off, same duration as warmup). Every metric is reported per phase;
the baseline-vs-chaos delta IS the resilience finding."
"""

from __future__ import annotations

from enum import StrEnum


class Phase(StrEnum):
    WARMUP = "warmup"
    CHAOS = "chaos"
    RECOVERY = "recovery"


def phase_duration_s(phase: Phase, *, duration_s: float, warmup_s: float) -> float:
    if phase is Phase.CHAOS:
        return duration_s
    return warmup_s
