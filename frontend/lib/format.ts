import type { Tone } from "@/types";

const SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", GBP: "£", CAD: "CA$", AUD: "A$" };

export function money(v: number | null | undefined, currency = "USD", signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  const sym = SYMBOLS[currency] ?? "";
  const sign = v < 0 ? "-" : signed && v > 0 ? "+" : "";
  const body = Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
  return sym ? `${sign}${sym}${body}` : `${sign}${body} ${currency}`;
}

export function compactMoney(v: number, currency = "USD"): string {
  const sym = SYMBOLS[currency] ?? "";
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}${sym}${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}${sym}${(a / 1e3).toFixed(0)}k`;
  return `${sign}${sym}${a.toFixed(0)}`;
}

export function monthLabel(p?: string | null): string {
  if (!p) return "";
  const [y, m] = p.split("-").map(Number);
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[m - 1]} ${y}`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const toneText: Record<Tone, string> = {
  favorable: "text-good",
  unfavorable: "text-risk",
  uncertain: "text-warn",
  neutral: "text-text-muted",
};

export const toneBg: Record<Tone, string> = {
  favorable: "bg-good/10 text-good ring-good/30",
  unfavorable: "bg-risk/10 text-risk ring-risk/30",
  uncertain: "bg-warn/10 text-warn ring-warn/30",
  neutral: "bg-slate-500/10 text-text-muted ring-slate-500/30",
};

export const toneDot: Record<Tone, string> = {
  favorable: "bg-good",
  unfavorable: "bg-risk",
  uncertain: "bg-warn",
  neutral: "bg-slate-500",
};

export const metricLabel = (m: string) =>
  ({
    revenue: "Revenue", cogs: "Cost of goods sold", gross_profit: "Gross profit", operating_expenses: "Operating expenses",
    operating_profit: "Operating profit", net_profit: "Net profit", cash_balance: "Cash balance", cash_flow: "Net cash flow",
    budget_approved: "Approved budget", budget_revised: "Revised budget (mentioned)", actual_cost: "Actual cost to date",
    committed_cost: "Remaining commitments", forecast_at_completion: "Forecast at completion", percent_complete: "Percent complete",
    start_date: "Start date", planned_completion: "Planned completion", forecast_completion: "Forecast completion",
    project_cost: "Monthly project cost", expense_category: "Expense category", supplier_invoice: "Supplier invoice",
    supplier_price_change_pct: "Supplier price change", open_purchase_order: "Open purchase order", business_note: "Note in document",
    milestone: "Milestone", change_request: "Change request",
  })[m] ?? m.replace(/_/g, " ");
