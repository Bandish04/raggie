# syntax=docker/dockerfile:1
# SPDX-License-Identifier: Apache-2.0

# ── build stage ──────────────────────────────────────────────
FROM golang:1.26-alpine AS build
WORKDIR /src

# Dependency layer.
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/edge ./cmd/edge

# ── runtime stage ────────────────────────────────────────────
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/edge /edge
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/edge"]
