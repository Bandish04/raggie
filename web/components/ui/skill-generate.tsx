// SPDX-License-Identifier: Apache-2.0

"use client";

// Shared "✨ AI ile oluştur" affordance for the skill modals. A one-line input
// ("what should it do?") + a generate button that POSTs { description } to the
// same-origin /api/skills/generate route and fills the instructions textarea
// with the returned text. The button shows a loading state; a small friendly
// message surfaces on error. Manual editing of the textarea is never blocked.

import { useState } from "react";

import { Icon } from "@/components/ui/icon";

type GenerateResponse = { instructions?: string; error?: string; message?: string };

export default function SkillGenerate({
  // Falls back to the skill name when the description input is empty.
  fallback,
  onGenerated,
  label,
  placeholder,
  generatingLabel,
  errorLabel,
}: {
  fallback: string;
  onGenerated: (instructions: string) => void;
  label: string;
  placeholder: string;
  generatingLabel: string;
  errorLabel: string;
}) {
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  async function generate() {
    if (loading) return;
    const desc = description.trim() || fallback.trim();
    if (!desc) return;
    setLoading(true);
    setError(false);
    try {
      const res = await fetch("/api/skills/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: desc }),
      });
      const data = (await res.json()) as GenerateResponse;
      if (res.ok && typeof data.instructions === "string" && data.instructions.trim()) {
        onGenerated(data.instructions);
      } else {
        setError(true);
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface-2/50 p-2.5">
      <div className="flex items-center gap-2">
        <Icon name="auto_awesome" size={18} className="shrink-0 text-brand" />
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void generate();
            }
          }}
          disabled={loading}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-muted/60 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => void generate()}
          disabled={loading}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand/10 px-2.5 py-1.5 text-xs font-medium text-brand-strong outline-none transition hover:bg-brand/20 focus-visible:ring-2 focus-visible:ring-brand/30 disabled:opacity-60"
        >
          <Icon
            name={loading ? "progress_activity" : "auto_awesome"}
            size={16}
            className={loading ? "animate-spin" : ""}
          />
          {loading ? generatingLabel : label}
        </button>
      </div>
      {error && (
        <p className="mt-1.5 pl-6 text-xs text-danger" role="alert">
          {errorLabel}
        </p>
      )}
    </div>
  );
}
