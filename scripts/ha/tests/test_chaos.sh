#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Unit tests for the pure parts of scripts/ha/chaos.sh: verdicts, k6 summary
# parsing, the results block and the job summary (no cluster, no Docker).
#   bash scripts/ha/tests/test_chaos.sh
# shellcheck source-path=SCRIPTDIR/..
set -uo pipefail

HA="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
# shellcheck disable=SC2034 # read by chaos.sh
CHAOS_LIB_ONLY=1 ARTIFACTS_DIR="$T/artifacts" RESULTS_FILE="$T/results.md" CHAOS_CONTEXT="test ctx"
# shellcheck source=../chaos.sh
. "$HA/chaos.sh"

failures=0
tests=0
eq() { # eq <name> <expected> <actual>
  tests=$((tests + 1))
  if [[ "$2" != "$3" ]]; then
    failures=$((failures + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3"
  fi
}
has() { [[ "$2" == *"$1"* ]] && echo yes || echo no; }
truth() { if "$@"; then echo yes; else echo no; fi; }

# ── k6 end-of-test summary parsing ──────────────────────────────────────────
cat >"$ARTIFACTS_DIR/edge.log" <<'EOF'
ACK_MSG 11111111-1111-4111-8111-111111111111
     chat_done......................: 12     0.13/s
     sse_reconnect..................: 3      0.03/s
     sse_resumed....................: 3      0.03/s
     http_5xx.......................: 0      0/s
EOF
eq metric-present 3 "$(k6_metric edge sse_reconnect)"
eq metric-absent 0 "$(k6_metric edge resume_failed)"
eq metric-prefix-not-confused 12 "$(k6_metric edge chat_done)"

# ── scenario 4 (graceful edge delete): a stream must actually be interrupted
#    and every interrupted stream resumed with resume_message_id ─────────────
# edge_graceful_ok RECONNECTS RESUMED RESUME_FAILED K6_OK(0|1)
eq edge-resumed-all yes "$(truth edge_graceful_ok 3 3 0 0)"
eq edge-no-interruption no "$(truth edge_graceful_ok 0 0 0 0)"
eq edge-resume-missing no "$(truth edge_graceful_ok 3 2 0 0)"
eq edge-resume-failed no "$(truth edge_graceful_ok 3 3 1 0)"
eq edge-k6-failed no "$(truth edge_graceful_ok 3 3 0 1)"

# ── results: duration column, FAIL rows kept, scenarios not run marked ──────
printf '# HA chaos results\n\n<!-- results:begin -->\nold\n<!-- results:end -->\n\ntail\n' >"$RESULTS_FILE"
overall=0
PLANNED=(pg redis edge)
SCENARIO_T0=$(($(now) - 42))
record pg PASS "failover 9s"
eq record-pass-keeps-overall 0 "$overall"
SCENARIO_T0=$(now)
record redis FAIL "no new primary"
eq record-fail-sets-overall 1 "$overall"
mark_not_run
eq not-run-sets-overall 1 "$overall"
GITHUB_RUN_ID=77 GITHUB_SERVER_URL=https://github.com GITHUB_REPOSITORY=o/r write_results
out="$(cat "$RESULTS_FILE")"
eq results-old-replaced no "$(has $'\nold\n' "$out")"
eq results-tail-kept yes "$(has "tail" "$out")"
eq results-header yes "$(has "| Scenario | Result | Duration | Details |" "$out")"
eq results-pass-row yes "$(has "| 1. PostgreSQL primary deleted | PASS | 42s | failover 9s |" "$out")"
eq results-fail-row yes "$(has "| 2. Valkey primary deleted | FAIL | 0s | no new primary |" "$out")"
eq results-not-run yes "$(has "| 4. Edge pod killed mid-stream | NOT RUN |" "$out")"
eq results-run-link yes "$(has "https://github.com/o/r/actions/runs/77" "$out")"
eq results-context yes "$(has "test ctx" "$out")"

# ── job summary: only when GITHUB_STEP_SUMMARY is set ───────────────────────
GITHUB_STEP_SUMMARY="$T/summary.md" write_summary
eq summary-written yes "$(has "| 2. Valkey primary deleted | FAIL | 0s |" "$(cat "$T/summary.md")")"
eq summary-verdict yes "$(has "FAIL" "$(head -n1 "$T/summary.md")")"
unset GITHUB_STEP_SUMMARY
eq summary-noop "" "$(write_summary 2>&1)"

printf '%d tests, %d failed\n' "$tests" "$failures"
((failures == 0))
