// Hand-rolled SVG sparkline, no charting library: matches DESIGN.md 5's
// locked stack (React + Vite + plain CSS) and chaosllm/report/charts.py's
// own approach to the same problem on the Python side.
const WIDTH = 300;
const HEIGHT = 60;
const PADDING = 4;

export default function Sparkline({ values, label }) {
  if (values.length === 0) {
    return (
      <div className="sparkline">
        <div className="sparkline-label">{label}</div>
        <div className="sparkline-empty">collecting data…</div>
      </div>
    );
  }

  // A single point has no line to draw (and dividing by values.length - 1
  // below would divide by zero), but a reader landing on a finished run
  // over SSE replay (only the last event, not the whole history) only ever
  // gets one: show the known value instead of claiming to still be
  // "collecting data" about a run that's already over.
  if (values.length === 1) {
    return (
      <div className="sparkline">
        <div className="sparkline-label">
          {label} <span className="sparkline-latest">{values[0].toFixed(0)}</span>
        </div>
      </div>
    );
  }

  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const step = (WIDTH - 2 * PADDING) / (values.length - 1);

  const points = values
    .map((value, i) => {
      const x = PADDING + i * step;
      const y = PADDING + (HEIGHT - 2 * PADDING) * (1 - (value - min) / range);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="sparkline">
      <div className="sparkline-label">
        {label}{" "}
        <span className="sparkline-latest">{values[values.length - 1].toFixed(0)}</span>
      </div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="sparkline-svg">
        <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
    </div>
  );
}
