// SPDX-License-Identifier: Apache-2.0

"use client";

import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";

// Mirrors the pinned edge capabilities contract. Inlined (not imported from the
// server-only lib/api) because this is a client component.
type MCPToolSpec = { name: string; description: string };
type MCPCapabilities = {
  enabled: boolean;
  status: "ok" | "error" | "disabled";
  protocol_version: string;
  latency_ms: number;
  checked_at: string; // ISO8601
  tools: MCPToolSpec[];
};

// Map the probe status to a calm health badge tone + label.
function healthTone(status: MCPCapabilities["status"]): "success" | "danger" | "neutral" {
  if (status === "ok") return "success";
  if (status === "error") return "danger";
  return "neutral";
}

// A detail modal for one connected MCP provider: health, protocol version,
// latency, last-checked, and the live tool list (kapabiliteler). Re-probes on
// demand. The edge endpoint is fail-soft, so a non-ok status is a normal,
// non-error render (the disabled / error split is shown honestly).
export default function MCPCapabilitiesModal({
  provider,
  label,
  onClose,
}: {
  provider: string;
  label: string;
  onClose: () => void;
}) {
  const t = useTranslations("admin");
  const locale = useLocale();
  const [data, setData] = useState<MCPCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchCapabilities = useCallback(async (signal?: AbortSignal) => {
    const res = await fetch(`/api/admin/mcp/capabilities?provider=${encodeURIComponent(provider)}`, {
      cache: "no-store",
      signal,
    });
    if (!res.ok) return null;
    return (await res.json()) as MCPCapabilities;
  }, [provider]);

  const probe = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const next = await fetchCapabilities();
      if (!next) {
        setError(true);
        return;
      }
      setData(next);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [fetchCapabilities]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadInitial() {
      try {
        const next = await fetchCapabilities(controller.signal);
        if (controller.signal.aborted) return;
        if (!next) {
          setError(true);
          return;
        }
        setData(next);
      } catch {
        if (!controller.signal.aborted) setError(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void loadInitial();
    return () => controller.abort();
  }, [fetchCapabilities]);

  const healthLabel = (status: MCPCapabilities["status"]) =>
    status === "ok"
      ? t("mcpHealthOk")
      : status === "error"
        ? t("mcpHealthError")
        : t("mcpHealthDisabled");

  const checkedAt = data?.checked_at
    ? new Date(data.checked_at).toLocaleString(locale)
    : "—";

  return (
    <Modal
      open
      onClose={onClose}
      title={t("mcpDetailTitle", { name: label })}
      description={t("mcpDetailSubtitle")}
      size="lg"
      footer={
        <Button variant="outline" onClick={() => void probe()} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? t("mcpRechecking") : t("mcpRecheck")}
        </Button>
      }
    >
      {error ? (
        <p className="rounded-2xl border border-border bg-surface-2 px-4 py-6 text-center text-sm text-ink-muted">
          {t("mcpProbeError")}
        </p>
      ) : loading && !data ? (
        <p className="px-1 py-6 text-center text-sm text-ink-muted">{t("mcpProbing")}</p>
      ) : data ? (
        <div className="space-y-5">
          {/* Health + key facts row. */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-border bg-surface-2 px-4 py-3">
              <div className="text-xs text-ink-muted">{t("mcpHealth")}</div>
              <div className="mt-1.5">
                <Badge tone={healthTone(data.status)} dot>
                  {healthLabel(data.status)}
                </Badge>
              </div>
            </div>
            <div className="rounded-2xl border border-border bg-surface-2 px-4 py-3">
              <div className="text-xs text-ink-muted">{t("mcpVersion")}</div>
              <div className="mt-1.5 font-mono text-sm text-ink">
                {data.protocol_version || "—"}
              </div>
            </div>
            <div className="rounded-2xl border border-border bg-surface-2 px-4 py-3">
              <div className="text-xs text-ink-muted">{t("mcpLatency")}</div>
              <div className="mt-1.5 text-sm text-ink">
                {t("mcpLatencyValue", { ms: data.latency_ms })}
              </div>
            </div>
            <div className="rounded-2xl border border-border bg-surface-2 px-4 py-3">
              <div className="text-xs text-ink-muted">{t("mcpCheckedAt")}</div>
              <div className="mt-1.5 text-sm text-ink">{checkedAt}</div>
            </div>
          </div>

          {/* Live tool list (kapabiliteler). */}
          <div>
            <div className="mb-2 flex items-center gap-2 text-ink">
              <Icon name="build" size={16} className="text-brand" />
              <h3 className="text-sm font-semibold">
                {t("mcpToolsHeading", { count: data.tools.length })}
              </h3>
            </div>
            {data.tools.length === 0 ? (
              <p className="rounded-2xl border border-border bg-surface-2 px-4 py-5 text-center text-sm text-ink-muted">
                {t("mcpToolsEmpty")}
              </p>
            ) : (
              <ul className="scrollbar-slim max-h-72 space-y-2 overflow-y-auto pr-1">
                {data.tools.map((tool) => (
                  <li
                    key={tool.name}
                    className="rounded-2xl border border-border bg-surface px-4 py-3"
                  >
                    <div className="font-mono text-sm text-ink">{tool.name}</div>
                    {tool.description && (
                      <p className="mt-1 text-sm text-ink-muted">{tool.description}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
