# Resilience patterns in the demo app

This is a short, honest account of what `demo/`'s `RESILIENT=true` path actually
does, and what it does not do. It exists because "the resilient demo passed" is
worth nothing if you can't say why. Everything here is implemented in
`demo/demo/llm_client.py` and `demo/demo/circuit_breaker.py`; there's no pattern
described below that isn't in those two files.

## The naive path (RESILIENT=false)

`naive_ask_llm` sends the request with `timeout=None` and returns whatever
happens: a slow proxy hangs the request for as long as the client is willing to
wait, a 500 propagates straight up as an exception, a truncated body raises on
`.json()`. This is deliberate. It's what an unguarded prod app looks like, and
it's the baseline the resilient path is measured against.

## Timeout

`resilient_ask_llm` sets an explicit 5-second `httpx` timeout
(`RESILIENT_TIMEOUT_S`) on the call to the proxy. Five seconds is arbitrary in the
sense that no load test picked it; it's short enough that a chaos-injected
multi-second latency spike (the demo's `llm-latency-spike.yaml` injects up to
2.5s) reliably trips it, and long enough that it doesn't fire on a normal
sub-second response. A production app should size this from its own p99, not
copy this number.

## Retry with jitter

Retryable failures (timeouts, connection errors, 429/500/502/503/504, and a
malformed or truncated body) get up to 3 attempts total
(`RESILIENT_MAX_ATTEMPTS`), via `tenacity`, with randomized exponential backoff
(`wait_random_exponential(multiplier=0.1, max=1.0)`). The jitter matters more than
the exact curve: fixed backoff across many concurrent requests means they all
retry in lockstep and hit the upstream at the same instant, which is exactly the
thundering-herd behavior that makes an already-struggling provider worse.

What is NOT retried: anything that isn't in `_is_retryable`. A 400 (bad request)
or 401 (bad key) fails immediately, because retrying a request that will never
succeed just burns the retry budget and adds latency for no chance of a
different outcome.

## Circuit breaker

`CircuitBreaker` (in `circuit_breaker.py`) sits in front of the retrying call.
Three consecutive failures (`failure_threshold=3`) open the circuit; while open,
`before_call()` raises immediately, no network call happens, for 5 seconds
(`reset_after_s`). After that it moves to half-open and lets exactly one trial
through. Success closes the circuit; failure re-opens it and restarts the
cooldown.

Why this on top of retries: retries help with a transient blip on one request.
A circuit breaker helps with a sustained outage across many requests, by
stopping the app from hammering a provider that is already down. Without it,
every one of N concurrent requests independently retries 3 times into a dead
upstream, which is 3x the load on something already failing, for zero
additional chance of success.

The one bug worth naming here, because it was real and it shipped and got
caught by manual testing rather than the original test suite: the first
version only re-armed the cooldown (`_opened_at`) the first time the threshold
was crossed. A half-open trial that failed again never re-opened the circuit,
so after the first cooldown elapsed, the breaker stayed permanently half-open,
meaning a real call was attempted on literally every request forever, which is
the exact behavior the breaker exists to prevent. Fixed by re-arming on every
qualifying failure, not just the first. There's a regression test for this
(`test_half_open_trial_failure_reopens_the_circuit`) precisely because it's
the kind of bug that only shows up once the circuit has been open and closed
more than once.

## Degraded fallback

If `resilient_ask_llm` still raises `LLMUnavailableError` after retries and the
circuit breaker, `/ask` in `demo/demo/main.py` does not fail the request. It
returns the first retrieved document's text verbatim as an "answer," with
`degraded: true` in the response body, instead of the actual LLM-generated
answer.

This is the pattern worth being honest about. A dashboard or report that only
tracks success rate will show this as a 100% success run, because every
request got a 200 back. It is not actually 100% successful: some fraction of
those responses are a raw retrieval chunk standing in for a real answer, at a
fraction of the latency and none of the synthesis. That's why the report has a
separate `degraded_rate` metric and assertion type (`type: degraded_rate, max:
...`): it exists specifically so "resilient" doesn't get to mean "always
returns 200" without anyone checking what was actually inside the 200.

## What this demo does not implement

- No token-bucket or leaky-bucket client-side rate limiting. The demo reacts to
  429s after the fact (retry/backoff), it doesn't self-limit its own request
  rate to stay under a provider's published limit.
- No request hedging (firing a duplicate request to a second attempt in
  parallel and taking whichever returns first). Retries here are strictly
  sequential.
- No caching of LLM responses. A cached-embedding fallback for retrieval is
  mentioned as a stretch idea in DESIGN.md; it isn't built. The only fallback
  implemented is the extractive degraded answer above.
- No adaptive circuit breaker tuning. `failure_threshold` and `reset_after_s`
  are fixed constants, not derived from observed latency or error rate.
