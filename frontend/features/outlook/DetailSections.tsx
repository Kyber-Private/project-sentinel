"use client";

import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { money, toneDot, toneText } from "@/lib/format";
import type { Finding, Investigation, Outlook } from "@/types";
import { Badge, Button, Expandable, Panel } from "@/components/ui";

const evidenceLabel: Record<string, string> = {
  observed: "Observed in documents",
  calculated: "Calculated from records",
  estimated: "Estimated",
  hypothesized: "Hypothesis",
};

function EvidenceButton({ ids, onOpen, label = "View sources" }: { ids: string[]; onOpen: (ids: string[]) => void; label?: string }) {
  if (!ids?.length) return null;
  return (
    <button onClick={() => onOpen(ids)} className="text-xs text-brand hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded">
      {label} ({ids.length})
    </button>
  );
}

function FindingRow({ f, onOpen }: { f: Finding; onOpen: (ids: string[]) => void }) {
  const a = f.review?.assessment;
  const tone = a === "supported" ? "favorable" : a === "hypothesis" || a === "overstated" ? "uncertain" : a ? "unfavorable" : "neutral";
  return (
    <li className="rounded-lg bg-ink p-3 ring-1 ring-ink-line">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-text">{f.title}</p>
        <div className="flex gap-1.5">
          {f.check && <Badge tone={f.check.status === "verified" ? "favorable" : "uncertain"}>Numbers {f.check.status.replace("_", " ")}</Badge>}
          {a && <Badge tone={tone}>Alex: {a}</Badge>}
        </div>
      </div>
      <p className="mt-1 text-sm text-text-muted">{f.statement}</p>
      {f.review?.comment && <p className="mt-1 text-xs text-text-faint">Reviewer: {f.review.comment}</p>}
      {f.check && f.check.unverified_numbers.length > 0 && (
        <p className="mt-1 text-xs text-warn">Numbers not found in the data: {f.check.unverified_numbers.join(", ")}</p>
      )}
      <div className="mt-1.5 flex gap-3 text-xs text-text-faint">
        <span>{evidenceLabel[f.evidence_type] ?? f.evidence_type}, {f.support}</span>
        <EvidenceButton ids={f.cited_fact_ids} onOpen={onOpen} />
      </div>
    </li>
  );
}

export function DetailSections({ inv, o, onOpen, onReopen }: {
  inv: Investigation; o: Outlook; onOpen: (ids: string[], title?: string) => void; onReopen: (qid: string) => void;
}) {
  const cur = o.currency;
  const review = o.agent_review;
  return (
    <Panel className="overflow-hidden">
      <Expandable title="Why the numbers are changing" subtitle="Drivers behind the forecast" id="why">
        <p className="text-sm leading-relaxed text-text">{o.why.plain_language}</p>
        <div className="mt-4 space-y-5">
          {o.why.movements.map((m) => (
            <div key={m.id}>
              <p className={clsx("flex items-center gap-2 text-sm font-semibold", toneText[m.tone])}>
                <span className={clsx("h-2 w-2 rounded-full", toneDot[m.tone])} aria-hidden />
                {m.title} <span className="font-normal text-text-muted">{m.summary}</span>
              </p>
              <ul className="mt-2 space-y-2">
                {m.drivers.map((d) => (
                  <li key={d.id} className="rounded-lg bg-ink p-3 ring-1 ring-ink-line">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-sm font-medium text-text">{d.title}</p>
                      {d.magnitude && <span className="font-mono text-xs text-text-muted">{d.magnitude}</span>}
                    </div>
                    <p className="mt-1 text-sm text-text-muted">{d.what_changed}</p>
                    <p className="mt-1 text-sm text-text-muted">{d.effect_on_forecast}</p>
                    <div className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-text-faint">
                      <span>{evidenceLabel[d.evidence_type]}</span>
                      <span>{d.support === "supported" ? "Supported by the arithmetic" : "Plausible, not proven"}</span>
                      {d.period_compared && <span>{d.period_compared}</span>}
                      <EvidenceButton ids={d.fact_ids} onOpen={(ids) => onOpen(ids, d.title)} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Expandable>

      <Expandable title="How the forecast was calculated" subtitle="Methods, ranges, and validation">
        <div className="space-y-4">
          {o.methodology.map((m) => (
            <div key={m.id} className="rounded-lg bg-ink p-3 ring-1 ring-ink-line">
              <p className="text-sm font-medium text-text">{m.label}: <span className="font-normal text-text-muted">{m.model ?? "No forecast"}</span></p>
              {m.reason && <p className="mt-1 text-xs text-text-muted">{m.reason}</p>}
              {m.formula && <p className="mt-1 text-xs text-text-muted">Formula: {m.formula}</p>}
              {m.history_months !== undefined && (
                <p className="mt-1 text-xs text-text-faint">History: {m.history_months} months · Data sufficiency: {m.sufficiency} · {m.validated ? "Validated with rolling-origin backtests" : "Not validated"}</p>
              )}
              {m.validation && m.validation.length > 0 && (
                <table className="mt-2 w-full text-xs">
                  <thead><tr className="text-left text-text-faint"><th className="py-1 font-medium">Candidate model</th><th className="py-1 text-right font-medium">Avg error (MAE)</th><th className="py-1 text-right font-medium">MAPE</th></tr></thead>
                  <tbody>
                    {m.validation.map((v) => (
                      <tr key={v.model} className="text-text-muted"><td className="py-0.5">{v.label}</td><td className="py-0.5 text-right font-mono">{money(v.mae, cur)}</td><td className="py-0.5 text-right font-mono">{v.mape != null ? `${v.mape.toFixed(1)}%` : "n/a"}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              {m.methods && (
                <ul className="mt-2 space-y-1 text-xs text-text-muted">
                  {m.methods.map((x) => (
                    <li key={x.name}><span className="text-text">{x.label}: {money(x.eac, cur)}</span> = {x.formula}. {x.note}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          <p className="text-xs text-text-faint">Ranges are approximate 80% bands built from past forecast errors on this data. They are not probabilities of any specific outcome.</p>
        </div>
      </Expandable>

      <Expandable title="Data sources and checks" subtitle="Conflicts, duplicates, and evidence">
        <div className="space-y-4 text-sm">
          {o.data_quality.conflicts.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-faint">Conflicting figures</p>
              <ul className="mt-2 space-y-2">
                {o.data_quality.conflicts.map((c) => (
                  <li key={c.id} className="rounded-lg bg-ink p-3 ring-1 ring-ink-line">
                    <p className="text-text">{c.description}</p>
                    <p className="mt-1 text-xs text-text-muted">{c.resolved_fact_id ? "Resolved with your answer." : "Not resolved."} <EvidenceButton ids={c.fact_ids} onOpen={onOpen} label="Compare sources" /></p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {o.data_quality.duplicates.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-faint">Duplicates counted once</p>
              <ul className="mt-2 space-y-1.5">
                {o.data_quality.duplicates.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-baseline gap-x-2 text-text-muted">
                    {d.kind === "uncertain" && <Badge tone="uncertain">Review</Badge>}
                    <span>{d.description}</span> <EvidenceButton ids={d.fact_ids} onOpen={onOpen} label="Sources" />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {o.data_quality.issues.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-faint">Data checks</p>
              <ul className="mt-2 space-y-1.5 text-text-muted">
                {o.data_quality.issues.map((i, n) => <li key={n}>{i.severity === "info" ? "" : `${i.severity}: `}{i.message}</li>)}
              </ul>
            </div>
          )}
        </div>
      </Expandable>

      <Expandable title="Assumptions and answers" subtitle={`${o.assumptions.length} assumptions · ${o.answers.length} answers`}>
        {o.answers.length > 0 && (
          <ul className="mb-4 space-y-2">
            {o.answers.map((a) => (
              <li key={a.id} className="rounded-lg bg-ink p-3 text-sm ring-1 ring-ink-line">
                <p className="text-text-muted">{a.text}</p>
                <p className="mt-1 text-text">{a.status === "skipped" ? "Skipped: unresolved assumption" : a.interpretation}</p>
                {a.change_summary && <p className="mt-0.5 text-xs text-text-faint">{a.change_summary}</p>}
                <Button variant="ghost" className="mt-1 -ml-2 px-2 py-1 text-xs" onClick={() => onReopen(a.id)}>Change answer</Button>
              </li>
            ))}
          </ul>
        )}
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-text-muted">
          {o.assumptions.map((a) => <li key={a}>{a}</li>)}
        </ul>
      </Expandable>

      <Expandable title="AI analyst and reviewer notes" subtitle={review?.ai_enabled ? "Emily, Sebas, and Alex" : "AI agents were not run"}>
        {!review?.ai_enabled && (
          <p className="text-sm text-text-muted">
            No OpenAI API key is configured, so the Data Analyst, Emily, Sebas, and Alex did not run. Every figure on this page comes from
            document extraction and the forecasting engine. Add <code>OPENAI_API_KEY</code> to the backend to enable the agents.
          </p>
        )}
        {review?.ai_enabled && (
          <div className="space-y-5">
            {review.alex && (
              <div className="rounded-lg bg-ink p-4 ring-1 ring-ink-line">
                <p className="text-sm font-semibold text-text">Alex, independent reviewer: <span className="capitalize">{review.alex.overall_verdict}</span> (confidence {review.alex.recommended_confidence})</p>
                <p className="mt-1 text-sm text-text-muted">{review.alex.verdict_reason}</p>
                {review.alex.challenges.length > 0 && (
                  <ul className="mt-2 space-y-1 text-sm text-text-muted">
                    {review.alex.challenges.map((c, i) => <li key={i}><Badge tone={c.severity === "high" ? "unfavorable" : "uncertain"} className="mr-1.5">{c.severity}</Badge>{c.target}: {c.issue}</li>)}
                  </ul>
                )}
                {review.alex.false_precision.length > 0 && <p className="mt-2 text-xs text-text-muted">False precision: {review.alex.false_precision.join(" ")}</p>}
                {review.alex.insufficient_data.length > 0 && <p className="mt-1 text-xs text-text-muted">Insufficient data: {review.alex.insufficient_data.join(" ")}</p>}
              </div>
            )}
            {review.emily && (
              <div>
                <p className="text-sm font-semibold text-text">Emily, company analyst</p>
                <p className="mt-1 text-sm text-text-muted">{review.emily.summary}</p>
                <ul className="mt-2 space-y-2">{review.emily.findings.map((f) => <FindingRow key={f.claim_id} f={f} onOpen={onOpen} />)}</ul>
              </div>
            )}
            {review.sebas?.projects.map((p) => (
              <div key={p.project}>
                <p className="text-sm font-semibold text-text">Sebas, project analyst: {p.project}</p>
                <p className="mt-1 text-sm text-text-muted">{p.summary}</p>
                <ul className="mt-2 space-y-2">{p.findings.map((f) => <FindingRow key={f.claim_id} f={f} onOpen={onOpen} />)}</ul>
              </div>
            ))}
            {review.failed.length > 0 && <p className="text-sm text-warn">These agents failed and their sections are missing: {review.failed.join(", ")}.</p>}
          </div>
        )}
        {review && review.runs.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-text-faint">Agent execution log</p>
            <ul className="mt-2 space-y-1 text-xs text-text-muted">
              {review.runs.map((r, i) => (
                <li key={i}>{r.agent}: {r.status}{r.model ? ` · ${r.model}` : ""}{r.duration_ms ? ` · ${(r.duration_ms / 1000).toFixed(1)}s` : ""}{r.error ? ` · ${r.error}` : ""}</li>
              ))}
            </ul>
          </div>
        )}
      </Expandable>

      <Expandable title="Source documents" subtitle={`${o.files.length} files`}>
        <ul className="space-y-1.5 text-sm">
          {inv.files.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-x-2">
              <a href={api.fileUrl(inv.id, f.id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand hover:underline">
                {f.name} <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
              <span className="text-xs text-text-faint">{f.type.toUpperCase()}{f.pages ? ` · ${f.pages} pages` : ""}{f.message ? ` · ${f.message}` : ""}</span>
            </li>
          ))}
        </ul>
      </Expandable>
    </Panel>
  );
}
