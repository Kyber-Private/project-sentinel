"use client";

import clsx from "clsx";
import { ChevronDown, Loader2, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import type { Tone } from "@/types";
import { toneBg } from "@/lib/format";

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <Link href="/" className="inline-flex items-center gap-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-md">
      <span className={clsx("grid place-items-center rounded-xl bg-brand shadow-[0_5px_14px_rgba(99,91,255,0.2)]", small ? "h-7 w-7" : "h-9 w-9")}>
        <ShieldCheck className={clsx("text-white", small ? "h-4 w-4" : "h-5 w-5")} aria-hidden />
      </span>
      <span className={clsx("font-semibold tracking-[0.12em] text-text", small ? "text-xs" : "text-sm")}>PROJECT SENTINEL</span>
    </Link>
  );
}

export function Button({
  children, onClick, variant = "primary", disabled, type = "button", className, busy, ariaLabel,
}: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "ghost" | "danger";
  disabled?: boolean; type?: "button" | "submit"; className?: string; busy?: boolean; ariaLabel?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      aria-label={ariaLabel}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold shadow-sm transition",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-ink",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-brand text-white hover:bg-[#5149D9]",
        variant === "secondary" && "bg-white text-text ring-1 ring-ink-line hover:bg-ink-raised",
        variant === "ghost" && "text-text-muted hover:text-text hover:bg-ink-raised",
        variant === "danger" && "text-risk hover:bg-risk/10",
        className,
      )}
    >
      {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Badge({ tone, children, className }: { tone: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1", toneBg[tone], className)}>
      {children}
    </span>
  );
}

export function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={clsx("rounded-2xl border border-ink-line bg-white shadow-[0_6px_24px_-20px_rgba(27,41,76,0.32)]", className)}>{children}</section>;
}

export function Expandable({
  title, subtitle, children, defaultOpen = false, id,
}: { title: string; subtitle?: string; children: ReactNode; defaultOpen?: boolean; id?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-ink-line first:border-t-0" id={id}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-ink-raised/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
      >
        <span>
          <span className="block text-sm font-medium text-text">{title}</span>
          {subtitle && <span className="mt-0.5 block text-xs text-text-muted">{subtitle}</span>}
        </span>
        <ChevronDown className={clsx("h-4 w-4 shrink-0 text-text-muted transition", open && "rotate-180")} aria-hidden />
      </button>
      {open && <div className="px-5 pb-5">{children}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#17233F]/50 p-0 sm:items-center sm:p-6" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div
        className={clsx("max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-ink-panel ring-1 ring-ink-line sm:rounded-2xl", wide ? "max-w-3xl" : "max-w-xl")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-ink-line bg-ink-panel px-5 py-4">
          <h2 className="text-base font-semibold text-text">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-text-muted hover:bg-ink-raised hover:text-text focus:outline-none focus-visible:ring-2 focus-visible:ring-brand" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-xl bg-risk/10 px-4 py-3 text-sm text-risk ring-1 ring-risk/25">
      {children}
    </div>
  );
}
