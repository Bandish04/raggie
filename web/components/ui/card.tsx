// SPDX-License-Identifier: Apache-2.0

import * as React from "react";

/**
 * Calm surface container. The shared building block for every panel in the app.
 * Composes with the .card class (border + radius + soft shadow) from globals.css.
 */
export function Card({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`} {...props} />;
}

export function CardHeader({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`flex items-start justify-between gap-4 px-5 pt-5 ${className}`} {...props} />;
}

export function CardTitle({ className = "", ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={`font-display text-base font-semibold tracking-tight text-ink ${className}`} {...props} />
  );
}

export function CardDescription({ className = "", ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={`mt-1 text-sm text-ink-muted ${className}`} {...props} />;
}

export function CardBody({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`p-5 ${className}`} {...props} />;
}

export function CardFooter({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`flex items-center gap-3 border-t border-border px-5 py-4 ${className}`} {...props} />
  );
}
