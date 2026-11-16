"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, CircleDashed, Clock, Loader2, MinusCircle } from "lucide-react";
import type { Step } from "@/types";

const ICON = {
  done: <CheckCircle2 className="h-4 w-4 text-good" aria-hidden />,
  running: <Loader2 className="h-4 w-4 animate-spin text-brand" aria-hidden />,
  pending: <CircleDashed className="h-4 w-4 text-text-faint" aria-hidden />,
  skipped: <MinusCircle className="h-4 w-4 text-text-faint" aria-hidden />,
  failed: <AlertCircle className="h-4 w-4 text-risk" aria-hidden />,
  waiting: <Clock className="h-4 w-4 text-warn" aria-hidden />,
};

/** Shows the real pipeline status reported by the backend. No simulated activity. */
export function ProgressPanel({ steps, compact = false }: { steps: Step[]; compact?: boolean }) {
  return (
    <ol className={clsx("space-y-2.5", compact && "space-y-1.5")} aria-live="polite">
      {steps.map((s) => (
        <li key={s.key} className="flex items-start gap-3">
          <span className="mt-0.5">{ICON[s.status] ?? ICON.pending}</span>
          <span className="min-w-0">
            <span className={clsx("block text-sm", s.status === "pending" ? "text-text-faint" : "text-text")}>{s.label}</span>
            {s.detail && !compact && <span className="block text-xs text-text-muted">{s.detail}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}
