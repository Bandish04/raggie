// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import UpdateCommand from "@/components/admin/update-command";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Icon } from "@/components/ui/icon";
import type { UpdateStatus } from "@/lib/api";
import { safeHttpsHref } from "@/lib/security/url";

// Presentation + the "check for updates" action. The web app never executes
// anything on the host; checking just re-runs the server-side fetch.
export default function UpdatesClient({ status }: { status: UpdateStatus | null }) {
  const t = useTranslations("admin");
  // release_url comes from a remote manifest: link it only when it is https.
  const releaseHref = status ? safeHttpsHref(status.release_url) : null;
  const tc = useTranslations("common");
  const router = useRouter();
  const [checking, startCheck] = useTransition();

  function check() {
    startCheck(() => router.refresh());
  }

  const checkButton = (
    <Button variant="ghost" onClick={check} disabled={checking}>
      <Icon name="refresh" size={18} className={checking ? "animate-spin" : undefined} />
      {checking ? tc("loading") : t("updatesCheckNow")}
    </Button>
  );

  // The host couldn't reach the update server at all.
  if (!status) {
    return (
      <EmptyState
        icon="cloud_off"
        title={t("updatesErrorTitle")}
        description={t("updatesErrorHint")}
        action={checkButton}
      />
    );
  }

  const available = status.update_available;
  const current = status.current_version || t("updatesUnknown");
  const latest = status.latest_version || t("updatesUnknown");

  return (
    <div
      className={`grid gap-6 lg:items-start ${available ? "lg:grid-cols-2" : ""}`}
    >
      {/* Version summary + status badge. */}
      <Card>
        <CardBody className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="grid grid-cols-2 gap-x-10 gap-y-1">
              <div>
                <div className="text-xs uppercase tracking-wide text-ink-muted">{t("updatesCurrent")}</div>
                <div className="font-display text-2xl font-semibold text-ink">v{current}</div>
              </div>
              {status.checked && (
                <div>
                  <div className="text-xs uppercase tracking-wide text-ink-muted">{t("updatesLatest")}</div>
                  <div className="font-display text-2xl font-semibold text-ink">v{latest}</div>
                </div>
              )}
            </div>
            {available ? (
              <Badge tone="brand">
                <Icon name="upgrade" size={16} />
                {t("updatesAvailable")}
              </Badge>
            ) : status.checked ? (
              <Badge tone="success">
                <Icon name="check_circle" size={16} />
                {t("updatesUpToDate")}
              </Badge>
            ) : (
              <Badge tone="neutral">{t("updatesNotConfigured")}</Badge>
            )}
          </div>

          {!available && status.checked && (
            <p className="text-sm text-ink-muted">{t("updatesUpToDateHint")}</p>
          )}

          <div className="flex items-center gap-3 border-t border-border pt-4">{checkButton}</div>
        </CardBody>
      </Card>

      {/* Release notes + the command to run, only when there's an update. */}
      {available && (
        <Card>
          <CardHeader>
            <CardTitle>{t("updatesHowTo")}</CardTitle>
          </CardHeader>
          <CardBody className="space-y-5">
            {status.notes && (
              <div className="space-y-1.5">
                <div className="text-sm font-medium text-ink">{t("updatesChangelog")}</div>
                <p className="whitespace-pre-wrap text-sm text-ink-muted">{status.notes}</p>
              </div>
            )}

            <div className="space-y-2">
              <p className="text-sm text-ink-muted">{t("updatesHowToHint")}</p>
              <UpdateCommand command={status.update_command} />
            </div>

            {releaseHref ? (
              <a
                href={releaseHref}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline"
              >
                <Icon name="open_in_new" size={16} />
                {t("updatesReleaseNotes")}
              </a>
            ) : status.release_url ? (
              // Rejected (non-https) URL: shown as inert text, never a link.
              <p className="break-all text-sm text-ink-muted">{status.release_url}</p>
            ) : null}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
