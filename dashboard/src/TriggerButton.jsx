import { useEffect, useRef, useState } from "react";

function formatCountdown(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// The button that actually makes this page self-demonstrating: a visitor
// doesn't have to wait for (or get lucky and catch) the hourly scheduled
// run. Every response state the backend can return gets its own honest
// message rather than a generic "something went wrong."
export default function TriggerButton({ proxyUrl, isRunLive }) {
  const [state, setState] = useState("idle"); // idle | starting | started | rate_limited | budget_exhausted | not_configured | error
  const [detail, setDetail] = useState("");
  const [remainingS, setRemainingS] = useState(0);
  const timerRef = useRef(null);

  useEffect(() => {
    if (state !== "rate_limited" || remainingS <= 0) return undefined;
    const interval = setInterval(() => {
      setRemainingS((prev) => {
        if (prev <= 1) {
          setState("idle");
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [state, remainingS]);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const handleClick = async () => {
    setState("starting");
    try {
      const response = await fetch(`${proxyUrl}/control/demo/trigger`, { method: "POST" });
      const data = await response.json();
      setDetail(data.detail || "");
      if (data.status === "started") {
        setState("started");
        timerRef.current = setTimeout(() => setState("idle"), 10000);
      } else if (data.status === "rate_limited") {
        setState("rate_limited");
        setRemainingS(data.retry_after_s || 60);
      } else if (data.status === "already_running") {
        setState("started");
        timerRef.current = setTimeout(() => setState("idle"), 6000);
      } else {
        // budget_exhausted or not_configured: both are stable end states,
        // nothing to count down to.
        setState(data.status);
      }
    } catch {
      setDetail("Couldn't reach the proxy. It may be waking up, try again in a moment.");
      setState("error");
    }
  };

  if (state === "not_configured") {
    return <p className="trigger-note">{detail}</p>;
  }

  if (state === "budget_exhausted") {
    return <p className="trigger-note">{detail}</p>;
  }

  const disabled = state === "starting" || isRunLive || (state === "rate_limited" && remainingS > 0);

  let label = "Run a live experiment";
  if (state === "starting") label = "Starting…";
  else if (isRunLive) label = "A run is already live below";
  else if (state === "rate_limited") label = `Next run in ${formatCountdown(remainingS)}`;
  else if (state === "started") label = "Started, watch below";

  return (
    <div className="trigger">
      <button className="trigger-button" onClick={handleClick} disabled={disabled}>
        {label}
      </button>
      {state === "error" && <p className="trigger-note trigger-error">{detail}</p>}
    </div>
  );
}
