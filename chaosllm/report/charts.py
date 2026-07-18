"""SVG "degradation profile": p95 latency across phases, chaos window shaded.

DESIGN.md 4.5: "a 'degradation profile' line chart (latency over time with
fault window shaded, rendered as SVG for embeddability in READMEs)."
"""

from __future__ import annotations

from chaosllm.metrics.store import PhaseSummary

_WIDTH = 600
_HEIGHT = 220
_MARGIN = 40


def render_latency_svg(phase_summaries: list[PhaseSummary]) -> str | None:
    points = [(s.phase, s.latency_p95_ms) for s in phase_summaries if s.latency_p95_ms is not None]
    if len(points) < 2:
        return None

    max_latency = max(value for _, value in points) or 1.0
    plot_width = _WIDTH - 2 * _MARGIN
    plot_height = _HEIGHT - 2 * _MARGIN
    step = plot_width / (len(points) - 1)

    def coords(i: int, value: float) -> tuple[float, float]:
        x = _MARGIN + i * step
        y = _MARGIN + plot_height * (1 - value / max_latency)
        return x, y

    coords_list = [coords(i, value) for i, (_, value) in enumerate(points)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords_list)

    shade = ""
    chaos_index = next((i for i, (phase, _) in enumerate(points) if phase == "chaos"), None)
    if chaos_index is not None:
        x0 = _MARGIN + (chaos_index - 0.5) * step
        x1 = _MARGIN + (chaos_index + 0.5) * step
        shade = (
            f'<rect x="{x0:.1f}" y="{_MARGIN}" width="{x1 - x0:.1f}" '
            f'height="{plot_height}" fill="#ef444422" />'
        )

    labels = "".join(
        f'<text x="{x:.1f}" y="{_HEIGHT - 10}" font-size="11" text-anchor="middle" '
        f'fill="#666">{phase}</text>'
        for (phase, _), (x, _y) in zip(points, coords_list, strict=True)
    )
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#2563eb" />' for x, y in coords_list
    )

    return (
        f'<svg viewBox="0 0 {_WIDTH} {_HEIGHT}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="p95 latency by phase">'
        f"{shade}"
        f'<polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="2" />'
        f"{dots}{labels}"
        f"</svg>"
    )
