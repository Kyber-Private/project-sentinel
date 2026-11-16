"use client";

import clsx from "clsx";
import { CheckCircle2, HelpCircle, MessageSquare } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Investigation, QuestionT } from "@/types";
import { Badge, Button, ErrorNote, Panel } from "@/components/ui";

export function ClarificationScreen({ inv, onUpdate }: { inv: Investigation; onUpdate: (i: Investigation) => void }) {
  const questions = inv.questions;
  const open = questions.filter((q) => q.status === "open");
  const done = questions.filter((q) => q.status !== "open");
  const current: QuestionT | undefined = open[0];
  const [text, setText] = useState("");
  const [option, setOption] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<{ q: string; interp: string; change?: string | null } | null>(null);

  useEffect(() => { setText(""); setOption(null); setError(null); }, [current?.id]);

  const position = useMemo(() => (current ? questions.findIndex((q) => q.id === current.id) + 1 : questions.length), [current, questions]);
  const summary = inv.extraction_summary;

  const submit = async (body: { text?: string; option_id?: string; skip?: boolean }, kind: string) => {
    if (!current) return;
    setBusy(kind);
    setError(null);
    try {
      const res = await api.answer(inv.id, current.id, body);
      setLast({ q: current.text, interp: res.result.interpretation, change: res.result.change_summary });
      onUpdate(res.investigation);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (option) submit({ option_id: option, text: text || undefined }, "submit");
    else if (text.trim()) submit({ text }, "submit");
    else setError("Choose an option, type an answer, or press Skip.");
  };

  const runAnalysis = async () => {
    setBusy("continue");
    setError(null);
    try {
      onUpdate(await api.continue(inv.id));
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };

  const needsTyping = current?.input_type !== "choice" || option === "other";

  return (
    <div className="mx-auto max-w-2xl">
      {summary && (
        <p className="text-sm text-text-muted">
          Sentinel read {inv.files.length} documents and found {summary.facts} usable records
          {summary.company_name ? ` for ${summary.company_name}` : ""}
          {summary.projects.length ? `, including ${summary.projects.length} project${summary.projects.length > 1 ? "s" : ""}` : ""}.
          {summary.duplicates ? ` ${summary.duplicates} duplicate record group${summary.duplicates > 1 ? "s were" : " was"} counted once.` : ""}
        </p>
      )}

      {last && (
        <div className="mt-5 flex gap-3 rounded-xl bg-good/10 px-4 py-3 text-sm ring-1 ring-good/30" role="status">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-good" aria-hidden />
          <div>
            <p className="text-text">{last.interp}</p>
            {last.change && <p className="mt-0.5 text-xs text-text-muted">{last.change}</p>}
          </div>
        </div>
      )}

      {current ? (
        <Panel className="mt-6 p-6 sm:p-8">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-medium uppercase tracking-wider text-text-faint">Question {position} of {questions.length}</p>
            <Badge tone={current.importance === "essential" ? "unfavorable" : "uncertain"}>
              {current.importance === "essential" ? "Needed for the forecast" : "Improves the forecast"}
            </Badge>
          </div>
          <h2 className="mt-4 text-xl font-semibold leading-snug text-text">{current.text}</h2>
          <p className="mt-3 flex gap-2 text-sm text-text-muted">
            <HelpCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> <span><span className="text-text">Why this matters:</span> {current.reason}</span>
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            {current.options.length > 0 && (
              <div className="grid gap-2" role="radiogroup" aria-label="Answer options">
                {current.options.map((o) => (
                  <button
                    type="button" key={o.id} role="radio" aria-checked={option === o.id}
                    onClick={() => setOption(option === o.id ? null : o.id)}
                    className={clsx(
                      "rounded-xl px-4 py-3 text-left ring-1 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
                      option === o.id ? "bg-brand/15 ring-brand" : "bg-ink ring-ink-line hover:ring-slate-500",
                    )}
                  >
                    <span className="block text-sm font-medium text-text">{o.label}</span>
                    {o.description && <span className="mt-0.5 block text-xs text-text-muted">{o.description}</span>}
                  </button>
                ))}
              </div>
            )}
            <label className="block">
              <span className="flex items-center gap-1.5 text-xs text-text-muted">
                <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                {needsTyping ? (current.input_type === "number" || option === "other" ? "Type the amount" : "Your answer") : "Or answer in your own words"}
              </span>
              <input
                value={text} onChange={(e) => setText(e.target.value)}
                placeholder={current.input_type === "number" || option === "other" ? "e.g. 325,000" : "Type your answer"}
                className="mt-1.5 w-full rounded-lg bg-ink px-3.5 py-2.5 text-sm text-text ring-1 ring-ink-line placeholder:text-text-faint focus:outline-none focus:ring-2 focus:ring-brand"
              />
            </label>
            {error && <ErrorNote>{error}</ErrorNote>}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button type="submit" busy={busy === "submit"} disabled={!!busy}>Continue</Button>
              <Button variant="ghost" onClick={() => submit({ text: "I don't know", skip: true }, "idk")} disabled={!!busy}>I don&apos;t know</Button>
              <Button variant="ghost" onClick={() => submit({ skip: true }, "skip")} disabled={!!busy}>Skip</Button>
            </div>
            <p className="text-xs text-text-faint">Skipped questions stay visible in the outlook as unresolved assumptions.</p>
          </form>
        </Panel>
      ) : (
        <Panel className="mt-6 p-6 text-center sm:p-8">
          <CheckCircle2 className="mx-auto h-8 w-8 text-good" aria-hidden />
          <h2 className="mt-3 text-lg font-semibold text-text">Thanks. Sentinel has what it needs.</h2>
          <p className="mt-1 text-sm text-text-muted">
            {inv.ai_enabled ? "Next, the analysts and the reviewer will work through the numbers." : "Next, the forecasting engine will calculate your outlook."}
          </p>
          {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}
          <Button className="mt-5" onClick={runAnalysis} busy={busy === "continue"}>Build my outlook</Button>
        </Panel>
      )}

      {done.length > 0 && (
        <div className="mt-6">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text-faint">Your answers</h3>
          <ul className="mt-2 space-y-2">
            {done.map((q) => (
              <li key={q.id} className="rounded-lg bg-ink-panel px-4 py-3 text-sm ring-1 ring-ink-line">
                <p className="text-text-muted">{q.text}</p>
                <p className="mt-1 text-text">{q.status === "skipped" ? "Skipped (kept as an assumption)" : q.interpretation}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
