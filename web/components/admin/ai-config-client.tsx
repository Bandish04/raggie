// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { saveAiConfigAction } from "@/app/admin/ai/actions";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import Select from "@/components/ui/select";
import type { ModelsConfig } from "@/lib/api";
import { ui } from "@/lib/ui";

type ProviderModel = {
  id: string;
  provider: string;
  upstreamModel: string;
  capabilities: string[];
  available: boolean;
};

// The same-origin /api/admin/models route forwards canonical ids and, when the
// explicit registry is enabled, non-secret provider metadata. Keep compatibility
// with the legacy string-only response during rolling upgrades.
function parseProviderModels(data: unknown): ProviderModel[] {
  if (Array.isArray(data)) {
    return data
      .filter((x): x is string => typeof x === "string")
      .map((id) => ({
        id,
        provider: "default",
        upstreamModel: id,
        capabilities: [],
        available: true,
      }));
  }
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    if (Array.isArray(obj.profiles)) {
      const profiles = obj.profiles.flatMap((raw): ProviderModel[] => {
        if (!raw || typeof raw !== "object") return [];
        const profile = raw as Record<string, unknown>;
        if (typeof profile.id !== "string") return [];
        return [{
          id: profile.id,
          provider: typeof profile.provider === "string" ? profile.provider : "default",
          upstreamModel:
            typeof profile.upstream_model === "string" ? profile.upstream_model : profile.id,
          capabilities: Array.isArray(profile.capabilities)
            ? profile.capabilities.filter((x): x is string => typeof x === "string")
            : [],
          available: profile.available !== false,
        }];
      });
      if (profiles.length > 0) return profiles;
    }
    const list = obj.models ?? obj.allowed_models;
    if (Array.isArray(list)) {
      return list
        .filter((x): x is string => typeof x === "string")
        .map((id) => ({
          id,
          provider: "default",
          upstreamModel: id,
          capabilities: [],
          available: true,
        }));
    }
  }
  return [];
}

export default function AiConfigClient({ initial }: { initial: ModelsConfig }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();

  const [allowed, setAllowed] = useState<string[]>(initial.allowed_models ?? []);
  const [defaultModel, setDefaultModel] = useState<string>(initial.default_model ?? "");
  // Display aliases (model id -> friendly name). Kept as a full map; empty
  // values are dropped on save so the backend only stores real overrides.
  const [aliases, setAliases] = useState<Record<string, string>>(initial.aliases ?? {});
  const [draft, setDraft] = useState("");

  const [provider, setProvider] = useState<ProviderModel[] | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [fetching, startFetch] = useTransition();

  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [saving, startSave] = useTransition();

  function addModel(id: string) {
    const v = id.trim();
    if (!v || allowed.includes(v)) return;
    setAllowed((prev) => [...prev, v]);
  }
  function removeModel(id: string) {
    setAllowed((prev) => prev.filter((m) => m !== id));
    // A removed model can no longer be the default, nor carry an alias.
    if (defaultModel === id) setDefaultModel("");
    setAliases((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }
  function setAlias(id: string, name: string) {
    setAliases((prev) => ({ ...prev, [id]: name }));
  }
  function addDraft() {
    addModel(draft);
    setDraft("");
  }

  function fetchProviderModels() {
    setFetchError(false);
    startFetch(async () => {
      try {
        const res = await fetch("/api/admin/models", { cache: "no-store" });
        if (!res.ok) {
          setFetchError(true);
          return;
        }
        setProvider(parseProviderModels(await res.json()));
      } catch {
        setFetchError(true);
      }
    });
  }

  function save() {
    setSaved(false);
    setSaveError(false);
    startSave(async () => {
      // Only forward aliases for currently-allowed models, dropping blanks so
      // the backend stores real overrides only.
      const cleanedAliases: Record<string, string> = {};
      for (const id of allowed) {
        const name = aliases[id]?.trim();
        if (name) cleanedAliases[id] = name;
      }
      const res = await saveAiConfigAction({
        default_model: defaultModel || null,
        allowed_models: allowed,
        aliases: cleanedAliases,
      });
      if (res.ok) {
        setSaved(true);
        router.refresh();
      } else {
        setSaveError(true);
      }
    });
  }

  // The default must be choosable; offer the curated allow-list, or "none".
  const defaultOptions = [
    { value: "", label: t("aiDefaultNone") },
    ...allowed.map((m) => ({ value: m, label: m })),
  ];

  return (
    <div className="space-y-6">
      {/* On-prem / KVKK note: only model selection is managed here. */}
      <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-2/60 p-4 text-sm text-ink-muted">
        <Icon name="shield" size={20} className="mt-0.5 shrink-0 text-ink-muted" />
        <p>{t("aiServerHint")}</p>
      </div>

      {/* Two intentional columns on wide screens: the curated allow-list (the
          tallest, most-edited surface) on the left; the default-model picker and
          the provider fetch stacked on the right. */}
      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        {/* Allowed models */}
        <Card>
          <CardHeader>
            <CardTitle>{t("aiAllowedModels")}</CardTitle>
          </CardHeader>
          <CardBody className="space-y-4">
          <p className="text-sm text-ink-muted">{t("aiAllowedModelsHint")}</p>

          {allowed.length === 0 ? (
            <EmptyState icon="robot_2" title={t("aiNoAllowed")} description={t("aiNoAllowedHint")} />
          ) : (
            <ul className="space-y-2">
              {allowed.map((m) => (
                <li
                  key={m}
                  className="flex flex-wrap items-center gap-2 rounded-2xl bg-surface-2 px-3 py-2"
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{m}</span>
                  <input
                    value={aliases[m] ?? ""}
                    onChange={(e) => setAlias(m, e.target.value)}
                    placeholder={t("aiAlias")}
                    aria-label={`${t("aiAlias")} — ${m}`}
                    className={`${ui.input} h-9 w-full sm:w-48`}
                  />
                  <button
                    type="button"
                    onClick={() => removeModel(m)}
                    aria-label={`${t("remove")} ${m}`}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-ink-muted transition hover:bg-surface-3 hover:text-ink"
                  >
                    <Icon name="close" size={16} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {allowed.length > 0 && <p className="text-xs text-ink-muted">{t("aiAliasHint")}</p>}

          {/* Manual add */}
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1 space-y-1.5">
              <label htmlFor="ai-add" className={ui.label}>
                {t("aiAddModel")}
              </label>
              <input
                id="ai-add"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addDraft();
                  }
                }}
                placeholder={t("aiModelPlaceholder")}
                className={`${ui.input} max-w-sm`}
              />
            </div>
            <Button variant="ghost" onClick={addDraft} disabled={!draft.trim()}>
              <Icon name="add" size={18} />
              {t("aiAddModel")}
            </Button>
          </div>
          </CardBody>
        </Card>

        {/* Right column: the default-model picker over the provider fetch. */}
        <div className="space-y-6">
          {/* Default model */}
          <Card>
            <CardHeader>
              <CardTitle>{t("aiDefaultModel")}</CardTitle>
            </CardHeader>
            <CardBody className="space-y-3">
              <p className="text-sm text-ink-muted">{t("aiDefaultModelHint")}</p>
              <Select
                options={defaultOptions}
                value={defaultModel}
                onValueChange={setDefaultModel}
                ariaLabel={t("aiDefaultModel")}
                className="max-w-sm"
              />
            </CardBody>
          </Card>

          {/* Fetch from provider */}
          <Card>
            <CardHeader>
              <CardTitle>{t("aiProviderModels")}</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <p className="text-sm text-ink-muted">{t("aiFetchModelsHint")}</p>
              <div className="flex items-center gap-3">
                <Button variant="ghost" onClick={fetchProviderModels} disabled={fetching}>
                  <Icon name="cloud_download" size={18} />
                  {fetching ? tc("loading") : t("aiFetchModels")}
                </Button>
                {fetchError && <span className="text-sm text-danger">{t("aiFetchFailed")}</span>}
              </div>

              {provider !== null &&
                (provider.length === 0 ? (
                  <p className="text-sm text-ink-muted">{t("aiNoProviderModels")}</p>
                ) : (
                  <ul className="flex flex-wrap gap-2">
                    {provider.map((model) => {
                      const added = allowed.includes(model.id);
                      return (
                        <li key={model.id}>
                          <button
                            type="button"
                            onClick={() => addModel(model.id)}
                            disabled={added || !model.available}
                            title={`${model.provider} / ${model.upstreamModel}`}
                            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1 text-sm text-ink transition hover:bg-surface-2 disabled:cursor-default disabled:opacity-50"
                          >
                            <Icon name={added ? "check" : "add"} size={14} />
                            {model.id}
                            <span className="text-xs text-ink-muted">{model.provider}</span>
                            {model.capabilities.map((capability) => (
                              <span
                                key={capability}
                                className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-muted"
                              >
                                {capability}
                              </span>
                            ))}
                            {!model.available && (
                              <span className="text-xs text-danger">offline</span>
                            )}
                            {added && <span className="text-xs text-ink-muted">{t("aiAlreadyAdded")}</span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ))}
            </CardBody>
          </Card>
        </div>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={saving}>
          {saving ? tc("loading") : t("aiSave")}
        </Button>
        {saved && <span className="text-sm text-success">{t("aiSaved")}</span>}
        {saveError && <span className="text-sm text-danger">{t("saveFailed")}</span>}
      </div>
    </div>
  );
}
