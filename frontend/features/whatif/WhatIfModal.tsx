"use client";

import clsx from "clsx";
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { ScenarioInputT, ScenarioResult } from "@/types";
import { Button, ErrorNote, Modal } from "@/components/ui";

const EMPTY: ScenarioInputT = {
  revenue_change_pct: 0, opex_change_pct: 0, supplier_cost_change_pct: 0,
  extra_monthly_hiring_cost: 0, project_delay_weeks: 0, delayed_project: null,
};

function Slider({ label, value, onChange, min, max, step, suffix, hint }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; step: number; suffix: string; hint?: string;
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between text-sm">
        <span className="text-text">{label}</span>
        <span className="font-mono text-text">{value > 0 && suffix === "%" ? "+" : ""}{suffix === "$" ? money(value) : `${value}${suffix}`}</span>
      </span>
      {hint && <span className="block text-xs text-text-muted">{hint}</span>}
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-brand" aria-label={label} />
    </label>
  );
}

export function WhatIfModal({ open, onClose, invId, projects, currency, horizon }: {
  open: boolean; onClose: () => void; invId: string; projects: string[]; currency: string; horizon: number;
}) {
  const [inp, setInp] = useState<ScenarioInputT>(EMPTY);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof ScenarioInputT) => (v: number | string | null) => setInp({ ...inp, [k]: v });

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.scenario(invId, inp));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="What if?" wide>
      <p className="flex items-center gap-2 text-sm text-text-muted">
        <FlaskConical className="h-4 w-4 text-warn" aria-hidden />
        Change an assumption to see how the {horizon}-month forecast moves. Results are hypothetical, recalculated by the forecasting engine.
      </p>
      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <Slider label="Revenue vs forecast" value={inp.revenue_change_pct} onChange={set("revenue_change_pct")} min={-20} max={20} step={1} suffix="%" />
        <Slider label="Operating expenses" value={inp.opex_change_pct} onChange={set("opex_change_pct")} min={-20} max={20} step={1} suffix="%" />
        <Slider label="Supplier costs" value={inp.supplier_cost_change_pct} onChange={set("supplier_cost_change_pct")} min={-20} max={20} step={1} suffix="%" hint="Applies to cost of goods sold and open project orders" />
        <Slider label="Extra hiring cost per month" value={inp.extra_monthly_hiring_cost} onChange={set("extra_monthly_hiring_cost")} min={0} max={100000} step={2500} suffix="$" />
        {projects.length > 0 && (
          <div className="sm:col-span-2 grid gap-3 sm:grid-cols-2">
            <Slider label="Project delay" value={inp.project_delay_weeks} onChange={set("project_delay_weeks")} min={0} max={16} step={1} suffix=" weeks" />
            <label className="block text-sm">
              <span className="text-text">Delayed project</span>
              <select value={inp.delayed_project ?? ""} onChange={(e) => set("delayed_project")(e.target.value || null)}
                className="mt-2 w-full rounded-lg bg-ink px-3 py-2 text-sm text-text ring-1 ring-ink-line focus:outline-none focus:ring-2 focus:ring-brand">
                <option value="">All projects</option>
                {projects.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
          </div>
        )}
      </div>
      <div className="mt-6 flex gap-2">
        <Button onClick={run} busy={busy}>Recalculate</Button>
        <Button variant="ghost" onClick={() => { setInp(EMPTY); setResult(null); }}>Reset</Button>
      </div>
      {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}
      {result && (
        <div className="mt-6">
          <p className="text-xs font-semibold uppercase tracking-wider text-warn">Hypothetical scenario, not a confirmed prediction</p>
          {result.changed.length > 0 && <p className="mt-1 text-sm text-text-muted">Changed: {result.changed.join("; ")}</p>}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-text-muted">
                  <th className="py-2 pr-3 font-medium">Item</th>
                  <th className="py-2 pr-3 text-right font-medium">Original</th>
                  <th className="py-2 pr-3 text-right font-medium">Scenario</th>
                  <th className="py-2 text-right font-medium">Difference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-line">
                {result.lines.map((l) => (
                  <tr key={l.key}>
                    <td className="py-2 pr-3 text-text">{l.label}</td>
                    <td className="py-2 pr-3 text-right font-mono text-text-muted">{money(l.original, result.currency)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-text">{money(l.new, result.currency)}</td>
                    <td className={clsx("py-2 text-right font-mono", l.favorable === true && "text-good", l.favorable === false && "text-risk", l.favorable === null && "text-text-muted")}>
                      {money(l.difference, result.currency, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="mt-4 space-y-1 text-sm text-text">
            {result.explanations.map((e) => <li key={e}>{e}</li>)}
          </ul>
          <ul className="mt-3 space-y-1 text-xs text-text-muted">
            {result.assumptions.map((a) => <li key={a}>Assumption: {a}</li>)}
          </ul>
        </div>
      )}
    </Modal>
  );
}
