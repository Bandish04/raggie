{{/* ── Names ─────────────────────────────────────────────────────────── */}}
{{- define "raggie.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "raggie.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* "<fullname>-<component>" */}}
{{- define "raggie.componentName" -}}
{{- printf "%s-%s" (include "raggie.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "raggie.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "raggie.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* ── Labels ────────────────────────────────────────────────────────── */}}
{{- define "raggie.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "raggie.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: raggie
{{- end -}}

{{/* dict root component -> selector labels of one component */}}
{{- define "raggie.selectorLabels" -}}
app.kubernetes.io/name: {{ include "raggie.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "raggie.componentLabels" -}}
{{ include "raggie.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* ── Images ────────────────────────────────────────────────────────── */}}
{{/* dict root svc image(map with repository/tag) */}}
{{- define "raggie.image" -}}
{{- $root := .root -}}
{{- $repo := .image.repository | default (printf "%s/%s%s" $root.Values.image.registry $root.Values.image.prefix .svc) -}}
{{- $tag := .image.tag | default $root.Values.image.tag | default $root.Chart.AppVersion -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}

{{- define "raggie.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{/* ── Security ──────────────────────────────────────────────────────── */}}
{{/* dict root override(map) */}}
{{- define "raggie.podSecurityContext" -}}
{{- toYaml (merge (deepCopy (.override | default dict)) (deepCopy .root.Values.podSecurityContext)) -}}
{{- end -}}

{{- define "raggie.containerSecurityContext" -}}
{{- toYaml .Values.containerSecurityContext -}}
{{- end -}}

{{/* dict root component -> zone + hostname spread for one component */}}
{{- define "raggie.topologySpread" -}}
{{- if .root.Values.topologySpread.enabled }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "raggie.selectorLabels" . | nindent 8 }}
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: {{ ternary "DoNotSchedule" "ScheduleAnyway" .root.Values.topologySpread.strictHostname }}
    labelSelector:
      matchLabels:
        {{- include "raggie.selectorLabels" . | nindent 8 }}
{{- end }}
{{- end -}}

{{/* dict root component -> preferred anti-affinity across nodes (datastores) */}}
{{- define "raggie.antiAffinity" -}}
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname
          labelSelector:
            matchLabels:
              {{- include "raggie.selectorLabels" . | nindent 14 }}
{{- end -}}

{{/* ── Secrets ───────────────────────────────────────────────────────── */}}
{{- define "raggie.appSecretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-dev-secrets" (include "raggie.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* dict root keys(list of "ENV" or "ENV?" for optional) -> env entries */}}
{{- define "raggie.secretEnv" -}}
{{- $secret := include "raggie.appSecretName" .root -}}
{{- range .keys }}
{{- $optional := hasSuffix "?" . }}
{{- $key := trimSuffix "?" . }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $key }}
      {{- if $optional }}
      optional: true
      {{- end }}
{{- end }}
{{- end -}}

{{/* ── Endpoints ─────────────────────────────────────────────────────── */}}
{{- define "raggie.cnpgClusterName" -}}
{{- include "raggie.componentName" (dict "root" . "component" "pg") -}}
{{- end -}}

{{- define "raggie.postgresHost" -}}
{{- if and (eq .Values.postgresql.mode "cnpg") .Values.postgresql.cnpg.pooler.enabled -}}
{{- printf "%s-pooler-rw" (include "raggie.cnpgClusterName" .) -}}
{{- else -}}
{{- include "raggie.postgresDirectHost" . -}}
{{- end -}}
{{- end -}}

{{/* The primary itself, never the pooler. The migration Job holds a session
     advisory lock across statements; behind a transaction-mode PgBouncer the
     unlock can land on another backend and leak the lock, hanging the next run. */}}
{{- define "raggie.postgresDirectHost" -}}
{{- if eq .Values.postgresql.mode "cnpg" -}}
{{- printf "%s-rw" (include "raggie.cnpgClusterName" .) -}}
{{- else if eq .Values.postgresql.mode "external" -}}
{{- required "postgresql.external.host is required for postgresql.mode=external" .Values.postgresql.external.host -}}
{{- else -}}
{{- include "raggie.componentName" (dict "root" . "component" "postgres") -}}
{{- end -}}
{{- end -}}

{{- define "raggie.postgresPort" -}}
{{- if eq .Values.postgresql.mode "external" -}}{{ .Values.postgresql.external.port }}{{- else -}}5432{{- end -}}
{{- end -}}

{{/* POSTGRES_* + DATABASE_URL. The password comes from the mode's Secret and is
     spliced into DATABASE_URL with $(VAR) expansion; it must be URL-safe
     (generated and CNPG passwords are alphanumeric). */}}
{{- define "raggie.databaseEnv" -}}
{{- include "raggie.databaseEnvFor" (dict "root" . "host" (include "raggie.postgresHost" .)) -}}
{{- end -}}

{{/* Same, but pinned to the primary (see raggie.postgresDirectHost). */}}
{{- define "raggie.databaseEnvDirect" -}}
{{- include "raggie.databaseEnvFor" (dict "root" . "host" (include "raggie.postgresDirectHost" .)) -}}
{{- end -}}

{{- define "raggie.databaseEnvFor" -}}
{{- $host := .host -}}
{{- with .root -}}
{{- $pg := .Values.postgresql -}}
- name: POSTGRES_HOST
  value: {{ $host | quote }}
- name: POSTGRES_PORT
  value: {{ include "raggie.postgresPort" . | quote }}
- name: POSTGRES_DB
  value: {{ $pg.database | quote }}
- name: POSTGRES_USER
  value: {{ $pg.user | quote }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      {{- if eq $pg.mode "cnpg" }}
      name: {{ include "raggie.cnpgClusterName" . }}-app
      key: password
      {{- else if eq $pg.mode "external" }}
      name: {{ required "postgresql.external.existingSecret is required" $pg.external.existingSecret }}
      key: {{ $pg.external.passwordKey }}
      {{- else }}
      name: {{ include "raggie.appSecretName" . }}
      key: POSTGRES_PASSWORD
      {{- end }}
- name: DATABASE_URL
  value: {{ printf "postgresql://%s:$(POSTGRES_PASSWORD)@%s:%s/%s" $pg.user $host (include "raggie.postgresPort" .) $pg.database }}{{ if eq $pg.mode "external" }}?sslmode={{ $pg.external.sslmode }}{{ end }}
{{- end -}}
{{- end -}}

{{- define "raggie.valkeyName" -}}
{{- include "raggie.componentName" (dict "root" . "component" "valkey") -}}
{{- end -}}

{{- define "raggie.sentinelAddrs" -}}
{{- if eq .Values.valkey.mode "external" -}}
{{- .Values.valkey.external.sentinelAddrs -}}
{{- else if eq .Values.valkey.mode "sentinel" -}}
{{- $name := include "raggie.valkeyName" . -}}
{{- $addrs := list -}}
{{- range $i := until (int .Values.valkey.replicas) -}}
{{- $addrs = append $addrs (printf "%s-%d.%s-headless.%s.svc:26379" $name $i $name $.Release.Namespace) -}}
{{- end -}}
{{- join "," $addrs -}}
{{- end -}}
{{- end -}}

{{- define "raggie.sentinelMaster" -}}
{{- if eq .Values.valkey.mode "external" -}}
{{- .Values.valkey.external.sentinelMaster -}}
{{- else if eq .Values.valkey.mode "sentinel" -}}
{{- .Values.valkey.sentinel.masterSet -}}
{{- end -}}
{{- end -}}

{{/* Host of the "current primary" endpoint for REDIS_URL. */}}
{{- define "raggie.redisHost" -}}
{{- if eq .Values.valkey.mode "sentinel" -}}
{{- if .Values.valkey.haproxy.enabled -}}
{{- printf "%s-primary" (include "raggie.valkeyName" .) -}}
{{- else -}}
{{- printf "%s-0.%s-headless" (include "raggie.valkeyName" .) (include "raggie.valkeyName" .) -}}
{{- end -}}
{{- else -}}
{{- include "raggie.valkeyName" . -}}
{{- end -}}
{{- end -}}

{{- define "raggie.redisEnv" -}}
{{- $v := .Values.valkey -}}
{{- if $v.auth }}
- name: REDIS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "raggie.appSecretName" . }}
      key: REDIS_PASSWORD
{{- end }}
- name: REDIS_URL
{{- if eq $v.mode "external" }}
  value: {{ required "valkey.external.url is required for valkey.mode=external" $v.external.url | quote }}
{{- else if $v.auth }}
  value: "redis://:$(REDIS_PASSWORD)@{{ include "raggie.redisHost" . }}:6379/0"
{{- else }}
  value: "redis://{{ include "raggie.redisHost" . }}:6379/0"
{{- end }}
{{- with include "raggie.sentinelAddrs" . }}
- name: REDIS_SENTINEL_ADDRS
  value: {{ . | quote }}
- name: REDIS_SENTINEL_MASTER
  value: {{ include "raggie.sentinelMaster" $ | quote }}
{{- if $v.auth }}
- name: REDIS_SENTINEL_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "raggie.appSecretName" $ }}
      key: REDIS_PASSWORD
{{- end }}
{{- end }}
{{- end -}}

{{- define "raggie.qdrantUrl" -}}
{{- if .Values.vectordb.url -}}
{{- .Values.vectordb.url -}}
{{- else if eq .Values.vectordb.mode "cluster" -}}
{{- $name := "qdrant" -}}
{{- if contains $name .Release.Name -}}
{{- printf "http://%s:6333" .Release.Name -}}
{{- else -}}
{{- printf "http://%s-%s:6333" .Release.Name $name -}}
{{- end -}}
{{- else if eq .Values.vectordb.mode "single" -}}
{{- printf "http://%s:6333" (include "raggie.componentName" (dict "root" . "component" "qdrant")) -}}
{{- else -}}
{{- fail "vectordb.url is required for vectordb.mode=external" -}}
{{- end -}}
{{- end -}}

{{- define "raggie.s3SecretName" -}}
{{- if .Values.s3.existingSecret -}}
{{- .Values.s3.existingSecret -}}
{{- else if eq .Values.s3.mode "external" -}}
{{- fail "s3.existingSecret is required for s3.mode=external" -}}
{{- else -}}
{{- include "raggie.appSecretName" . -}}
{{- end -}}
{{- end -}}

{{- define "raggie.s3AccessKeyKey" -}}
{{- if .Values.s3.existingSecret -}}{{ .Values.s3.accessKeyKey }}{{- else -}}S3_ACCESS_KEY{{- end -}}
{{- end -}}

{{- define "raggie.s3SecretKeyKey" -}}
{{- if .Values.s3.existingSecret -}}{{ .Values.s3.secretKeyKey }}{{- else -}}S3_SECRET_KEY{{- end -}}
{{- end -}}

{{/* MINIO_* is the env contract of the S3 client in control-plane/workers. */}}
{{- define "raggie.s3Env" -}}
- name: MINIO_ENDPOINT
{{- if eq .Values.s3.mode "external" }}
  value: {{ required "s3.external.endpoint is required for s3.mode=external" .Values.s3.external.endpoint | quote }}
- name: MINIO_USE_SSL
  value: {{ .Values.s3.external.useSSL | quote }}
{{- else }}
  value: "{{ include "raggie.componentName" (dict "root" . "component" "seaweedfs") }}:8333"
- name: MINIO_USE_SSL
  value: "false"
{{- end }}
- name: MINIO_BUCKET
  value: {{ .Values.s3.bucket | quote }}
- name: MINIO_ROOT_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "raggie.s3SecretName" . }}
      key: {{ include "raggie.s3AccessKeyKey" . }}
- name: MINIO_ROOT_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "raggie.s3SecretName" . }}
      key: {{ include "raggie.s3SecretKeyKey" . }}
{{- end -}}

{{- define "raggie.llmBaseUrl" -}}
{{- if .Values.mockLLM.enabled -}}
{{- printf "http://%s:%d/v1" (include "raggie.componentName" (dict "root" . "component" "mockllm")) (int .Values.mockLLM.port) -}}
{{- else -}}
{{- .Values.config.llm.baseUrl -}}
{{- end -}}
{{- end -}}

{{/* Kubernetes CPU quantity ("2", "1.5", "500m") -> millicores; 0 when empty. */}}
{{- define "raggie.cpuMillis" -}}
{{- $q := toString (. | default "") -}}
{{- if not $q -}}0
{{- else if hasSuffix "m" $q -}}{{ trimSuffix "m" $q | int }}
{{- else -}}{{ mulf (float64 $q) 1000 | int }}
{{- end -}}
{{- end -}}

{{/* EMBEDDINGS_ONNX_THREADS: explicit value, else 4 capped at the CPU limit. */}}
{{- define "raggie.onnxThreads" -}}
{{- $m := .Values.embeddings -}}
{{- if $m.onnxThreads -}}{{ $m.onnxThreads }}
{{- else -}}
{{- $limit := include "raggie.cpuMillis" (dig "limits" "cpu" "" ($m.resources | default dict)) | int -}}
{{- if and (gt $limit 0) (lt $limit 4000) -}}{{ max 1 (div $limit 1000) }}{{- else -}}4{{- end -}}
{{- end -}}
{{- end -}}

{{/* map -> env list */}}
{{- define "raggie.envMap" -}}
{{- range $k, $v := . }}
- name: {{ $k }}
  value: {{ $v | toString | quote }}
{{- end }}
{{- end -}}

{{/* Writable scratch space under a read-only root filesystem. */}}
{{- define "raggie.tmpVolumeMount" -}}
- name: tmp
  mountPath: /tmp
{{- end -}}

{{- define "raggie.tmpVolume" -}}
- name: tmp
  emptyDir:
    sizeLimit: 1Gi
{{- end -}}

{{/* ── Render-time validation ────────────────────────────────────────── */}}
{{- define "raggie.validate" -}}
{{- $v := .Values -}}
{{- if not (has $v.profile (list "single" "ha")) -}}
{{- fail "profile must be single or ha" -}}
{{- end -}}
{{- if not (has $v.postgresql.mode (list "internal" "cnpg" "external")) -}}
{{- fail "postgresql.mode must be internal, cnpg or external" -}}
{{- end -}}
{{- if not (has $v.valkey.mode (list "standalone" "sentinel" "external")) -}}
{{- fail "valkey.mode must be standalone, sentinel or external" -}}
{{- end -}}
{{- if not (has $v.vectordb.mode (list "single" "cluster" "external")) -}}
{{- fail "vectordb.mode must be single, cluster or external" -}}
{{- end -}}
{{- if not (has $v.s3.mode (list "seaweedfs" "external")) -}}
{{- fail "s3.mode must be seaweedfs or external" -}}
{{- end -}}
{{- if ne (eq $v.vectordb.mode "cluster") (and $v.qdrant $v.qdrant.enabled | default false) -}}
{{- fail "vectordb.mode=cluster and qdrant.enabled=true go together" -}}
{{- end -}}
{{- if and (not $v.secrets.existingSecret) (not $v.secrets.generateDevSecret) -}}
{{- fail "set secrets.existingSecret (or secrets.generateDevSecret=true in the single profile)" -}}
{{- end -}}
{{- if eq $v.profile "ha" -}}
{{- if or $v.secrets.generateDevSecret (not $v.secrets.existingSecret) -}}
{{- fail "profile=ha requires secrets.existingSecret and secrets.generateDevSecret=false" -}}
{{- end -}}
{{- if eq $v.postgresql.mode "internal" -}}
{{- fail "profile=ha does not support postgresql.mode=internal (use cnpg or external)" -}}
{{- end -}}
{{- if eq $v.valkey.mode "standalone" -}}
{{- fail "profile=ha does not support valkey.mode=standalone (use sentinel or external)" -}}
{{- end -}}
{{- if eq $v.vectordb.mode "single" -}}
{{- fail "profile=ha does not support vectordb.mode=single (use cluster or external)" -}}
{{- end -}}
{{- end -}}
{{- if and (eq $v.valkey.mode "sentinel") (lt (int $v.valkey.replicas) 3) -}}
{{- fail "valkey.mode=sentinel needs valkey.replicas >= 3 for a quorum" -}}
{{- end -}}
{{- if lt (int $v.edge.shutdown.terminationGraceSeconds) (add (int $v.edge.shutdown.delaySeconds) (int $v.edge.shutdown.drainSeconds) 3 | int) -}}
{{- fail "edge.shutdown.terminationGraceSeconds must be >= delaySeconds + drainSeconds + 3" -}}
{{- end -}}
{{- end -}}
