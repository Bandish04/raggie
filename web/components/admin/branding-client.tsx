// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Icon } from "@/components/ui/icon";
import type { Branding } from "@/lib/api";
import { ui } from "@/lib/ui";

export default function BrandingClient({ initial }: { initial: Branding }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const router = useRouter();
  const [name, setName] = useState(initial.name);
  const [tagline, setTagline] = useState(initial.tagline ?? "");
  const [color, setColor] = useState(initial.color);
  const [logo, setLogo] = useState(initial.logo_data_url);
  const [icon, setIcon] = useState(initial.icon_data_url);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(false);
  const [pending, start] = useTransition();
  const logoRef = useRef<HTMLInputElement>(null);
  const iconRef = useRef<HTMLInputElement>(null);

  function saveText() {
    setSaved(false);
    setError(false);
    start(async () => {
      const res = await fetch("/api/admin/branding", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, tagline, color }),
      });
      if (res.ok) {
        setSaved(true);
        router.refresh(); // re-render layout with the new brand color/name
      } else {
        setError(true);
      }
    });
  }

  function upload(kind: "logo" | "icon", file: File | undefined) {
    if (!file) return;
    setError(false);
    start(async () => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/admin/branding/${kind}`, { method: "POST", body: fd });
      if (res.ok) {
        const b = (await res.json()) as Branding;
        if (kind === "logo") setLogo(b.logo_data_url);
        else setIcon(b.icon_data_url);
        router.refresh();
      } else {
        setError(true);
      }
    });
  }

  const brandName = name || "Raggie";
  const previewMark = logo || icon;

  return (
    <div className="space-y-6">
      {/* What branding controls. */}
      <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-2/60 p-4 text-sm text-ink-muted">
        <Icon name="palette" size={20} className="mt-0.5 shrink-0 text-brand" />
        <p>{t("brandingHint")}</p>
      </div>

      {/* Two intentional columns on wide screens: the live preview over the
          identity form (left) and the image uploads (right). */}
      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <div className="space-y-6">
      {/* Live preview: name + accent swatch + logo, the way users see it. */}
      <Card>
        <CardHeader>
          <CardTitle>{t("brandingPreview")}</CardTitle>
        </CardHeader>
        <CardBody>
          <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-border bg-surface-2/40 p-5">
            {previewMark ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewMark}
                alt={brandName}
                className="h-12 w-12 shrink-0 rounded-full object-contain"
              />
            ) : (
              <span
                className="grid h-12 w-12 shrink-0 place-items-center rounded-full text-white"
                style={{ background: color }}
              >
                <Icon name="pets" size={24} fill />
              </span>
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate font-display text-xl font-semibold text-ink">{brandName}</div>
              {tagline && <div className="mt-0.5 truncate text-sm text-ink-muted">{tagline}</div>}
            </div>
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-6 w-6 rounded-full border border-border"
                style={{ background: color }}
              />
              <span className="font-mono text-xs uppercase text-ink-muted">{color}</span>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Identity: name, tagline, accent color. */}
      <Card>
        <CardHeader>
          <CardTitle>{t("brandingIdentity")}</CardTitle>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="b-name" className={ui.label}>
              {t("brandingName")}
            </label>
            <input
              id="b-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={ui.input}
              placeholder={t("brandingNamePlaceholder")}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="b-tag" className={ui.label}>
              {t("brandingTagline")}
            </label>
            <input
              id="b-tag"
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              className={ui.input}
              placeholder={t("brandingTaglinePlaceholder")}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="b-color" className={ui.label}>
              {t("brandingColor")}
            </label>
            <div className="flex items-center gap-3">
              <input
                id="b-color"
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="h-10 w-14 cursor-pointer rounded-lg border border-border bg-surface"
              />
              <input
                value={color}
                onChange={(e) => setColor(e.target.value)}
                aria-label={t("brandingColor")}
                className={`${ui.input} max-w-[10rem] font-mono`}
              />
            </div>
            <p className="text-xs text-ink-muted">{t("brandingColorHelp")}</p>
          </div>

          <div className="flex items-center gap-3 pt-1">
            <Button onClick={saveText} disabled={pending}>
              {pending ? tc("loading") : t("brandingSave")}
            </Button>
            {saved && (
              <span className="inline-flex items-center gap-1.5 text-sm text-success">
                <Icon name="check_circle" size={18} />
                {t("brandingSaved")}
              </span>
            )}
            {error && (
              <span className="inline-flex items-center gap-1.5 text-sm text-danger">
                <Icon name="error" size={18} />
                {t("saveFailed")}
              </span>
            )}
          </div>
        </CardBody>
      </Card>
        </div>

      {/* Images: logo + icon uploads with previews. */}
      <Card>
        <CardHeader>
          <CardTitle>{t("brandingImages")}</CardTitle>
        </CardHeader>
        <CardBody className="space-y-4">
          <p className="text-sm text-ink-muted">{t("brandingImagesHint")}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 rounded-2xl border border-border bg-surface p-4">
              <span className={ui.label}>{t("brandingLogo")}</span>
              <div className="flex items-center gap-3">
                {logo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={logo} alt={t("brandingLogo")} className="h-12 w-12 rounded-full object-contain" />
                ) : (
                  <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-muted">
                    <Icon name="image" size={22} />
                  </span>
                )}
                <input
                  ref={logoRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(e) => upload("logo", e.target.files?.[0])}
                />
                <Button variant="ghost" size="sm" disabled={pending} onClick={() => logoRef.current?.click()}>
                  <Icon name="upload" size={16} />
                  {logo ? t("brandingReplace") : t("brandingUpload")}
                </Button>
              </div>
            </div>

            <div className="space-y-2 rounded-2xl border border-border bg-surface p-4">
              <span className={ui.label}>{t("brandingIcon")}</span>
              <div className="flex items-center gap-3">
                {icon ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={icon} alt={t("brandingIcon")} className="h-12 w-12 rounded-full object-contain" />
                ) : (
                  <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-muted">
                    <Icon name="favicon" size={22} />
                  </span>
                )}
                <input
                  ref={iconRef}
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(e) => upload("icon", e.target.files?.[0])}
                />
                <Button variant="ghost" size="sm" disabled={pending} onClick={() => iconRef.current?.click()}>
                  <Icon name="upload" size={16} />
                  {icon ? t("brandingReplace") : t("brandingUpload")}
                </Button>
              </div>
            </div>
          </div>
        </CardBody>
      </Card>
      </div>
    </div>
  );
}
