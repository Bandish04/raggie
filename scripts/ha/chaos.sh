#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Scenarios are dispatched as "scenario_$name"; single-quoted remote shell
# snippets expand inside the pod on purpose.
# shellcheck disable=SC2329,SC2016
# HA chaos suite (plan 5b.5) against the kind cluster from scripts/ha/up.sh.
# Each scenario runs the in-cluster k6 driver (scripts/ha/k6/chaos-load.js)
# while breaking one component, then checks the scenario's oracle:
#
#   pg         delete the PostgreSQL primary   -> failover < PG_FAILOVER_BUDGET s, no acked write lost
#   redis      delete the Valkey primary       -> Sentinel failover, no ingestion event lost, one primary
#   qdrant     delete a Qdrant node            -> chat/search uninterrupted (no 5xx, no stream errors)
#   edge       delete an edge pod mid-stream   -> drain + client reconnect, no 5xx; then a SIGKILL variant
#   ingestion  kill ingestion workers mid-parse -> every acked upload still reaches SUCCESS
#   upgrade    rolling upgrade under load       -> zero 5xx / connection errors, migration Job ran once
#
#   scripts/ha/chaos.sh                 # all scenarios
#   scripts/ha/chaos.sh pg edge         # a subset
# Results: a table (verdict, duration, details) between the results markers in
# docs/benchmarks/ha-chaos.md (RESULTS_FILE), also when the suite aborts
# (scenarios not reached are NOT RUN), plus $GITHUB_STEP_SUMMARY in Actions.
# Raw k6 logs under ARTIFACTS_DIR. Exit 1 if any scenario fails or does not run.
# The ha-chaos workflow (.github/workflows/ha-chaos.yml) runs it weekly.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

RESULTS_FILE="${RESULTS_FILE:-$REPO_ROOT/docs/benchmarks/ha-chaos.md}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$(mktemp -d)}"
PG_FAILOVER_BUDGET="${PG_FAILOVER_BUDGET:-30}"
REDIS_FAILOVER_BUDGET="${REDIS_FAILOVER_BUDGET:-30}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-300}"
CHAT_VUS="${CHAT_VUS:-4}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)}"
PG_CLUSTER="${RELEASE}-pg"
VALKEY="${RELEASE}-valkey"
mkdir -p "$ARTIFACTS_DIR"

declare -a RESULTS=() PLANNED=() DONE=()
overall=0
SCENARIO_T0=0

svc() { echo "http://${RELEASE}-$1.${NAMESPACE}.svc:$2"; }
EDGE_URL="$(svc edge 8080)"
CP_URL="$(svc control-plane 8000)"
WEB_URL="$(svc web 3000)"

scenario_title() {
  case "$1" in
    pg) echo "1. PostgreSQL primary deleted" ;;
    redis) echo "2. Valkey primary deleted" ;;
    qdrant) echo "3. Qdrant node deleted" ;;
    edge) echo "4. Edge pod killed mid-stream" ;;
    ingestion) echo "5. Ingestion worker killed mid-parse" ;;
    upgrade) echo "6. Rolling upgrade under load" ;;
    *) echo "$1" ;;
  esac
}

record() { # scenario verdict detail (duration: since SCENARIO_T0)
  local title secs=$(( $(now) - SCENARIO_T0 ))
  title="$(scenario_title "$1")"
  RESULTS+=("| $title | $2 | ${secs}s | $3 |")
  DONE+=("$1")
  if [[ "$2" == "PASS" ]]; then log "$title: PASS (${secs}s) — $3"; else warn "$title: $2 (${secs}s) — $3"; overall=1; fi
}

mark_not_run() { # planned scenarios without a verdict (the suite aborted)
  local s
  for s in "${PLANNED[@]}"; do
    [[ " ${DONE[*]-} " == *" $s "* ]] && continue
    RESULTS+=("| $(scenario_title "$s") | NOT RUN | - | the suite aborted before a verdict (see the logs) |")
    DONE+=("$s")
    overall=1
  done
}

# edge_graceful_ok RECONNECTS RESUMED RESUME_FAILED K6_RC: the delete really
# interrupted streams, and every one resumed on another replica.
edge_graceful_ok() {
  (($1 > 0 && $2 == $1 && $3 == 0 && $4 == 0))
}

# ── k6 driver ────────────────────────────────────────────────────────────────
k6_configmap() {
  kctl create configmap chaos-k6 --from-file="$HA_DIR/k6/chaos-load.js" --dry-run=client -o yaml \
    | kctl apply -f - >/dev/null
}

# k6_start NAME KEY=VALUE... — start a driver pod (does not wait).
k6_start() {
  local name="$1"; shift
  local env_yaml="" kv
  for kv in "EDGE_URL=$EDGE_URL" "CP_URL=$CP_URL" "WEB_URL=$WEB_URL" "RUN_ID=$RUN_ID-$name" \
    "TOKEN=${TOKEN:-}" "WS=${WS:-}" "$@"; do
    env_yaml+="        - { name: \"${kv%%=*}\", value: \"${kv#*=}\" }"$'\n'
  done
  kctl delete pod "chaos-$name" --ignore-not-found --wait=true >/dev/null
  kctl apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: chaos-$name
  labels: { raggie.io/chaos: "true" }
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 12345
    seccompProfile: { type: RuntimeDefault }
  containers:
    - name: k6
      image: $K6_IMAGE
      args: ["run", "--quiet", "/scripts/chaos-load.js"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: { drop: ["ALL"] }
      env:
$env_yaml
      volumeMounts:
        - { name: scripts, mountPath: /scripts }
  volumes:
    - name: scripts
      configMap: { name: chaos-k6 }
EOF
  wait_until 120 "driver running" bash -c \
    "kubectl --context kind-$CLUSTER_NAME -n $NAMESPACE get pod chaos-$name -o jsonpath='{.status.phase}' | grep -Eq 'Running|Succeeded|Failed'" \
    || die "driver chaos-$name did not start"
}

# k6_wait NAME — wait for the driver, save its log, return k6's verdict.
k6_wait() {
  local name="$1" phase
  wait_until 1800 "driver done" bash -c \
    "kubectl --context kind-$CLUSTER_NAME -n $NAMESPACE get pod chaos-$name -o jsonpath='{.status.phase}' | grep -Eq 'Succeeded|Failed'" \
    || die "driver chaos-$name timed out"
  kctl logs "chaos-$name" >"$ARTIFACTS_DIR/$name.log" 2>&1 || true
  phase="$(kctl get pod "chaos-$name" -o jsonpath='{.status.phase}')"
  [[ "$phase" == "Succeeded" ]]
}

k6_metric() { # NAME METRIC -> count (0 when absent)
  local v
  v="$(grep -E "^\s*$2\.*:" "$ARTIFACTS_DIR/$1.log" | head -n1 | awk '{print $2}')"
  echo "${v:-0}"
}

acked() { # NAME KIND(MSG|DOC) -> ids, one per line
  grep -oE "ACK_$2 [0-9a-f-]{36}" "$ARTIFACTS_DIR/$1.log" | awk '{print $2}' | sort -u || true
}

# ── datastore probes ─────────────────────────────────────────────────────────
pg_primary() { kctl get cluster "$PG_CLUSTER" -o jsonpath='{.status.currentPrimary}'; }

psql_q() {
  kctl exec "$(pg_primary)" -c postgres -- psql -U postgres -d raggie -Atc "$1"
}

sql_ids() { # newline ids -> 'a','b'
  sed "s/.*/'&'/" | paste -sd, -
}

# verify_messages NAME — every acked chat turn is persisted with content.
verify_messages() {
  local ids n found
  ids="$(acked "$1" MSG)"
  n="$(grep -c . <<<"$ids" || true)"
  [[ "$n" -gt 0 ]] || { echo "0/0"; return 1; }
  found="$(psql_q "SELECT count(*) FROM messages WHERE id IN ($(sql_ids <<<"$ids")) AND content <> ''")"
  echo "$found/$n"
  [[ "$found" == "$n" ]]
}

# verify_documents NAME — every acked upload reaches SUCCESS (none FAILED).
verify_documents() {
  local ids n deadline indexed failed
  ids="$(acked "$1" DOC)"
  n="$(grep -c . <<<"$ids" || true)"
  [[ "$n" -gt 0 ]] || { echo "0/0"; return 1; }
  deadline=$(( $(now) + VERIFY_TIMEOUT ))
  while :; do
    indexed="$(psql_q "SELECT count(*) FROM documents WHERE id IN ($(sql_ids <<<"$ids")) AND status IN ('SUCCESS','READY') AND deleted_at IS NULL")"
    failed="$(psql_q "SELECT count(*) FROM documents WHERE id IN ($(sql_ids <<<"$ids")) AND status = 'FAILED'")"
    if [[ "$indexed" == "$n" || "$failed" != "0" || $(now) -ge $deadline ]]; then break; fi
    sleep 5
  done
  echo "$indexed/$n ok, $failed failed"
  [[ "$indexed" == "$n" ]]
}

ratio_ok() { # "a/b ..." -> a == b > 0
  local a="${1%%/*}" b="${1#*/}"
  b="${b%% *}"
  [[ "$a" == "$b" && "$b" != "0" ]]
}
docs_ok() { ratio_ok "$1" && [[ "$1" == *", 0 failed" ]]; }

sentinel_primary() { # -> pod name of the current Valkey primary
  kctl exec "$VALKEY-0" -c sentinel -- sh -c \
    'REDISCLI_AUTH="$REDIS_PASSWORD" valkey-cli --no-auth-warning -p 26379 sentinel get-master-addr-by-name raggie | head -n1' \
    2>/dev/null | cut -d. -f1
}

valkey_primaries() { # number of pods reporting role:master
  local i c=0
  for i in 0 1 2; do
    if kctl exec "$VALKEY-$i" -c valkey -- sh -c \
      'REDISCLI_AUTH="$REDIS_PASSWORD" valkey-cli --no-auth-warning info replication' 2>/dev/null \
      | grep -q '^role:master'; then
      c=$((c + 1))
    fi
  done
  echo "$c"
}

qdrant() { # METHOD PATH [JSON] — Qdrant REST through a port-forward
  local key
  key="$(kctl get secret raggie-secrets -o jsonpath='{.data.QDRANT_API_KEY}' | base64 -d)"
  curl -fsS -X "$1" "http://127.0.0.1:16333$2" -H "api-key: $key" -H 'Content-Type: application/json' ${3:+-d "$3"}
}

# The workers create collections with QDRANT_REPLICATION_FACTOR=2; this tops up
# any shard that still has a single replica (a collection created before), so a
# node loss keeps all data online. A no-op on a correctly created collection.
qdrant_replicate() {
  local pf collections c
  kctl port-forward "svc/${RELEASE}-qdrant" 16333:6333 >/dev/null 2>&1 &
  pf=$!
  sleep 3
  collections="$(qdrant GET /collections | grep -oE '"name":"[^"]+"' | cut -d'"' -f4 | grep '^raggie_chunks' || true)"
  for c in $collections; do
    qdrant PATCH "/collections/$c" '{"replication_factor":2}' >/dev/null || true
    python3 - "$c" <<'PY' | while read -r body; do qdrant POST "/collections/$c/cluster" "$body" >/dev/null || true; done
import json, subprocess, sys
c = sys.argv[1]
def q(path):
    out = subprocess.run(["bash", "-c", f'curl -fsS http://127.0.0.1:16333{path} -H "api-key: $QKEY"'],
                         capture_output=True, text=True).stdout
    return json.loads(out)["result"]
peers = sorted(int(p) for p in q("/cluster")["peers"].keys())
info = q(f"/collections/{c}/cluster")
placement = {}
for s in info.get("local_shards", []):
    placement.setdefault(s["shard_id"], set()).add(info["peer_id"])
for s in info.get("remote_shards", []):
    placement.setdefault(s["shard_id"], set()).add(s["peer_id"])
for shard, holders in placement.items():
    if len(holders) < 2:
        src = next(iter(holders))
        dst = next(p for p in peers if p not in holders)
        print(json.dumps({"replicate_shard": {"shard_id": shard, "from_peer_id": src, "to_peer_id": dst}}))
PY
  done
  sleep 10
  kill "$pf" 2>/dev/null || true
}

# ── scenarios ────────────────────────────────────────────────────────────────
bootstrap() {
  local email password setup state
  email="$(kctl get secret raggie-chaos-admin -o jsonpath='{.data.email}' | base64 -d)"
  password="$(kctl get secret raggie-chaos-admin -o jsonpath='{.data.password}' | base64 -d)"
  setup="$(kctl get secret raggie-secrets -o jsonpath='{.data.SETUP_TOKEN}' | base64 -d)"
  k6_start bootstrap MODE=bootstrap "ADMIN_EMAIL=$email" "ADMIN_PASSWORD=$password" "SETUP_TOKEN=$setup"
  k6_wait bootstrap || { cat "$ARTIFACTS_DIR/bootstrap.log"; die "bootstrap failed"; }
  state="$(grep -oE 'STATE \{.*\}' "$ARTIFACTS_DIR/bootstrap.log" | head -n1 | cut -d' ' -f2-)"
  TOKEN="$(sed -E 's/.*"token":"([^"]+)".*/\1/' <<<"$state")"
  WS="$(sed -E 's/.*"workspace_id":"([^"]+)".*/\1/' <<<"$state")"
  [[ -n "$TOKEN" && -n "$WS" ]] || die "bootstrap printed no state"
  log "workspace $WS"
  # Seed documents so chat retrieves real chunks and the collection exists.
  k6_start seed DURATION=5s CHAT_VUS=0 WEB_VUS=0 UPLOAD_RATE=1
  k6_wait seed || die "seed upload failed"
  verify_documents seed >/dev/null || die "seed documents did not index"
  export QKEY
  QKEY="$(kctl get secret raggie-secrets -o jsonpath='{.data.QDRANT_API_KEY}' | base64 -d)"
  qdrant_replicate
}

scenario_pg() {
  local old new t0 elapsed msgs docs
  k6_start pg DURATION=120s "CHAT_VUS=$CHAT_VUS" WEB_VUS=2 UPLOAD_RATE=1 MAX_5XX=100000 MAX_CONN_ERRORS=100000 MAX_SSE_ERRORS=100000
  sleep 25
  old="$(pg_primary)"
  log "pg: force-deleting primary $old"
  t0=$(now)
  kctl delete pod "$old" --grace-period=0 --force >/dev/null 2>&1
  wait_until 180 "new primary" bash -c "new=\$(kubectl --context kind-$CLUSTER_NAME -n $NAMESPACE get cluster $PG_CLUSTER -o jsonpath='{.status.currentPrimary}'); [[ -n \$new && \$new != $old ]] && kubectl --context kind-$CLUSTER_NAME -n $NAMESPACE wait --for=condition=Ready pod/\$new --timeout=1s" || true
  elapsed=$(( $(now) - t0 ))
  new="$(pg_primary)"
  k6_wait pg || true
  msgs="$(verify_messages pg)" || true
  docs="$(verify_documents pg)" || true
  local detail
  detail="failover ${elapsed}s ($old -> $new), acked chat turns persisted $msgs, uploads $docs, 5xx during failover $(k6_metric pg http_5xx)"
  if [[ "$new" != "$old" && $elapsed -le $PG_FAILOVER_BUDGET ]] && ratio_ok "$msgs" && docs_ok "$docs"; then
    record pg PASS "$detail"
  else
    record pg FAIL "$detail"
  fi
}

scenario_redis() {
  local old new t0 elapsed docs primaries
  k6_start redis DURATION=120s "CHAT_VUS=$CHAT_VUS" WEB_VUS=1 UPLOAD_RATE=1 MAX_5XX=100000 MAX_CONN_ERRORS=100000 MAX_SSE_ERRORS=100000
  sleep 25
  old="$(sentinel_primary)"
  log "redis: force-deleting primary $old"
  t0=$(now)
  kctl delete pod "$old" --grace-period=0 --force >/dev/null 2>&1
  new=""
  for _ in $(seq 1 120); do
    new="$(sentinel_primary || true)"
    [[ -n "$new" && "$new" != "$old" ]] && break
    sleep 1
  done
  elapsed=$(( $(now) - t0 ))
  k6_wait redis || true
  docs="$(verify_documents redis)" || true
  kctl wait --for=condition=Ready "pod/$old" --timeout=120s >/dev/null 2>&1 || true
  sleep 10
  primaries="$(valkey_primaries)"
  local detail
  detail="sentinel failover ${elapsed}s ($old -> $new), uploads (events) $docs, primaries after rejoin: $primaries, 5xx $(k6_metric redis http_5xx), stream errors $(k6_metric redis sse_errors)"
  if [[ -n "$new" && "$new" != "$old" && $elapsed -le $REDIS_FAILOVER_BUDGET && "$primaries" == "1" ]] && docs_ok "$docs"; then
    record redis PASS "$detail"
  else
    record redis FAIL "$detail"
  fi
}

scenario_qdrant() {
  local victim="${RELEASE}-qdrant-1"
  k6_start qdrant DURATION=90s "CHAT_VUS=$CHAT_VUS" WEB_VUS=0
  sleep 20
  log "qdrant: force-deleting $victim"
  kctl delete pod "$victim" --grace-period=0 --force >/dev/null 2>&1
  if k6_wait qdrant; then
    record qdrant PASS "chat turns done $(k6_metric qdrant chat_done), 5xx 0, stream errors 0"
  else
    record qdrant FAIL "5xx $(k6_metric qdrant http_5xx), conn errors $(k6_metric qdrant conn_errors), stream errors $(k6_metric qdrant sse_errors) (see $ARTIFACTS_DIR/qdrant.log)"
  fi
  kctl wait --for=condition=Ready "pod/$victim" --timeout=180s >/dev/null 2>&1 || true
}

scenario_edge() {
  local victim
  k6_start edge DURATION=90s "CHAT_VUS=$CHAT_VUS" WEB_VUS=0
  sleep 20
  victim="$(kctl get pods -l app.kubernetes.io/component=edge -o jsonpath='{.items[0].metadata.name}')"
  log "edge: deleting $victim (graceful: readiness drop, drain, reconnect)"
  kctl delete pod "$victim" --wait=false >/dev/null
  local ok=0 k6rc=0 rc rs rf msgs
  k6_wait edge || k6rc=1
  rc="$(k6_metric edge sse_reconnect)" rs="$(k6_metric edge sse_resumed)" rf="$(k6_metric edge resume_failed)"
  msgs="$(verify_messages edge)" || true
  edge_graceful_ok "$rc" "$rs" "$rf" "$k6rc" && ratio_ok "$msgs" || ok=1
  local detail
  detail="graceful delete: reconnect events $rc, resumed via resume_message_id $rs, resume failures $rf, acked turns persisted $msgs, 5xx $(k6_metric edge http_5xx), conn errors $(k6_metric edge conn_errors)"
  # Hard kill: in-flight streams break; each VU may lose at most one stream and
  # must recover on the next request.
  k6_start edgekill DURATION=60s "CHAT_VUS=$CHAT_VUS" WEB_VUS=0 "MAX_CONN_ERRORS=$CHAT_VUS"
  sleep 20
  victim="$(kctl get pods -l app.kubernetes.io/component=edge -o jsonpath='{.items[0].metadata.name}')"
  log "edge: SIGKILL $victim"
  kctl delete pod "$victim" --grace-period=0 --force >/dev/null 2>&1
  k6_wait edgekill || ok=1
  detail+="; SIGKILL: conn errors $(k6_metric edgekill conn_errors) (budget $CHAT_VUS), 5xx $(k6_metric edgekill http_5xx), turns done after kill $(k6_metric edgekill chat_done)"
  if [[ $ok -eq 0 ]]; then record edge PASS "$detail"; else record edge FAIL "$detail"; fi
}

scenario_ingestion() {
  local pods p docs
  k6_start ingestion DURATION=60s CHAT_VUS=0 WEB_VUS=0 UPLOAD_RATE=1 UPLOAD_KB=768
  sleep 15
  pods="$(kctl get pods -l app.kubernetes.io/component=ingestion-worker -o jsonpath='{.items[*].metadata.name}')"
  for p in $pods; do
    log "ingestion: SIGKILL $p"
    kctl delete pod "$p" --grace-period=0 --force >/dev/null 2>&1
    sleep 15
  done
  k6_wait ingestion || true
  docs="$(verify_documents ingestion)" || true
  if docs_ok "$docs"; then
    record ingestion PASS "uploads $docs (workers killed: $pods)"
  else
    record ingestion FAIL "uploads $docs"
  fi
}

scenario_upgrade() {
  local ok=0 job_ok pods
  k6_start upgrade DURATION=240s "CHAT_VUS=$CHAT_VUS" WEB_VUS=2 UPLOAD_RATE=1
  sleep 20
  log "upgrade: helm upgrade (config change rolls every app Deployment; pre-upgrade migration hook)"
  helm --kube-context "kind-$CLUSTER_NAME" upgrade "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" \
    -f "$CHART_DIR/values-ha.yaml" -f "$HA_DIR/values-kind.yaml" \
    --set-string "config.extraEnv.CHAOS_ROLLOUT=$RUN_ID" --wait --timeout 15m >/dev/null || ok=1
  k6_wait upgrade || ok=1
  job_ok="$(kctl get job "${RELEASE}-migrate" -o jsonpath='{.status.succeeded}/{.status.failed}' 2>/dev/null || echo missing)"
  pods="$(kctl get pods -l job-name="${RELEASE}-migrate" --no-headers 2>/dev/null | grep -c . || true)"
  local detail
  detail="5xx $(k6_metric upgrade http_5xx), conn errors $(k6_metric upgrade conn_errors), stream errors $(k6_metric upgrade sse_errors), turns done $(k6_metric upgrade chat_done), resumed $(k6_metric upgrade sse_resumed)/$(k6_metric upgrade sse_reconnect); migration hook succeeded/failed=$job_ok, pods=$pods"
  if [[ $ok -eq 0 && "$job_ok" == "1/" && "$pods" == "1" ]]; then
    record upgrade PASS "$detail"
  else
    record upgrade FAIL "$detail"
  fi
}

cluster_context() {
  local v n
  v="$(kubectl --context "kind-$CLUSTER_NAME" version -o json 2>/dev/null | grep -m1 -A3 serverVersion | grep gitVersion | cut -d'"' -f4)" || true
  n="$(kubectl --context "kind-$CLUSTER_NAME" get nodes --no-headers 2>/dev/null | grep -c .)" || true
  echo "kind ${v:-?}, ${n:-?} nodes, chart $(grep '^version:' "$CHART_DIR/Chart.yaml" | awk '{print $2}'), CHAT_VUS=$CHAT_VUS"
}

results_table() {
  echo "| Scenario | Result | Duration | Details |"
  echo "|---|---|---|---|"
  printf '%s\n' "${RESULTS[@]}"
}

write_results() {
  local tmp ctx run=""
  ctx="${CHAOS_CONTEXT:-$(cluster_context)}"
  [[ -n "${GITHUB_RUN_ID:-}" ]] && run=" — run ${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/$GITHUB_RUN_ID"
  tmp="$(mktemp)"
  {
    echo "<!-- results:begin -->"
    echo "Last run: $(date -u +%Y-%m-%dT%H:%M:%SZ) — $ctx$run"
    echo
    results_table
    echo "<!-- results:end -->"
  } >"$tmp"
  python3 - "$RESULTS_FILE" "$tmp" <<'PY'
import re, sys
path, block = sys.argv[1], open(sys.argv[2]).read().strip()
text = open(path).read()
text = re.sub(r"<!-- results:begin -->.*?<!-- results:end -->", lambda _: block, text, flags=re.S)
open(path, "w").write(text)
PY
  rm -f "$tmp"
  log "results written to $RESULTS_FILE (logs: $ARTIFACTS_DIR)"
}

write_summary() { # GitHub Actions job summary; no-op elsewhere
  [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] || return 0
  local verdict=PASS
  [[ $overall -eq 0 ]] || verdict=FAIL
  {
    echo "### HA chaos: $verdict"
    echo
    echo "${CHAOS_CONTEXT:-$(cluster_context)}"
    echo
    results_table
  } >>"$GITHUB_STEP_SUMMARY"
}

# EXIT trap: record what did not run, then always write the results.
finish() {
  local rc=$?
  trap - EXIT
  mark_not_run
  write_results
  write_summary
  [[ $rc -eq 0 ]] || overall=1
  exit "$overall"
}

main() {
  local scenarios=("$@") s
  [[ ${#scenarios[@]} -gt 0 ]] || scenarios=(pg redis qdrant edge ingestion upgrade)
  for s in "${scenarios[@]}"; do
    case "$s" in
      pg | redis | qdrant | edge | ingestion | upgrade) ;;
      *) die "unknown scenario: $s" ;;
    esac
  done
  need kubectl
  need helm
  kubectl --context "kind-$CLUSTER_NAME" get ns "$NAMESPACE" >/dev/null || die "run scripts/ha/up.sh first"
  PLANNED=("${scenarios[@]}")
  trap finish EXIT
  k6_configmap
  bootstrap
  for s in "${scenarios[@]}"; do
    SCENARIO_T0=$(now)
    "scenario_$s"
  done
}

[[ "${CHAOS_LIB_ONLY:-}" == 1 ]] || main "$@"
