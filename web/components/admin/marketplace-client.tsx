// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import {
  connectIntegrationAction,
  disconnectIntegrationAction,
} from "@/app/admin/integrations/actions";
import MCPCapabilitiesModal from "@/components/admin/mcp-capabilities-modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Modal } from "@/components/ui/modal";
import Select from "@/components/ui/select";
import type { IntegrationProvider, IntegrationRow, WorkspaceRow } from "@/lib/api";
import { ui } from "@/lib/ui";

// A provider's connect scope. The backend is adding an explicit `scope` field;
// until every provider carries it, fall back to category (MCP/tools = org).
function scopeOf(p: IntegrationProvider): "org" | "workspace" {
  if (p.scope) return p.scope;
  return (p.category ?? "other") === "mcp" ? "org" : "workspace";
}

// The connect dialog: scope-aware. Org providers hide the workspace picker and
// submit without one; workspace providers require it.
function ConnectModal({
  open,
  onClose,
  providers,
  workspaces,
  initialProvider,
}: {
  open: boolean;
  onClose: () => void;
  providers: IntegrationProvider[];
  workspaces: WorkspaceRow[];
  initialProvider: string;
}) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();

  const [providerKey, setProviderKey] = useState(initialProvider);
  const [wsId, setWsId] = useState(workspaces[0]?.id ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState(false);
  const [pending, start] = useTransition();

  const provider = providers.find((p) => p.key === providerKey);
  const isOrg = provider ? scopeOf(provider) === "org" : false;
  // Workspace providers need a workspace; org providers never do.
  const ready = Boolean(provider) && (isOrg || Boolean(wsId));

  function submit() {
    if (!provider || !ready) return;
    const credentials: Record<string, string> = {};
    const config: Record<string, string> = {};
    for (const f of provider.fields) {
      const v = values[f.key] ?? "";
      if (!v) continue;
      if (f.secret) credentials[f.key] = v;
      else config[f.key] = v;
    }
    start(async () => {
      const res = await connectIntegrationAction({
        provider: provider.key,
        // Omit the workspace for org-scoped providers.
        workspaceId: isOrg ? undefined : wsId,
        credentials,
        config,
      });
      if (res.ok) {
        onClose();
        router.refresh();
      } else {
        setError(true);
      }
    });
  }

  return (
    <Modal open={open} onClose={onClose} title={t("integrationsConnectTitle")}>
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label className={ui.label}>{t("integrationsProvider")}</label>
          <Select
            ariaLabel={t("integrationsProvider")}
            value={providerKey}
            onValueChange={(v) => {
              setProviderKey(v);
              setValues({});
              setError(false);
            }}
            options={providers.map((p) => ({
              value: p.key,
              label: p.label,
              icon: p.icon ?? "extension",
            }))}
          />
          {provider?.description && (
            <p className="text-xs text-ink-muted">{provider.description}</p>
          )}
        </div>

        {isOrg ? (
          <p className="text-xs text-ink-muted">{t("mktOrgNote")}</p>
        ) : (
          <div className="space-y-1.5">
            <label className={ui.label}>{t("chooseWorkspace")}</label>
            <Select
              ariaLabel={t("chooseWorkspace")}
              value={wsId}
              onValueChange={setWsId}
              options={workspaces.map((w) => ({ value: w.id, label: w.name, icon: "workspaces" }))}
            />
          </div>
        )}

        {provider?.fields.map((f) => (
          <div key={f.key} className="space-y-1.5">
            <label htmlFor={`int-${f.key}`} className={ui.label}>
              {f.label}
            </label>
            <input
              id={`int-${f.key}`}
              type={f.secret ? "password" : "text"}
              value={values[f.key] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              className={ui.input}
            />
          </div>
        ))}

        {provider?.auth === "oauth" && (
          <p className="text-xs text-ink-muted">{t("integrationsOauthNote")}</p>
        )}
        {error && <p className="text-sm text-danger">{t("saveFailed")}</p>}

        <div className="flex items-center justify-end gap-3 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button type="button" onClick={submit} disabled={pending || !ready}>
            {pending ? tc("loading") : t("integrationsConnect")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// One provider tile in the grid.
function ProviderCard({
  p,
  connection,
  canConnect,
  onInstall,
  onRemove,
  onDetails,
  removing,
}: {
  p: IntegrationProvider;
  connection?: IntegrationRow;
  canConnect: boolean;
  onInstall: () => void;
  // Omitted when the viewer may not remove this connection (org scope, non platform admin).
  onRemove?: (id: string) => void;
  // Opens the MCP capability detail modal. Only wired for connected MCP providers.
  onDetails?: () => void;
  removing: boolean;
}) {
  const t = useTranslations("admin");
  const scope = scopeOf(p);
  const connected = Boolean(connection);
  // The capability probe only exists for MCP servers (live tools/list + health).
  const isMcp = (p.category ?? "other") === "mcp";

  return (
    <div className="card-hover flex flex-col gap-3.5 rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand/10 text-brand">
          <Icon name={p.icon ?? "extension"} size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium text-ink">{p.label}</div>
          <Badge tone="neutral" className="mt-1">
            <Icon name={scope === "org" ? "corporate_fare" : "workspaces"} size={12} />
            {scope === "org" ? t("mktScopeOrg") : t("mktScopeWorkspace")}
          </Badge>
        </div>
      </div>

      <p className="line-clamp-2 min-h-[2.5rem] text-sm text-ink-muted">{p.description}</p>

      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        {connected ? (
          <>
            <Badge tone="success">
              <Icon name="check_circle" size={13} />
              {t("mktConnected")}
            </Badge>
            <div className="flex items-center gap-1">
              {isMcp && onDetails && (
                <Button variant="subtle" size="sm" onClick={onDetails}>
                  <Icon name="monitor_heart" size={16} />
                  {t("mktDetails")}
                </Button>
              )}
              {onRemove && (
                <Button
                  variant="subtle"
                  size="sm"
                  disabled={removing}
                  onClick={() => connection && onRemove(connection.id)}
                >
                  <Icon name="link_off" size={16} />
                  {t("mktRemove")}
                </Button>
              )}
            </div>
          </>
        ) : (
          <>
            <Button size="sm" onClick={onInstall} disabled={!canConnect}>
              <Icon name="add_link" size={16} />
              {t("mktInstall")}
            </Button>
            {!canConnect && (
              <span className="text-xs text-ink-muted">{t("mktSuperAdminRequired")}</span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  icon,
  heading,
  hint,
  children,
}: {
  icon: string;
  heading: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <div className="flex items-center gap-2 text-ink">
          <Icon name={icon} size={18} className="text-brand" />
          <h2 className="font-display text-base font-semibold tracking-tight">{heading}</h2>
        </div>
        <p className="mt-1 text-sm text-ink-muted">{hint}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
    </section>
  );
}

export default function MarketplaceClient({
  providers,
  integrations,
  workspaces,
  platformAdmin,
}: {
  providers: IntegrationProvider[];
  integrations: IntegrationRow[];
  workspaces: WorkspaceRow[];
  // Org-scoped (operator MCP) integrations front the operator's deploy-time
  // credentials: only a platform admin may connect or remove them.
  platformAdmin: boolean;
}) {
  const t = useTranslations("admin");
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [connectProvider, setConnectProvider] = useState<string | null>(null);
  // The connected MCP provider whose capability detail modal is open (or null).
  const [detailsProvider, setDetailsProvider] = useState<IntegrationProvider | null>(null);
  const [removing, start] = useTransition();

  // First connection per provider key (drives the connected badge + remove).
  const connectionByProvider = useMemo(() => {
    const m = new Map<string, IntegrationRow>();
    for (const i of integrations) if (!m.has(i.provider)) m.set(i.provider, i);
    return m;
  }, [integrations]);

  function canConnect(p: IntegrationProvider): boolean {
    // Org-scoped connects are platform-admin-only; workspace connects need a workspace.
    if (scopeOf(p) === "org") return platformAdmin;
    return workspaces.length > 0;
  }

  function remove(id: string) {
    start(async () => {
      await disconnectIntegrationAction(id);
      router.refresh();
    });
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return providers;
    return providers.filter(
      (p) =>
        p.label.toLowerCase().includes(q) ||
        (p.description ?? "").toLowerCase().includes(q),
    );
  }, [providers, query]);

  // Tools & MCP first (the featured, org-wide path), then workspace data sources.
  const tools = filtered.filter((p) => (p.category ?? "other") === "mcp");
  const sources = filtered.filter((p) => (p.category ?? "other") !== "mcp");
  const connectedCount = connectionByProvider.size;

  const renderCard = (p: IntegrationProvider) => (
    <ProviderCard
      key={p.key}
      p={p}
      connection={connectionByProvider.get(p.key)}
      canConnect={canConnect(p)}
      onInstall={() => setConnectProvider(p.key)}
      onRemove={scopeOf(p) === "org" && !platformAdmin ? undefined : remove}
      onDetails={() => setDetailsProvider(p)}
      removing={removing}
    />
  );

  return (
    <div className="space-y-8">
      {/* Toolbar: connected summary + search. */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {connectedCount > 0 ? (
          <Badge tone="brand">
            <Icon name="check_circle" size={13} />
            {t("mktConnectedCount", { count: connectedCount })}
          </Badge>
        ) : (
          <span className="text-sm text-ink-muted">{t("mktIntro")}</span>
        )}
        <div className="relative w-full sm:max-w-xs">
          <Icon
            name="search"
            size={18}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("mktSearchPlaceholder")}
            aria-label={t("mktSearchPlaceholder")}
            className={`${ui.input} pl-10`}
          />
        </div>
      </div>

      {tools.length === 0 && sources.length === 0 ? (
        <p className="rounded-2xl border border-border bg-surface px-4 py-8 text-center text-sm text-ink-muted">
          {t("mktSearchEmpty")}
        </p>
      ) : (
        <>
          {tools.length > 0 && (
            <Section icon="hub" heading={t("mktToolsHeading")} hint={t("mktToolsHint")}>
              {tools.map(renderCard)}
            </Section>
          )}
          {sources.length > 0 && (
            <Section
              icon="database"
              heading={t("mktSourcesHeading")}
              hint={t("mktSourcesHint")}
            >
              {sources.map(renderCard)}
            </Section>
          )}
        </>
      )}

      {connectProvider && (
        <ConnectModal
          open
          onClose={() => setConnectProvider(null)}
          providers={providers}
          workspaces={workspaces}
          initialProvider={connectProvider}
        />
      )}

      {detailsProvider && (
        <MCPCapabilitiesModal
          provider={detailsProvider.key}
          label={detailsProvider.label}
          onClose={() => setDetailsProvider(null)}
        />
      )}
    </div>
  );
}
