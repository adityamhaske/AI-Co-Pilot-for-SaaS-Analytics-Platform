import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The small set of primitives the app is built from.
 *
 * Kept deliberately few: one button with four variants beats six bespoke buttons.
 * Every one carries a visible focus ring and an accessible name.
 */

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-ink hover:bg-accent-hover disabled:bg-surface-active disabled:text-ink-muted",
  secondary:
    "bg-surface text-ink border border-line hover:bg-surface-hover disabled:text-ink-muted",
  ghost: "text-ink-secondary hover:bg-surface-hover hover:text-ink",
  danger: "bg-danger text-ink-inverse hover:opacity-90",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-5 text-base gap-2",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "secondary", size = "md", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium",
        "transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:opacity-60",
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      {...props}
    />
  )
);
Button.displayName = "Button";

// ---------------------------------------------------------------------------
// IconButton — an icon alone is never self-describing, so a label is required.
// ---------------------------------------------------------------------------

export interface IconButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: "sm" | "md";
}

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, label, size = "md", type = "button", children, ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md",
        "text-ink-muted transition-colors duration-150",
        "hover:bg-surface-hover hover:text-ink",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 w-7" : "h-9 w-9",
        className
      )}
      {...props}
    >
      {children}
    </button>
  )
);
IconButton.displayName = "IconButton";

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "w-full rounded-md border border-line bg-surface px-3 py-2 text-base text-ink",
      "placeholder:text-ink-muted",
      "transition-colors duration-150",
      "hover:border-line-strong",
      "focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent",
      "disabled:cursor-not-allowed disabled:bg-surface-hover disabled:text-ink-muted",
      className
    )}
    {...props}
  />
));
Input.displayName = "Input";

// ---------------------------------------------------------------------------
// Field — label, control and error bound together so the association is never missed
// ---------------------------------------------------------------------------

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-ink-secondary">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-ink-muted">{hint}</p>}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("animate-spin", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
      />
      <path
        className="opacity-90"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z"
      />
    </svg>
  );
}

export function Banner({
  tone = "danger",
  children,
  onDismiss,
}: {
  tone?: "danger" | "info";
  children: React.ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-md border px-3 py-2.5 text-sm",
        tone === "danger"
          ? "border-danger/30 bg-danger-subtle text-danger"
          : "border-line bg-surface-hover text-ink-secondary"
      )}
    >
      <span className="flex-1">{children}</span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-xs underline underline-offset-2 hover:opacity-80"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

/** A neutral placeholder while real content loads. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded bg-surface-active", className)}
    />
  );
}

export function Badge({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-line px-2 py-0.5",
        "text-2xs font-medium uppercase tracking-wide text-ink-muted",
        className
      )}
    >
      {children}
    </span>
  );
}
