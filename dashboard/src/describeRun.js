// Turns the raw numbers from a finished run into one plain-English sentence,
// for the idle state: a first-time visitor between scheduled runs shouldn't
// have to interpret "success 100%, degraded 86%" themselves.
const FAULT_NAMES = {
  latency: "injected delays",
  rate_limit_burst: "injected rate limits",
  timeout: "connection timeouts",
  error: "injected errors",
  truncate: "truncated responses",
  malformed_json: "malformed responses",
  context_overflow: "context overflow errors",
  model_downgrade: "a downgraded model",
};

function faultsToPhrase(faultFireCounts) {
  const names = Object.keys(faultFireCounts || {}).map((id) => FAULT_NAMES[id] || id);
  if (names.length === 0) return null;
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function formatTime(isoString) {
  if (!isoString) return null;
  try {
    return new Date(isoString).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return null;
  }
}

export function describeRun({ successRate, degradedRate, faultFireCounts, completedAt }) {
  const time = formatTime(completedAt);
  const faultsPhrase = faultsToPhrase(faultFireCounts);
  const lead = time ? `Last run, ${time}:` : "Last run:";

  if (successRate == null) return null;

  const successClause = faultsPhrase
    ? `the demo held ${successRate.toFixed(0)}% success under ${faultsPhrase}`
    : `the demo held ${successRate.toFixed(0)}% success under chaos`;

  if (degradedRate == null || degradedRate <= 0) {
    return `${lead} ${successClause}, and every one of those was a real answer.`;
  }

  return `${lead} ${successClause}, but ${(degradedRate * 100).toFixed(0)}% of those were degraded fallbacks, not real answers.`;
}
