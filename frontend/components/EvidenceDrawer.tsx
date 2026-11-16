"use client";

import { ExternalLink, FileText, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { metricLabel, money, monthLabel } from "@/lib/format";
import type { FactT } from "@/types";
import { ErrorNote, Modal } from "./ui";

function location(s: FactT["source"]) {
  const parts: string[] = [];
  if (s.page) parts.push(`page ${s.page}`);
  if (s.sheet) parts.push(`sheet "${s.sheet}"`);
  if (s.row) parts.push(`row ${s.row}`);
  if (s.record_id) parts.push(s.record_id);
  return parts.join(", ");
}

function valueText(f: FactT) {
  if (f.value === null || f.value === undefined) return f.text_value ?? "";
  if (f.unit === "percent") return `${f.value}%`;
  if (f.unit === "currency") return money(f.value, f.currency ?? "USD");
  return String(f.value);
}

/** Lists the exact source records behind a claim, with links to the original files. */
export function EvidenceDrawer({ invId, factIds, title, onClose }: { invId: string; factIds: string[] | null; title: string; onClose: () => void }) {
  const [facts, setFacts] = useState<FactT[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!factIds) return;
    setFacts(null);
    setError(null);
    if (factIds.length === 0) {
      setFacts([]);
      return;
    }
    api.facts(invId, factIds).then(setFacts).catch((e) => setError(e.message));
  }, [invId, factIds]);

  return (
    <Modal open={!!factIds} onClose={onClose} title={title} wide>
      {error && <ErrorNote>{error}</ErrorNote>}
      {!facts && !error && (
        <p className="flex items-center gap-2 text-sm text-text-muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading source records</p>
      )}
      {facts && facts.length === 0 && (
        <p className="text-sm text-text-muted">This item is a calculation. Its inputs are listed in the forecast methodology section.</p>
      )}
      {facts && facts.length > 0 && (
        <ul className="space-y-3">
          {facts.map((f) => (
            <li key={f.id} className="rounded-xl bg-ink p-4 ring-1 ring-ink-line">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium text-text">
                  {f.entity !== "__company__" ? `${f.entity}: ` : ""}{metricLabel(f.metric)}
                  {f.dimension ? ` (${f.dimension})` : ""}{f.period ? `, ${monthLabel(f.period)}` : ""}
                </p>
                <p className="font-mono text-sm text-text">{valueText(f)}</p>
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-text-muted">
                <FileText className="h-3.5 w-3.5" aria-hidden />
                <span>{f.source.file_name}</span>
                {location(f.source) && <span>· {location(f.source)}</span>}
                <span>· {f.extraction_method === "agent" ? "extracted by Data Analyst, verified against source text" : f.extraction_method === "table" ? "read from table" : "read from text"}</span>
                {f.superseded && <span className="text-warn">· not used (duplicate or replaced)</span>}
              </p>
              {f.source.excerpt && (
                <blockquote className="mt-2 border-l-2 border-ink-line pl-3 text-xs leading-relaxed text-text-muted">{f.source.excerpt}</blockquote>
              )}
              {f.corroborating_sources?.length > 0 && (
                <p className="mt-2 text-xs text-text-muted">
                  Same value also in: {f.corroborating_sources.map((c) => `${c.file_name}${c.page ? ` p.${c.page}` : ""}${c.sheet ? ` ${c.sheet}` : ""}`).join("; ")}
                </p>
              )}
              <a
                href={api.fileUrl(invId, f.source.file_id, f.source.page)}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-brand hover:underline"
              >
                Open original file <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
