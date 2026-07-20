// A fast, static answer to "what is this, mechanically" - deliberately placed
// above the live panel so a first-time visitor has the mental model before
// they hit any numbers.
const SNIPPET = `from openai import OpenAI

client = OpenAI(
    base_url="https://your-proxy/openai/v1",  # <- the one line that changes
    api_key="sk-...",
)`;

export default function HowItWorks() {
  return (
    <section className="how-it-works">
      <ol className="how-steps">
        <li>
          <span className="how-step-num">1</span>
          <div>
            <div className="how-step-title">Point your app at the proxy</div>
            <div className="how-step-body">
              One line changes: your app&rsquo;s <code>base_url</code>. Nothing else about its
              code has to know chaos testing exists.
            </div>
          </div>
        </li>
        <li>
          <span className="how-step-num">2</span>
          <div>
            <div className="how-step-title">Define faults in YAML</div>
            <div className="how-step-body">
              Which route, which failure (latency, rate limits, timeouts, malformed output),
              how long.
            </div>
          </div>
        </li>
        <li>
          <span className="how-step-num">3</span>
          <div>
            <div className="how-step-title">Get a resilience report</div>
            <div className="how-step-body">
              Success rate, degraded rate, and latency, before vs. during vs. after the faults
              hit.
            </div>
          </div>
        </li>
      </ol>
      <pre className="how-snippet">
        <code>{SNIPPET}</code>
      </pre>
    </section>
  );
}
