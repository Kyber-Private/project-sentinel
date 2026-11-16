"use client";

import clsx from "clsx";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, FileText, FileType2, FolderOpen, Info, Loader2, Trash2, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { bytes } from "@/lib/format";
import type { FileInfo, Investigation, InvestigationSummary } from "@/types";
import { Button, ErrorNote, Logo } from "@/components/ui";

const ACCEPT = ".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt";

function FileIcon({ type }: { type: string }) {
  if (["xlsx", "xls", "csv"].includes(type)) return <FileSpreadsheet className="h-5 w-5 text-good" aria-hidden />;
  if (type === "pdf") return <FileType2 className="h-5 w-5 text-risk" aria-hidden />;
  return <FileText className="h-5 w-5 text-brand" aria-hidden />;
}

export function UploadScreen() {
  const router = useRouter();
  const [inv, setInv] = useState<Investigation | null>(null);
  const [pending, setPending] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState<"analyze" | "sample" | null>(null);
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);
  const [setupMsg, setSetupMsg] = useState<string | null>(null);
  const [recent, setRecent] = useState<InvestigationSummary[]>([]);
  const [backendDown, setBackendDown] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshRecent = useCallback(() => {
    api.list().then(setRecent).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.health()
      .then((h) => { setAiEnabled(h.ai_enabled); setSetupMsg(h.setup_message); })
      .catch(() => setBackendDown(true));
    refreshRecent();
  }, [refreshRecent]);

  const ensureInvestigation = async (): Promise<Investigation> => {
    if (inv) return inv;
    const created = await api.create();
    setInv(created);
    return created;
  };

  const addFiles = async (list: FileList | File[]) => {
    const files = Array.from(list);
    if (!files.length) return;
    setErrors([]);
    setPending(files.map((f) => f.name));
    try {
      const target = await ensureInvestigation();
      const res = await api.upload(target.id, files);
      setInv(res.investigation);
      setErrors(res.errors.map((e) => `${e.name}: ${e.error}`));
    } catch (e) {
      setErrors([(e as Error).message]);
    } finally {
      setPending([]);
    }
  };

  const removeFile = async (f: FileInfo) => {
    if (!inv) return;
    try {
      setInv(await api.removeFile(inv.id, f.id));
    } catch (e) {
      setErrors([(e as Error).message]);
    }
  };

  const loadSample = async () => {
    setBusy("sample");
    setErrors([]);
    try {
      if (inv && inv.files.length === 0) await api.remove(inv.id).catch(() => undefined);
      setInv(await api.sample());
      refreshRecent();
    } catch (e) {
      setErrors([(e as Error).message]);
    } finally {
      setBusy(null);
    }
  };

  const analyze = async () => {
    if (!inv) return;
    setBusy("analyze");
    try {
      await api.analyze(inv.id);
      router.push(`/investigation/${inv.id}`);
    } catch (e) {
      setErrors([(e as Error).message]);
      setBusy(null);
    }
  };

  const deleteRecent = async (id: string) => {
    if (!confirm("Delete this investigation and its uploaded files?")) return;
    await api.remove(id).catch(() => undefined);
    if (inv?.id === id) setInv(null);
    refreshRecent();
  };

  const files = inv?.files ?? [];

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col px-5 pb-16 pt-8 sm:pt-10">
      <header className="flex items-center justify-between">
        <Logo />
        {aiEnabled !== null && (
          <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ring-1",
            aiEnabled ? "text-good ring-good/30" : "text-warn ring-warn/30")}>
            <span className={clsx("h-1.5 w-1.5 rounded-full", aiEnabled ? "bg-good" : "bg-warn")} />
            {aiEnabled ? "AI agents ready" : "AI agents off"}
          </span>
        )}
      </header>

      <section className="mt-14 text-center sm:mt-20">
        <h1 className="text-4xl font-semibold tracking-tight text-text sm:text-5xl">Understand where your business is heading.</h1>
        <p className="mx-auto mt-3 max-w-xl text-base text-text-muted">
          Upload your financial and project documents to receive an AI-powered financial outlook.
        </p>
      </section>

      {backendDown && (
        <div className="mt-8"><ErrorNote>Cannot reach the Sentinel backend. Start it with <code>uvicorn main:app --port 8000</code> in the backend folder.</ErrorNote></div>
      )}
      {aiEnabled === false && setupMsg && (
        <div className="mt-8 flex gap-3 rounded-xl bg-warn/10 px-4 py-3 text-sm text-warn ring-1 ring-warn/30">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
          <p>{setupMsg}</p>
        </div>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
        className={clsx(
          "mt-10 rounded-3xl border-2 border-dashed px-6 py-14 text-center shadow-sm transition",
          drag ? "border-brand bg-brand/5" : "border-ink-line bg-white hover:border-brand/60",
        )}
      >
        <UploadCloud className="mx-auto h-10 w-10 text-brand" aria-hidden />
        <p className="mt-4 text-base font-medium text-text">Drag and drop your documents here</p>
        <p className="mt-1 text-sm text-text-muted">PDF, Word, Excel, CSV, or text. Several files at once is best.</p>
        <Button variant="secondary" className="mt-5" onClick={() => inputRef.current?.click()}>
          <FolderOpen className="h-4 w-4" aria-hidden /> Choose files
        </Button>
        <input
          ref={inputRef} type="file" multiple accept={ACCEPT} className="sr-only" aria-label="Choose files to upload"
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />
      </div>

      {(files.length > 0 || pending.length > 0) && (
        <ul className="mt-6 divide-y divide-ink-line overflow-hidden rounded-xl bg-ink-panel ring-1 ring-ink-line" aria-label="Uploaded files">
          {files.map((f) => (
            <li key={f.id} className="flex items-center gap-3 px-4 py-3">
              <FileIcon type={f.type} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-text">{f.name}</p>
                <p className="text-xs text-text-muted">{f.type.toUpperCase()} · {bytes(f.size)}</p>
              </div>
              <span className="inline-flex items-center gap-1 text-xs text-good"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Ready</span>
              <button onClick={() => removeFile(f)} className="rounded-md p-1.5 text-text-muted hover:bg-ink-raised hover:text-risk focus:outline-none focus-visible:ring-2 focus-visible:ring-brand" aria-label={`Remove ${f.name}`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
          {pending.map((name) => (
            <li key={name} className="flex items-center gap-3 px-4 py-3">
              <Loader2 className="h-5 w-5 animate-spin text-brand" aria-hidden />
              <p className="flex-1 truncate text-sm text-text-muted">{name}</p>
              <span className="text-xs text-text-muted">Uploading</span>
            </li>
          ))}
        </ul>
      )}

      {errors.length > 0 && (
        <div className="mt-4 space-y-2">{errors.map((e) => <ErrorNote key={e}>{e}</ErrorNote>)}</div>
      )}

      <div className="mt-8 flex flex-col items-center gap-3">
        <Button onClick={analyze} disabled={!files.length || pending.length > 0} busy={busy === "analyze"} className="w-full px-8 py-3 text-base sm:w-auto">
          Analyze my business
        </Button>
        <button onClick={loadSample} disabled={busy !== null} className="text-sm text-text-muted underline-offset-4 hover:text-text hover:underline disabled:opacity-50">
          {busy === "sample" ? "Loading sample documents..." : "Or load a fictional sample company (Nova Industries)"}
        </button>
      </div>

      <p className="mt-10 flex items-start gap-2 text-xs leading-relaxed text-text-faint">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        This is a hackathon prototype. Do not upload sensitive real-world financial data unless your organization has approved this environment.
        Uploaded documents are treated as data only, never as instructions.
      </p>

      {recent.length > 0 && (
        <section className="mt-12">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-faint">Recent investigations</h2>
          <ul className="mt-3 divide-y divide-ink-line rounded-xl bg-ink-panel ring-1 ring-ink-line">
            {recent.slice(0, 6).map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-4 py-3">
                <a href={`/investigation/${r.id}`} className="min-w-0 flex-1 hover:underline">
                  <p className="truncate text-sm text-text">{r.name}</p>
                  <p className="text-xs text-text-muted">
                    {new Date(r.updated_at).toLocaleString()} · {r.files} file(s) · {r.headline ?? r.status.replace("_", " ")}
                  </p>
                </a>
                <button onClick={() => deleteRecent(r.id)} className="rounded-md p-1.5 text-text-muted hover:bg-ink-raised hover:text-risk" aria-label={`Delete ${r.name}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
