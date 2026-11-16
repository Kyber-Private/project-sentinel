"use client";

import clsx from "clsx";
import {
  ArrowRight, ChevronDown, CheckCircle2, Download, FlaskConical,
  Info, Minus, ShieldAlert, ShieldCheck, ShieldQuestion,
  TrendingDown, TrendingUp,
} from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { money, toneBg, toneDot, toneText } from "@/lib/format";
import type { Investigation, MetricLine, ProjectLine, Tone } from "@/types";
import { EvidenceDrawer } from "@/components/EvidenceDrawer";
import { Button, ErrorNote, Panel } from "@/components/ui";
import { WhatIfModal } from "@/features/whatif/WhatIfModal";
import { DetailSections } from "./DetailSections";
import { MetricChart } from "./MetricChart";

const intentText: Record<Tone, string> = {
  favorable: "Positive",
  unfavorable: "Needs attention",
  uncertain: "Worth reviewing",
  neutral: "No clear change",
};

const intentSurface: Record<Tone, string> = {
  favorable: "bg-good/10 text-good ring-good/20",
  unfavorable: "bg-risk/10 text-risk ring-risk/20",
  uncertain: "bg-warn/10 text-warn ring-warn/20",
  neutral: "bg-ink-raised text-text-muted ring-ink-line",
};

const intentAccent: Record<Tone, string> = {
  favorable: "border-good/40",
  unfavorable: "border-risk/40",
  uncertain: "border-warn/40",
  neutral: "border-ink-line",
};

function changeText(m: MetricLine): string {
  if (m.change_pct == null || !Number.isFinite(m.change_pct)) {
    return m.message || m.display.replace(/[↑↓→]/g, "").trim() || "Not enough information";
  }
  const amount = `${Math.abs(m.change_pct).toFixed(1)}%`;
  if (Math.abs(m.change_pct) < 0.05 || m.direction === "stable") return "Holding steady";
  return `${m.change_pct > 0 ? "Up" : "Down"} ${amount}`;
}

function signalExplanation(m: MetricLine): string {
  if (m.change_pct == null) return "Available records do not support a clear forecast.";
  if (m.tone === "favorable") return "A positive signal for your business.";
  if (m.tone === "unfavorable") return "This could put pressure on financial performance.";
  if (m.tone === "uncertain") return "Check the assumptions before acting.";
  return "Little change expected from recent performance.";
}

function amountFromText(v: string): number | null {
  const cleaned = v.replace(/[^\d.\-]/g, "");
  if (!cleaned || !/^\-?\d+(?:\.\d+)?$/.test(cleaned)) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function budgets(p: ProjectLine): number[] {
  const candidates = p.budget_text.replace(/\s*\(unresolved\)/i, "").split(/\s+or\s+/i);
  return candidates.map(amountFromText).filter((n): n is number => n !== null);
}

function differenceLabel(diff: number, currency: string): string {
  const abs = money(Math.abs(diff), currency);
  if (diff > 0) return `Over budget by ${abs}`;
  if (diff < 0) return `Under budget by ${abs}`;
  return "Exactly on budget";
}

function ForecastLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs" aria-label="Forecast color guide">
      <span className="inline-flex items-center gap-2 text-text-muted"><i className="h-2.5 w-2.5 rounded-full bg-good" aria-hidden /> Green: positive</span>
      <span className="inline-flex items-center gap-2 text-text-muted"><i className="h-2.5 w-2.5 rounded-full bg-warn" aria-hidden /> Amber: review</span>
      <span className="inline-flex items-center gap-2 text-text-muted"><i className="h-2.5 w-2.5 rounded-full bg-risk" aria-hidden /> Red: risk</span>
    </div>
  );
}

function ReviewStatus({ verdict, ai }: { verdict: string; ai: boolean }) {
  const [open, setOpen] = useState(false);
  if (!ai || verdict === "not_reviewed") {
    return <span className="inline-flex items-center gap-2 text-xs text-white/70"><ShieldQuestion className="h-4 w-4" aria-hidden /> Not reviewed by AI</span>;
  }
  const qualified = verdict === "qualify";
  const withheld = verdict === "withhold";
  return (
    <div className="max-w-xl">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-2 text-xs font-medium text-white ring-1 ring-white/20 hover:bg-white/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-white">
        {qualified || withheld ? <ShieldAlert className="h-4 w-4 text-amber-200" aria-hidden /> : <ShieldCheck className="h-4 w-4 text-emerald-200" aria-hidden />}
        {qualified ? "Reviewed with cautions" : withheld ? "Reviewer withheld conclusion" : "Independently reviewed"}
        <ChevronDown className={clsx("h-3.5 w-3.5 transition", open && "rotate-180")} aria-hidden />
      </button>
      {open && <p className="mt-2 text-xs leading-relaxed text-white/75">The independent AI reviewer evaluates the strength of the evidence. Its full reasoning is available under Detailed analysis below.</p>}
    </div>
  );
}

function SignalCard({ m, onOpen }: { m: MetricLine; onOpen: (ids: string[], title: string) => void }) {
  const down = m.change_pct != null ? m.change_pct < 0 : m.direction === "decrease";
  const flat = m.change_pct == null || Math.abs(m.change_pct) < 0.05;
  const Trend = flat ? Minus : down ? TrendingDown : TrendingUp;
  return (
    <Panel className={clsx("min-w-0 border-t-[3px] p-5 sm:p-6", intentAccent[m.tone])}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-text-muted">{m.label}</p>
        <Trend className={clsx("h-4 w-4", toneText[m.tone])} aria-hidden />
      </div>
      <p className={clsx("mt-5 text-2xl font-semibold tracking-tight sm:text-3xl", toneText[m.tone])}>{changeText(m)}</p>
      <span className={clsx("mt-3 inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1", intentSurface[m.tone])}>{intentText[m.tone]}</span>
      <p className="mt-3 text-xs leading-relaxed text-text-muted">{signalExplanation(m)}</p>
      {m.fact_ids.length > 0 && (
        <button onClick={() => onOpen(m.fact_ids, `${m.label}: original records`)} className="mt-3 text-xs font-semibold text-brand hover:underline">View evidence</button>
      )}
    </Panel>
  );
}

function ProjectCard({ p, currency, onOpen }: { p: ProjectLine; currency: string; onOpen: (ids: string[], title: string) => void }) {
  const choices = budgets(p);
  const unresolved = p.budget_status === "unresolved";
  const knownBudget = !unresolved && choices.length === 1;
  const gap = knownBudget && p.eac !== null ? p.eac - choices[0] : null;
  return (
    <Panel className="overflow-hidden p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-text-faint">Project outlook</p>
          <h3 className="mt-1 text-lg font-semibold text-text">{p.project}</h3>
        </div>
        <span className={clsx("inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1", intentSurface[unresolved ? "uncertain" : p.tone])}>
          {unresolved ? "Budget needs confirmation" : intentText[p.tone]}
        </span>
      </div>
      <p className="mt-5 text-xs text-text-muted">Estimated total project cost</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-text">{p.eac_text}</p>
      {unresolved ? (
        <div className="mt-4 rounded-xl bg-warn/10 px-4 py-3 ring-1 ring-warn/20">
          <p className="text-sm font-semibold text-warn">Which budget is approved?</p>
          {p.eac !== null && choices.length > 0 ? (
            <ul className="mt-2 space-y-1.5 text-sm text-text">
              {choices.map((b, i) => (
                <li key={`${b}-${i}`}><span className="text-text-muted">If budget is {money(b, currency)}:</span> <span className="font-medium">{differenceLabel(p.eac! - b, currency)}</span></li>
              ))}
            </ul>
          ) : <p className="mt-1 text-sm text-text-muted">{p.budget_text}</p>}
        </div>
      ) : (
        <div className="mt-4 rounded-xl bg-ink-raised px-4 py-3">
          <p className="text-xs text-text-muted">{knownBudget ? `Approved budget: ${money(choices[0], currency)}` : `Approved budget: ${p.budget_text}`}</p>
          <p className={clsx("mt-1 text-sm font-semibold", toneText[p.tone])}>{gap !== null ? differenceLabel(gap, currency) : p.variance_text}</p>
        </div>
      )}
      {p.fact_ids.length > 0 && (
        <button onClick={() => onOpen(p.fact_ids, `${p.project}: source documents`)} className="mt-4 text-xs font-semibold text-brand hover:underline">View supporting records</button>
      )}
    </Panel>
  );
}

function MetricDetails({ m, currency, onOpen }: { m: MetricLine; currency: string; onOpen: (ids: string[], title: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="border-t border-ink-line first:border-0">
      <button onClick={() => setExpanded(!expanded)} aria-expanded={expanded} className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-ink-raised/70">
        <span className={clsx("h-2 w-2 shrink-0 rounded-full", toneDot[m.tone])} aria-hidden />
        <span className="min-w-0 flex-1 text-sm text-text">{m.label}</span>
        <span className={clsx("text-sm font-medium", toneText[m.tone])}>{changeText(m)}</span>
        <ChevronDown className={clsx("h-4 w-4 text-text-faint transition", expanded && "rotate-180")} aria-hidden />
      </button>
      {expanded && <div className="px-5 pb-5">
        {m.forecast.length > 0 && <MetricChart line={m} currency={currency} />}
        {m.detail && <p className="mt-2 text-xs text-text-muted">{m.detail}</p>}
        {m.message && <p className="mt-2 text-xs text-warn">{m.message}</p>}
        {m.fact_ids.length > 0 && <button className="mt-3 text-xs font-medium text-brand hover:underline" onClick={() => onOpen(m.fact_ids, m.label)}>View original records</button>}
      </div>}
    </div>
  );
}

export function OutlookScreen({ inv, onUpdate }: { inv: Investigation; onUpdate: (i: Investigation) => void }) {
  const o = inv.outlook!;
  const [evidence, setEvidence] = useState<{ ids: string[]; title: string } | null>(null);
  const [whatIf, setWhatIf] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const open = (ids: string[], title = "Original source records") => setEvidence({ ids, title });

  const changeHorizon = async (months: number) => {
    if (months === o.horizon_months) return;
    setBusy(months);
    setError(null);
    try { onUpdate(await api.horizon(inv.id, months)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };

  const reopen = async (qid: string) => {
    try { onUpdate(await api.reopen(inv.id, qid)); window.scrollTo({ top: 0 }); }
    catch (e) { setError((e as Error).message); }
  };

  const core = ["revenue", "operating_expenses", "operating_profit"]
    .map((key) => o.company.find((m) => m.metric === key))
    .filter((m): m is MetricLine => !!m);
  const seen = new Set(core.map((m) => m.id));
  const additional = [...o.company.filter((m) => !seen.has(m.id)), ...(o.company_other ?? [])]
    .filter((m, idx, arr) => arr.findIndex((v) => v.id === m.id) === idx);
  const shortHeadline = o.overall.headline.split(/(?<=[.!?])\s+/)[0] || o.overall.headline;

  return (
    <div className="space-y-7 pb-8">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.17em] text-brand">Financial intelligence / Outlook</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-text sm:text-4xl">{o.company_name}</h1>
          <p className="mt-2 text-sm text-text-muted">Data through {o.as_of_label} · {o.forecast_window.label ?? "Forecast window unavailable"} · {o.currency}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl bg-white p-1 shadow-sm ring-1 ring-ink-line" role="group" aria-label="Forecast period">
            {[3, 6, 12].map((months) => (
              <button key={months} onClick={() => changeHorizon(months)} disabled={busy !== null}
                aria-pressed={o.horizon_months === months}
                className={clsx("rounded-lg px-3 py-2 text-xs font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand", o.horizon_months === months ? "bg-brand text-white shadow-sm" : "text-text-muted hover:bg-ink-raised hover:text-text")}>
                {busy === months ? "Updating" : `${months} months`}
              </button>
            ))}
          </div>
          <Button variant="secondary" onClick={() => setWhatIf(true)}><FlaskConical className="h-4 w-4" aria-hidden /> What if?</Button>
          <a href={api.reportUrl(inv.id)} className="inline-flex items-center gap-2 rounded-xl bg-text px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            <Download className="h-4 w-4" aria-hidden /> Export PDF
          </a>
        </div>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}

      <section className="relative overflow-hidden rounded-[26px] bg-[#151D3F] p-7 text-white shadow-[0_14px_42px_-25px_rgba(23,31,72,0.7)] sm:p-9">
        <div className="pointer-events-none absolute -right-20 -top-32 h-72 w-72 rounded-full bg-[#716BFF]/20 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute bottom-0 right-0 h-28 w-80 bg-gradient-to-l from-[#635BFF]/20 to-transparent" aria-hidden />
        <div className="relative">
          <p className="text-xs font-semibold uppercase tracking-[0.19em] text-indigo-200">Your financial outlook</p>
          <div className="mt-4 flex flex-wrap items-start justify-between gap-5">
            <h2 className="max-w-2xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{o.overall.label.toLowerCase().replace(/^./, (c) => c.toUpperCase())}</h2>
            <ReviewStatus ai={inv.ai_enabled} verdict={o.overall.reviewer_verdict} />
          </div>
          <p className="mt-4 max-w-3xl text-base leading-7 text-white/85">{shortHeadline}</p>
          {o.overall.reviewer_verdict === "qualify" && <p className="mt-3 flex items-start gap-2 text-xs text-indigo-100/80"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> This is a planning estimate, not a guaranteed outcome. See the detailed review below.</p>}
        </div>
      </section>

      <section aria-label="Financial signals">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-text">The numbers at a glance</h2>
            <p className="mt-1 text-sm text-text-muted">Next {o.horizon_months} months compared with the previous {o.horizon_months} months.</p>
          </div>
          <ForecastLegend />
        </div>
        <p className="mb-4 text-xs text-text-faint">Color shows whether a change helps or hurts the business — not whether the number increases or decreases.</p>
        {core.length > 0 ? <div className="grid gap-4 md:grid-cols-3">{core.map((m) => <SignalCard key={m.id} m={m} onOpen={open} />)}</div> : <Panel className="p-6 text-sm text-text-muted">Not enough financial history to show the three main signals.</Panel>}
      </section>

      <section aria-label="Project forecasts">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-text">Projects to watch</h2>
            <p className="mt-1 text-sm text-text-muted">Estimated final costs compared with recorded project budgets.</p>
          </div>
        </div>
        {o.projects.length > 0 ? <div className="grid gap-4 md:grid-cols-2">{o.projects.map((p) => <ProjectCard key={p.id} p={p} currency={o.currency} onOpen={open} />)}</div> : <Panel className="p-6 text-sm text-text-muted">No project budget information was found in these documents.</Panel>}
      </section>

      <Panel className="flex flex-col gap-4 border-l-4 border-l-brand p-6 sm:flex-row sm:items-start sm:gap-6">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand"><ArrowRight className="h-5 w-5" aria-hidden /></span>
        <div>
          <h2 className="text-base font-semibold text-text">What to do next</h2>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-text-muted">{o.next_step}</p>
        </div>
      </Panel>

      <div className="overflow-hidden rounded-2xl border border-ink-line bg-white shadow-sm">
        <button onClick={() => setDetailsOpen(!detailsOpen)} aria-expanded={detailsOpen} className="flex w-full flex-wrap items-center justify-between gap-3 px-6 py-5 text-left transition hover:bg-ink-raised/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand">
          <span>
            <span className="block text-base font-semibold text-text">Detailed analysis and evidence</span>
            <span className="mt-1 block text-sm text-text-muted">Charts, other metrics, assumptions, sources, and AI reviewer notes.</span>
          </span>
          <span className="inline-flex items-center gap-2 text-sm font-semibold text-brand">{detailsOpen ? "Hide details" : "Explore details"}<ChevronDown className={clsx("h-4 w-4 transition", detailsOpen && "rotate-180")} aria-hidden /></span>
        </button>
        {detailsOpen && <div className="space-y-5 border-t border-ink-line bg-[#FBFCFF] p-4 sm:p-6">
          {additional.length > 0 && <Panel className="overflow-hidden">
            <h3 className="px-5 py-4 text-sm font-semibold text-text">Other financial metrics</h3>
            {additional.map((m) => <MetricDetails key={m.id} m={m} currency={o.currency} onOpen={open} />)}
          </Panel>}
          {core.length > 0 && <Panel className="overflow-hidden">
            <h3 className="px-5 py-4 text-sm font-semibold text-text">Main forecast charts</h3>
            {core.map((m) => <MetricDetails key={m.id} m={m} currency={o.currency} onOpen={open} />)}
          </Panel>}
          {o.reasons.length > 0 && <Panel className="p-5">
            <h3 className="text-sm font-semibold text-text">What drives the forecast</h3>
            <ul className="mt-3 space-y-3">
              {o.reasons.map((r) => <li key={r.driver_id} className="text-sm leading-relaxed text-text-muted">
                <span className="font-semibold text-text">{r.title}. </span>{r.text}
                {r.fact_ids.length > 0 && <button onClick={() => open(r.fact_ids, r.title)} className="ml-2 text-xs font-semibold text-brand hover:underline">Sources</button>}
              </li>)}
            </ul>
          </Panel>}
          <DetailSections inv={inv} o={o} onOpen={open} onReopen={reopen} />
        </div>}
      </div>

      <div className="flex items-center gap-2 text-xs text-text-faint"><CheckCircle2 className="h-4 w-4" aria-hidden /> Forecasts are estimates based on uploaded data. Review key assumptions before financial decisions.</div>
      <EvidenceDrawer invId={inv.id} factIds={evidence?.ids ?? null} title={evidence?.title ?? ""} onClose={() => setEvidence(null)} />
      <WhatIfModal open={whatIf} onClose={() => setWhatIf(false)} invId={inv.id} projects={o.projects.map((p) => p.project)} currency={o.currency} horizon={o.horizon_months} />
    </div>
  );
}
