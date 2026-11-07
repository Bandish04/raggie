# Load tests — A5 (design target: 50k concurrent streams)

`a5_chat_load.js` drives the edge SSE chat hot path with [k6](https://k6.io) and
asserts the A5 SLOs. These are **design targets, not measured results**: no A5
run has been published yet (see [docs/benchmarks](../../docs/benchmarks/README.md)).

| SLO | Threshold |
|-----|-----------|
| TTFB (time to first SSE byte) | p95 ≤ 1.5 s |
| inter-token latency | p95 ≤ 120 ms |
| error rate | < 0.5% |
| shedding at the bounded-pool ceiling | `503` + `Retry-After` (no 5xx storm) |

## Full A5 run (against a cluster sized for 50k — not a laptop)

```bash
EDGE=https://chat.raggie.example \
WS=<external_workspace_id> \
TOKEN=<widget_or_admin_jwt> \
  k6 run --vus 50000 --duration 5m deploy/load/a5_chat_load.js
```

The HPA/KEDA edge ScaledObject (prod overlay) scales on live SSE-connection
count (~800/pod), so the fleet grows past 50k while the bounded `chatPool` sheds
with `503 Retry-After` rather than collapsing — the script counts sheds
separately from errors.

## Smoke run (CI / dev — reuse the same script at small scale)

```bash
VUS=200 DURATION=1m \
  k6 run -e VUS=200 -e DURATION=1m -e EDGE=http://localhost:8080 \
         -e WS=<ws> -e TOKEN=<jwt> deploy/load/a5_chat_load.js
```

`make load-a5` runs the smoke profile against the local compose edge.
