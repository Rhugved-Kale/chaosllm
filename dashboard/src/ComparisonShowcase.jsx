// Static illustration of the tool's actual point, not live data: a naive
// LLM client (no timeout, no retries, no fallback) versus the same app with
// resilience patterns applied, under the identical chaos experiment. See
// docs/resilience-patterns.md for what "resilient" concretely means here.
export default function ComparisonShowcase() {
  return (
    <section className="showcase">
      <div className="showcase-header">
        <h2>Same chaos, different outcome</h2>
        <p>
          One experiment, run twice against the same app: once with no resilience patterns,
          once with a timeout, retries, and a fallback path.
        </p>
      </div>

      <div className="showcase-grid">
        <div className="showcase-card fragile">
          <div className="showcase-card-label">Fragile app</div>
          <div className="showcase-card-value">7%</div>
          <div className="showcase-card-sub">success rate under chaos</div>
        </div>

        <div className="showcase-card resilient">
          <div className="showcase-card-label">Resilient app</div>
          <div className="showcase-card-value">100%</div>
          <div className="showcase-card-sub">success rate under chaos</div>
          <div className="showcase-callout">99.9% of those were degraded</div>
        </div>
      </div>

      <p className="showcase-explainer">
        The fragile app has no timeout, no retries, no fallback: it fails outright the moment
        the LLM call slows down or gets rate-limited. The resilient app never technically fails,
        but almost every one of its &ldquo;successes&rdquo; is a degraded fallback answer, not a
        real response. Success rate alone can&rsquo;t tell the two apart. Degraded rate can,
        which is why it&rsquo;s tracked as its own metric.
      </p>
    </section>
  );
}
