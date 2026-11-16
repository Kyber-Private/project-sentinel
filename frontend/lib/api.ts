import type { FactT, Investigation, InvestigationSummary, ScenarioInputT, ScenarioResult } from "@/types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, cache: "no-store" });
  } catch {
    throw new Error("Cannot reach the Sentinel backend. Make sure it is running on port 8000.");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    if (res.status === 500 && detail.includes("ECONNREFUSED")) detail = "The Sentinel backend is not running.";
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<{ ok: boolean; ai_enabled: boolean; model: string; setup_message: string | null }>("/api/health"),
  list: () => request<InvestigationSummary[]>("/api/investigations"),
  create: (name?: string) => request<Investigation>("/api/investigations", json({ name })),
  sample: () => request<Investigation>("/api/investigations/sample", { method: "POST" }),
  get: (id: string) => request<Investigation>(`/api/investigations/${id}`),
  remove: (id: string) => request<{ deleted: boolean }>(`/api/investigations/${id}`, { method: "DELETE" }),
  upload: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<{ added: unknown[]; errors: { name: string; error: string }[]; investigation: Investigation }>(
      `/api/investigations/${id}/files`,
      { method: "POST", body: fd },
    );
  },
  removeFile: (id: string, fileId: string) =>
    request<Investigation>(`/api/investigations/${id}/files/${fileId}`, { method: "DELETE" }),
  analyze: (id: string) => request<Investigation>(`/api/investigations/${id}/analyze`, { method: "POST" }),
  answer: (id: string, qid: string, body: { text?: string; option_id?: string; skip?: boolean }) =>
    request<{ result: { interpretation: string; change_summary?: string | null }; investigation: Investigation }>(
      `/api/investigations/${id}/questions/${qid}/answer`,
      json(body),
    ),
  reopen: (id: string, qid: string) => request<Investigation>(`/api/investigations/${id}/questions/${qid}/reopen`, { method: "POST" }),
  continue: (id: string) => request<Investigation>(`/api/investigations/${id}/continue`, { method: "POST" }),
  horizon: (id: string, months: number) => request<Investigation>(`/api/investigations/${id}/horizon`, json({ months })),
  facts: (id: string, ids: string[]) => request<FactT[]>(`/api/investigations/${id}/facts?ids=${encodeURIComponent(ids.join(","))}`),
  scenario: (id: string, input: ScenarioInputT) => request<ScenarioResult>(`/api/investigations/${id}/scenarios`, json(input)),
  reportUrl: (id: string) => `/api/investigations/${id}/report.pdf`,
  fileUrl: (id: string, fileId: string, page?: number | null) =>
    `/api/investigations/${id}/files/${fileId}/download${page ? `#page=${page}` : ""}`,
};

export const RUNNING = ["extracting", "analyzing"];
