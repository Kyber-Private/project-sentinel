"use client";

import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, RUNNING } from "@/lib/api";
import type { Investigation } from "@/types";
import { ProgressPanel } from "@/components/ProgressPanel";
import { Button, ErrorNote, Logo, Panel } from "@/components/ui";
import { ClarificationScreen } from "./clarification/ClarificationScreen";
import { OutlookScreen } from "./outlook/OutlookScreen";

/** Routes between the three experiences based on the investigation's real status. */
export function InvestigationView({ id }: { id: string }) {
  const router = useRouter();
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get(id);
      setInv(data);
      setError(null);
      return data;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const data = await load();
      if (alive && data && RUNNING.includes(data.status)) timer.current = setTimeout(tick, 1200);
    };
    tick();
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, [load]);

  const update = (next: Investigation) => {
    setInv(next);
    if (RUNNING.includes(next.status)) {
      if (timer.current) clearTimeout(timer.current);
      const poll = async () => {
        const d = await load();
        if (d && RUNNING.includes(d.status)) timer.current = setTimeout(poll, 1200);
      };
      timer.current = setTimeout(poll, 800);
    }
  };

  const retry = async () => {
    try { update(await api.analyze(id)); } catch (e) { setError((e as Error).message); }
  };

  const remove = async () => {
    if (!confirm("Delete this investigation and its uploaded files?")) return;
    await api.remove(id).catch(() => undefined);
    router.push("/");
  };

  const running = inv && RUNNING.includes(inv.status);

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 pb-16 pt-6">
      <header className="mb-8 flex items-center justify-between gap-3">
        <Logo small />
        <div className="flex items-center gap-1">
          <Button variant="ghost" onClick={() => router.push("/")}><Plus className="h-4 w-4" aria-hidden /> New</Button>
          {inv && !running && <Button variant="ghost" onClick={remove} ariaLabel="Delete investigation"><Trash2 className="h-4 w-4" aria-hidden /></Button>}
        </div>
      </header>

      {error && !inv && <ErrorNote>{error}</ErrorNote>}
      {!inv && !error && <p className="text-sm text-text-muted">Loading investigation...</p>}

      {inv && running && (
        <div className="mx-auto max-w-xl">
          <h1 className="text-xl font-semibold text-text">{inv.status === "extracting" ? "Reading your documents" : "Building your outlook"}</h1>
          <p className="mt-1 text-sm text-text-muted">{inv.stage_message ?? "Working..."}</p>
          <Panel className="mt-6 p-6"><ProgressPanel steps={inv.progress} /></Panel>
          {!inv.ai_enabled && (
            <p className="mt-4 text-xs text-text-faint">AI agents are off, so their steps are skipped. Figures come from extraction and the forecasting engine.</p>
          )}
        </div>
      )}

      {inv && inv.status === "awaiting_answers" && <ClarificationScreen inv={inv} onUpdate={update} />}
      {inv && inv.status === "complete" && inv.outlook && <OutlookScreen inv={inv} onUpdate={update} />}

      {inv && inv.status === "error" && (
        <div className="mx-auto max-w-xl space-y-4">
          <ErrorNote>The analysis stopped: {inv.error}</ErrorNote>
          <Panel className="p-6"><ProgressPanel steps={inv.progress} /></Panel>
          <Button onClick={retry}><RefreshCw className="h-4 w-4" aria-hidden /> Try again</Button>
        </div>
      )}

      {inv && inv.status === "draft" && (
        <div className="mx-auto max-w-xl space-y-4">
          <p className="text-sm text-text-muted">This investigation has {inv.files.length} file(s) and has not been analyzed with its current documents.</p>
          <Button onClick={retry} disabled={!inv.files.length}>Analyze my business</Button>
        </div>
      )}
    </div>
  );
}
