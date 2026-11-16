export type Tone = "favorable" | "unfavorable" | "uncertain" | "neutral";

export interface FileInfo {
  id: string;
  name: string;
  type: string;
  size: number;
  status: string;
  message?: string | null;
  pages?: number | null;
}

export interface Option {
  id: string;
  label: string;
  value: unknown;
  description: string;
}

export interface QuestionT {
  id: string;
  key: string;
  text: string;
  reason: string;
  importance: "essential" | "helpful" | "optional";
  input_type: "choice" | "number" | "text";
  options: Option[];
  status: "open" | "answered" | "skipped";
  answer_text?: string | null;
  interpretation?: string | null;
  changed_analysis?: boolean | null;
  change_summary?: string | null;
}

export interface Step {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "skipped" | "failed" | "waiting";
  detail?: string | null;
}

export interface Point {
  period: string;
  value: number;
  low?: number;
  high?: number;
}

export interface MetricLine {
  id: string;
  metric: string;
  label: string;
  direction: string;
  direction_confidence?: string;
  change_pct?: number | null;
  effect?: string;
  effect_reason?: string;
  tone: Tone;
  display: string;
  detail?: string | null;
  reliable: boolean;
  message?: string | null;
  sufficiency?: string;
  fact_ids: string[];
  history: Point[];
  forecast: Point[];
}

export interface ProjectLine {
  id: string;
  project: string;
  eac: number | null;
  eac_text: string;
  eac_range_text?: string | null;
  budget_text: string;
  budget_status: string;
  variance_text: string;
  outlook: string;
  tone: Tone;
  method_label?: string | null;
  method_formula?: string | null;
  reliable: boolean;
  message?: string | null;
  delay_days?: number | null;
  fact_ids: string[];
  insights: string[];
  utilization_pct?: number | null;
  percent_complete?: number | null;
}

export interface DriverT {
  id: string;
  scope: string;
  subject: string;
  title: string;
  what_changed: string;
  magnitude?: string | null;
  period_compared?: string | null;
  evidence_type: string;
  effect_on_forecast: string;
  support: string;
  fact_ids: string[];
  impact?: string;
}

export interface Reason {
  driver_id: string;
  title: string;
  text: string;
  magnitude?: string | null;
  fact_ids: string[];
  evidence_type: string;
  support: string;
}

export interface Finding {
  claim_id: string;
  title: string;
  statement: string;
  metric: string;
  direction: string;
  business_effect: string;
  evidence_type: string;
  support: string;
  cited_fact_ids: string[];
  cited_calculation_ids: string[];
  check?: { status: string; unknown_ids: string[]; unverified_numbers: string[] } | null;
  review?: { assessment: string; comment: string } | null;
}

export interface AgentReview {
  ai_enabled: boolean;
  failed: string[];
  emily: { summary: string; outlook: string; findings: Finding[]; uncertainties: string[]; watch_items: string[] } | null;
  sebas: {
    projects: { project: string; summary: string; status: string; findings: Finding[]; risks: string[]; uncertainties: string[] }[];
    cross_project_notes: string[];
  } | null;
  alex: {
    overall_verdict: string;
    verdict_reason: string;
    recommended_confidence: string;
    company_verdict: string;
    project_verdicts: { project: string; verdict: string; reason: string }[];
    challenges: { target: string; issue: string; severity: string }[];
    false_precision: string[];
    insufficient_data: string[];
    recommended_next_step: string;
  } | null;
  runs: { agent: string; status: string; model?: string | null; duration_ms?: number | null; error?: string | null; at?: string }[];
}

export interface Outlook {
  company_name: string;
  currency: string;
  as_of: string | null;
  as_of_label: string;
  horizon_months: number;
  forecast_window: { start: string | null; end: string | null; label: string | null };
  overall: { label: string; tone: Tone; headline: string; qualifier?: string | null; reviewer_verdict: string };
  company: MetricLine[];
  company_other: MetricLine[];
  projects: ProjectLine[];
  reasons: Reason[];
  what_could_change: string[];
  data_quality: {
    label: string;
    score: number;
    limitations: string[];
    important_limitation?: string | null;
    history_months: number;
    issues: { severity: string; message: string; fact_ids: string[] }[];
    conflicts: { id: string; description: string; fact_ids: string[]; resolved_fact_id?: string | null }[];
    duplicates: { id: string; kind: string; description: string; fact_ids: string[] }[];
  };
  next_step: string;
  why: { plain_language: string; movements: { id: string; title: string; tone: Tone; summary: string; drivers: DriverT[] }[] };
  methodology: {
    id: string;
    label: string;
    method: string;
    model?: string | null;
    reason?: string;
    formula?: string | null;
    history_months?: number;
    sufficiency?: string;
    validated?: boolean;
    validation?: { model: string; label: string; mae: number; mape?: number | null; n_origins: number }[];
    assumptions?: string[];
    methods?: { name: string; label: string; eac: number; formula: string; evidence_type: string; note: string }[];
  }[];
  assumptions: string[];
  answers: {
    id: string;
    text: string;
    status: string;
    answer?: string | null;
    interpretation?: string | null;
    changed_analysis?: boolean | null;
    change_summary?: string | null;
    importance: string;
  }[];
  files: { id: string; name: string; type: string; pages?: number | null; status: string }[];
  agent_review?: AgentReview;
}

export interface Investigation {
  id: string;
  name: string;
  status: "draft" | "extracting" | "awaiting_answers" | "analyzing" | "complete" | "error";
  stage_message?: string | null;
  error?: string | null;
  is_sample: boolean;
  created_at: string;
  updated_at: string;
  horizon_months?: number | null;
  ai_enabled: boolean;
  model: string;
  files: FileInfo[];
  questions: QuestionT[];
  progress: Step[];
  extraction_summary: {
    company_name?: string | null;
    currency?: string | null;
    as_of?: string | null;
    projects: string[];
    facts: number;
    conflicts: number;
    duplicates: number;
  } | null;
  outlook: Outlook | null;
  scenarios: ScenarioResult[];
}

export interface InvestigationSummary {
  id: string;
  name: string;
  status: string;
  is_sample: boolean;
  created_at: string;
  updated_at: string;
  files: number;
  headline?: string | null;
}

export interface FactT {
  id: string;
  entity_type: string;
  entity: string;
  metric: string;
  period?: string | null;
  dimension?: string | null;
  value?: number | null;
  text_value?: string | null;
  currency?: string | null;
  unit: string;
  qualifier?: string | null;
  extraction_method: string;
  confidence: string;
  superseded: boolean;
  source: { file_id: string; file_name: string; page?: number | null; sheet?: string | null; row?: number | null; record_id?: string | null; excerpt?: string | null };
  corroborating_sources: { file_id: string; file_name: string; page?: number | null; sheet?: string | null; row?: number | null; record_id?: string | null }[];
  attributes: Record<string, unknown>;
}

export interface ScenarioInputT {
  revenue_change_pct: number;
  opex_change_pct: number;
  supplier_cost_change_pct: number;
  extra_monthly_hiring_cost: number;
  project_delay_weeks: number;
  delayed_project: string | null;
}

export interface ScenarioResult {
  id?: string;
  currency?: string;
  input: ScenarioInputT;
  horizon_months: number;
  lines: { key: string; label: string; original: number | null; new: number | null; difference: number | null; unit: string; favorable: boolean | null }[];
  explanations: string[];
  assumptions: string[];
  changed: string[];
}
