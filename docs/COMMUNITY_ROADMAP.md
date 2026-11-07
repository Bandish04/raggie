# Community roadmap

A practical list for contributors deciding where to help. It is a direction, not a
promise of dates; the [known limitations](../README.md#known-limitations) explain
the current gaps.

## Done in 0.1.0

- Benchmark and evaluation harnesses in [`bench/`](../bench/) (`make bench-a2`,
  `bench-a3`, `bench-a5`) and a TR/EN golden Q&A set over
  `examples/sample-corpus` with `make eval` (recall@k, MRR, citation accuracy).
- Cloud embeddings: installer presets, the admin embeddings card and the
  re-embed flow.
- Installer: release-pinned, checksum-verified downloads; Ollama and mock LLM
  choices; Caddy front door with automatic HTTPS.
- `make setup` and `make test-integration` for a one-command contributor setup.
- Helm chart with single-node and HA profiles.
- Backup, restore and disaster-recovery drill scripts.
- Web UI for the widget origin allow-list.

## Now (towards 0.1.x)

- Publish benchmark results: retrieval latency, ingestion speed, streaming
  concurrency and the golden-set scores, with hardware, commands and raw
  results in `docs/benchmarks/`.
- Validate cloud embeddings end to end against a live provider.
- Measure the faithfulness judge (precision/recall on labelled answers).

## Next (0.2)

- Per-organization MCP credentials (today one operator credential is shared).
- A per-workspace toggle for MCP write tools (today `MCP_ALLOW_WRITE_TOOLS` is a
  single deployment-wide switch).
- `*_FILE` secret files for all services (today only the control plane resolves
  them).
- PostgreSQL row-level security as a second layer of tenant isolation.
- Helm chart hardening: chaos and disaster-recovery drills for the HA profile.
- Web UI for SSO (OIDC login button).
- Retention policies and workspace/organization deletion.

## Later

- Document-level access control.
- Planned: a Kafka/Redpanda event-bus adapter for large deployments (Valkey
  Streams is the only bus today).
- More MCP servers and data-source connectors.
- Advanced retrieval (query rewriting, recall improvements).

## Contribution lanes

| Lane | Good places to start |
|---|---|
| Performance | retrieval latency instrumentation, streaming metrics, ingestion throughput |
| Quality | golden eval sets, citation-correctness tooling, failure-mode analysis |
| Security & ops | HA/DR drills, deployment hardening, more authorization tests |
| DX & docs | local setup, reproducible tests, examples, translations |

Issues labelled `good first issue` and `help wanted` are the easiest way in. Read
[CONTRIBUTING.md](../CONTRIBUTING.md) first.
