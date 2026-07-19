import { useEffect, useState } from "react";
import Sparkline from "./Sparkline.jsx";

// The one config knob this whole app has: which proxy's control API to
// watch. Set VITE_PROXY_URL at build time (Vercel env var for the hosted
// dashboard); defaults to a local proxy for `npm run dev`.
const PROXY_URL = import.meta.env.VITE_PROXY_URL || "http://localhost:8000";

const POLL_INTERVAL_MS = 3000;

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export default function App() {
  const [runId, setRunId] = useState(null);
  const [status, setStatus] = useState("waiting"); // waiting | connecting | live | complete
  const [phase, setPhase] = useState(null);
  const [totalCount, setTotalCount] = useState(0);
  const [successCount, setSuccessCount] = useState(0);
  const [latencyHistory, setLatencyHistory] = useState([]);
  const [faultFireCounts, setFaultFireCounts] = useState({});
  const [assertions, setAssertions] = useState([]);
  const [warnings, setWarnings] = useState([]);

  // Poll continuously (not just while waiting) for the latest run_id, and
  // switch only when it's actually different from the one we're showing.
  // A completed run's `latest` stays the same run_id until a new one
  // starts, so gating on "no runId yet" would immediately rediscover the
  // just-completed run, reset its state to blank, and reopen an SSE stream
  // that will never receive anything (that run already finished publishing)
  // — leaving the UI stuck showing "live" with no data forever.
  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const response = await fetch(`${PROXY_URL}/control/runs/latest`);
        const data = await response.json();
        if (!cancelled && data.run_id && data.run_id !== runId) {
          setPhase(null);
          setTotalCount(0);
          setSuccessCount(0);
          setLatencyHistory([]);
          setFaultFireCounts({});
          setAssertions([]);
          setWarnings([]);
          setRunId(data.run_id);
        }
      } catch {
        // Proxy unreachable; keep polling silently.
      }
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [runId]);

  // Subscribed to a run: stream progress over SSE.
  useEffect(() => {
    if (!runId) return undefined;
    setStatus("connecting");

    const source = new EventSource(`${PROXY_URL}/control/runs/${runId}/events`);

    source.onopen = () => setStatus("live");

    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.phase) setPhase(data.phase);
      if (typeof data.total_count === "number") setTotalCount(data.total_count);
      if (typeof data.success_count === "number") setSuccessCount(data.success_count);
      if (data.latency_p95_ms != null) {
        setLatencyHistory((prev) => [...prev.slice(-29), data.latency_p95_ms]);
      }
      if (data.fault_fire_counts && Object.keys(data.fault_fire_counts).length > 0) {
        setFaultFireCounts(data.fault_fire_counts);
      }
      if (data.assertions && data.assertions.length > 0) setAssertions(data.assertions);
      if (data.warnings && data.warnings.length > 0) setWarnings(data.warnings);

      if (data.type === "run_complete") {
        setStatus("complete");
        source.close();
      }
    };

    source.onerror = () => {
      setStatus((current) => (current === "complete" ? current : "connecting"));
    };

    return () => source.close();
  }, [runId]);

  const successRate = totalCount > 0 ? (successCount / totalCount) * 100 : null;

  return (
    <div className="dashboard">
      <header>
        <h1>chaosllm</h1>
        <span className={`status-pill status-${status}`}>{status}</span>
      </header>

      {!runId && <p className="empty-state">Waiting for a run…</p>}

      {runId && (
        <>
          <div className="run-id">{runId}</div>

          <div className="stat-grid">
            <Stat label="phase" value={phase ?? "—"} />
            <Stat label="requests" value={totalCount} />
            <Stat
              label="success rate"
              value={successRate != null ? `${successRate.toFixed(1)}%` : "—"}
            />
          </div>

          <Sparkline values={latencyHistory} label="p95 latency (ms)" />

          <section>
            <h2>Faults fired</h2>
            {Object.keys(faultFireCounts).length === 0 ? (
              <p className="muted">none yet</p>
            ) : (
              <ul className="fault-ticker">
                {Object.entries(faultFireCounts).map(([id, count]) => (
                  <li key={id}>
                    <code>{id}</code>
                    <span>{count}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2>Assertions</h2>
            {assertions.length === 0 ? (
              <p className="muted">pending</p>
            ) : (
              <ul className="assertions">
                {assertions.map((assertion) => (
                  <li key={assertion.type} className={assertion.passed ? "pass" : "fail"}>
                    <span className="mark">{assertion.passed ? "PASS" : "FAIL"}</span>
                    <code>{assertion.type}</code>
                    <span className="detail">{assertion.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {warnings.length > 0 && (
            <section className="warnings">
              <h2>Warnings</h2>
              <ul>
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
