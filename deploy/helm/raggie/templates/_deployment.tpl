{{/*
Shared Deployment shape for the app components.
dict:
  root        top-level context
  component   app.kubernetes.io/component (also the object name suffix)
  svc         image name suffix (raggie-<svc>)
  values      the component's values block
  common      optional shared block for nodeSelector/tolerations/affinity/podSecurityContext
  replicas    replica count
  autoscaled  omit spec.replicas (HPA/KEDA owns it)
  ports       list of {name, port}
  probePort   port name for probes
  readyPath / livePath
  env         rendered env entries (YAML string)
  volumeMounts / volumes  extra rendered YAML strings
  grace       terminationGracePeriodSeconds
*/}}
{{- define "raggie.deployment" -}}
{{- $root := .root -}}
{{- $v := .values -}}
{{- $common := .common | default dict -}}
{{- $sel := dict "root" $root "component" .component }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "raggie.componentName" $sel }}
  labels:
    {{- include "raggie.componentLabels" $sel | nindent 4 }}
spec:
  {{- if not .autoscaled }}
  replicas: {{ .replicas }}
  {{- end }}
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      # Never drop below the desired count during a rollout.
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      {{- include "raggie.selectorLabels" $sel | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "raggie.componentLabels" $sel | nindent 8 }}
      annotations:
        checksum/config: {{ include (print $root.Template.BasePath "/configmap.yaml") $root | sha256sum }}
    spec:
      serviceAccountName: {{ include "raggie.serviceAccountName" $root }}
      automountServiceAccountToken: false
      {{- include "raggie.imagePullSecrets" $root | nindent 6 }}
      {{- with .grace }}
      terminationGracePeriodSeconds: {{ . }}
      {{- end }}
      securityContext:
        {{- include "raggie.podSecurityContext" (dict "root" $root "override" ($v.podSecurityContext | default $common.podSecurityContext)) | nindent 8 }}
      {{- if gt (int .replicas) 1 }}
      {{- include "raggie.topologySpread" $sel | nindent 6 }}
      {{- end }}
      {{- with ($v.nodeSelector | default $common.nodeSelector) }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with ($v.tolerations | default $common.tolerations) }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with ($v.affinity | default $common.affinity) }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- else }}
      {{- if gt (int .replicas) 1 }}
      {{- include "raggie.antiAffinity" $sel | nindent 6 }}
      {{- end }}
      {{- end }}
      containers:
        - name: {{ .component }}
          image: {{ include "raggie.image" (dict "root" $root "svc" .svc "image" (.image | default dict)) }}
          imagePullPolicy: {{ $root.Values.image.pullPolicy }}
          securityContext:
            {{- include "raggie.containerSecurityContext" $root | nindent 12 }}
          ports:
            {{- range .ports }}
            - name: {{ .name }}
              containerPort: {{ .port }}
              protocol: TCP
            {{- end }}
          envFrom:
            - configMapRef:
                name: {{ include "raggie.fullname" $root }}-config
          env:
            {{- .env | nindent 12 }}
          startupProbe:
            httpGet: { path: {{ .livePath }}, port: {{ .probePort }} }
            periodSeconds: 5
            failureThreshold: {{ .startupFailureThreshold | default 30 }}
          readinessProbe:
            httpGet: { path: {{ .readyPath }}, port: {{ .probePort }} }
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 2
          livenessProbe:
            httpGet: { path: {{ .livePath }}, port: {{ .probePort }} }
            periodSeconds: 15
            timeoutSeconds: 3
            failureThreshold: 4
          resources:
            {{- toYaml $v.resources | nindent 12 }}
          volumeMounts:
            {{- include "raggie.tmpVolumeMount" $root | nindent 12 }}
            {{- with .volumeMounts }}
            {{- . | nindent 12 }}
            {{- end }}
      volumes:
        {{- include "raggie.tmpVolume" $root | nindent 8 }}
        {{- with .volumes }}
        {{- . | nindent 8 }}
        {{- end }}
{{- end -}}
