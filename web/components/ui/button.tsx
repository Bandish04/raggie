// SPDX-License-Identifier: Apache-2.0

import * as React from "react";

type Variant = "primary" | "ghost" | "outline" | "danger" | "subtle";
type Size = "sm" | "md" | "lg" | "icon";

const base =
  "inline-flex items-center justify-center gap-2 rounded-full font-medium transition active:scale-[0.98] disabled:opacity-40 disabled:active:scale-100 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  primary: "bg-brand text-brand-contrast hover:bg-brand-strong font-semibold",
  ghost: "border border-border bg-surface-2 text-ink hover:bg-surface-3",
  outline: "border border-border bg-surface text-ink hover:bg-surface-2",
  danger: "bg-danger text-white hover:opacity-90 font-semibold",
  subtle: "text-ink-muted hover:bg-surface-2 hover:text-ink",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3.5 text-sm",
  md: "h-10 px-5 text-sm",
  lg: "h-12 px-6 text-base",
  icon: "h-9 w-9",
};

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
};

/** The one button. Pill-shaped, System-Blue primary; variants + sizes for the rest. */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", className = "", type, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    />
  );
});
