// SPDX-License-Identifier: Apache-2.0

"use client";

import * as React from "react";
import { createPortal } from "react-dom";

type DrawerProps = {
  open: boolean;
  onClose: () => void;
  side?: "left" | "right";
  children: React.ReactNode;
  className?: string;
};

/** Mobile slide-in panel (used for nav on small screens). md:hidden by design. */
export function Drawer({ open, onClose, side = "left", children, className = "" }: DrawerProps) {
  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;
  const sideCls = side === "left" ? "left-0" : "right-0";

  return createPortal(
    <div className="fixed inset-0 z-50 md:hidden">
      <div className="absolute inset-0 bg-ink/30 backdrop-blur-[2px]" onClick={onClose} />
      <div className={`absolute top-0 ${sideCls} h-full w-[82%] max-w-xs bg-surface shadow-lift ${className}`}>
        {children}
      </div>
    </div>,
    document.body,
  );
}
