"use client";

import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compactMoney, money, monthLabel } from "@/lib/format";
import type { MetricLine } from "@/types";

/** History (solid) and forecast (dashed) with the approximate range shaded. */
export function MetricChart({ line, currency }: { line: MetricLine; currency: string }) {
  const hist = line.history.slice(-18).map((p) => ({ period: p.period, actual: p.value }));
  const lastActual = hist[hist.length - 1];
  const fc = line.forecast.map((p) => ({ period: p.period, forecast: p.value, range: [p.low ?? p.value, p.high ?? p.value] as [number, number] }));
  const data = [
    ...hist.slice(0, -1),
    lastActual ? { ...lastActual, forecast: lastActual.actual, range: [lastActual.actual, lastActual.actual] as [number, number] } : undefined,
    ...fc,
  ].filter(Boolean) as { period: string; actual?: number; forecast?: number; range?: [number, number] }[];
  if (!data.length) return null;
  return (
    <div className="h-52 w-full" role="img" aria-label={`${line.label}: history and forecast chart`}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#E1E7F0" vertical={false} />
          <XAxis dataKey="period" tickFormatter={(p: string) => monthLabel(p).replace(" 20", " '")} tick={{ fill: "#62718A", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis tickFormatter={(v: number) => compactMoney(v, currency)} tick={{ fill: "#62718A", fontSize: 11 }} axisLine={false} tickLine={false} width={60} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{ background: "#FFFFFF", border: "1px solid #E1E7F0", borderRadius: 12, color: "#17233F", fontSize: 12 }}
            labelFormatter={(p: unknown) => monthLabel(String(p))}
            formatter={(v: unknown, name: string) => {
              if (Array.isArray(v)) return [`${money(v[0], currency)} to ${money(v[1], currency)}`, "Range"];
              return [money(v as number, currency), name === "actual" ? "Actual" : "Forecast"];
            }}
          />
          <Area type="monotone" dataKey="range" stroke="none" fill="#635BFF" fillOpacity={0.12} isAnimationActive={false} />
          <Line type="monotone" dataKey="actual" stroke="#17233F" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="forecast" stroke="#635BFF" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
