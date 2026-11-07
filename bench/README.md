# bench

Reproducible benchmark and evaluation harnesses. How to run them, what they
measure and how to read the results: [`docs/benchmarks/README.md`](../docs/benchmarks/README.md).

```bash
cd bench
go run ./a2-retrieval -dry-run   # check a harness without a stack
go test ./...                    # unit tests + dry runs of every harness
```

| Path | Contents |
|---|---|
| `a2-retrieval/`, `a3-ingest/`, `a5-sse/`, `eval/` | one command per benchmark |
| `eval/testdata/` | five-item fixture in the `examples/golden/golden.yaml` schema (dry runs and tests) |
| `internal/stack` | instrumented client for the control plane and the edge chat stream |
| `internal/fakestack` | in-process fake stack behind `-dry-run` and the tests |
| `internal/pdfgen` | deterministic bilingual PDF generator (A3 input) |
| `internal/report`, `internal/sysinfo`, `internal/stackenv` | dated result files, hardware/revision capture, whitelisted stack settings |

The module is standalone (same Go toolchain as `services/edge`; dependencies:
`gopkg.in/yaml.v3`, `golang.org/x/text` for Unicode normalization) and never
imports service internals. `go test ./...` needs no Docker and no stack.
