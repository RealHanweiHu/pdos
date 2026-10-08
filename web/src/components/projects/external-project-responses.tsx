"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

import { fetchNpiSnapshot, NpiRequestError } from "./project-npi-api";

type ExternalRole = "supplier" | "customer";
type ResponseStatus = "approved" | "rejected";
type SignoffStatus = "pending" | ResponseStatus | "waived";
type Draft = { status: ResponseStatus | ""; note: string };
type Signoff = {
  id: string;
  title: string;
  audience: ExternalRole;
  status: SignoffStatus;
  sampleIds: string[];
  updatedAt: string;
  dueDate: string | null;
  responseNote: string | null;
  respondedAt: string | null;
};

export type ExternalProjectResponsesProps = { projectId: string; role: string };

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const field = "mt-1 min-h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";
const labels: Record<SignoffStatus, string> = {
  pending: "待回应",
  approved: "已回应 · 确认符合",
  rejected: "已回应 · 退回核对",
  waived: "已结束 · 无须回应",
};

function incomplete(): never {
  throw new NpiRequestError("EXTERNAL_RESPONSE_INCOMPLETE", "请求资料不完整，暂时无法回应。请刷新重新读取。");
}

function stamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) incomplete();
  return value;
}

function optionalText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") incomplete();
  return value;
}

// Read only the authorized signoff projection. Build/sample/test collections
// are deliberately never used to enrich an external collaborator's request.
async function readSignoffs(projectId: string, role: ExternalRole): Promise<Signoff[]> {
  const snapshot = await fetchNpiSnapshot(projectId);
  const values: unknown = snapshot.sample_signoffs;
  if (!Array.isArray(values)) incomplete();
  const seen = new Set<string>();
  const signoffs: Signoff[] = [];
  for (const value of values) {
    if (!isRecord(value) || value.audience !== role) continue;
    if (typeof value.id !== "string" || !uuid.test(value.id) || seen.has(value.id)
      || value.project_id !== projectId || typeof value.title !== "string" || !value.title.trim()
      || !["pending", "approved", "rejected", "waived"].includes(String(value.status))
      || !Array.isArray(value.sample_ids) || value.sample_ids.length === 0
      || value.sample_ids.some(id => typeof id !== "string" || !uuid.test(id))
      || new Set(value.sample_ids).size !== value.sample_ids.length) incomplete();
    const status = value.status as SignoffStatus;
    const respondedAt = value.responded_at === null || value.responded_at === undefined
      ? null : stamp(value.responded_at);
    if (status !== "pending" && !respondedAt) incomplete();
    const dueDate = optionalText(value.due_date);
    if (dueDate && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) incomplete();
    seen.add(value.id);
    signoffs.push({
      id: value.id, title: value.title, audience: role, status,
      sampleIds: value.sample_ids as string[], updatedAt: stamp(value.updated_at),
      dueDate, responseNote: optionalText(value.response_note), respondedAt,
    });
  }
  return signoffs;
}

function messageFor(failure: unknown, responding = false): string {
  if (failure instanceof NpiRequestError) {
    if (["PROJECT_ACCESS_DENIED", "NPI_AUDIENCE_DENIED", "ACTION_DENIED", "FORBIDDEN"].includes(failure.code)) {
      return "当前身份无权读取或回应这条请求。请刷新查看仍可访问的请求。";
    }
    if (failure.code === "NPI_CONFLICT") return "请求已变化或已被回应，请刷新核对最新记录。";
    if (failure.code === "NPI_NOT_FOUND") return "这条请求已不可读取，请刷新请求列表。";
    if (failure.code === "EXTERNAL_RESPONSE_INCOMPLETE") return failure.message;
  }
  return responding
    ? "未能确认本次回应结果。输入已保留，请先刷新核对记录，再决定是否重新提交。"
    : "回应请求暂时无法读取，请刷新重试。";
}

async function respond(projectId: string, signoff: Signoff, role: ExternalRole, draft: Draft): Promise<void> {
  if (signoff.audience !== role || signoff.status !== "pending"
    || (draft.status !== "approved" && draft.status !== "rejected") || draft.note.length > 20_000) {
    throw new NpiRequestError("NPI_AUDIENCE_DENIED", "当前请求不可回应");
  }
  // The existing service accepts only status/note. The original signoff is
  // addressed by its project + id; server locking rechecks pending and audience.
  const response = await fetch(`/api/projects/${projectId}/npi/sample-signoffs/${signoff.id}/respond`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: draft.status, note: draft.note.trim() || null }),
  });
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = isRecord(value) && isRecord(value.detail) ? value.detail : null;
    const code = response.status === 401 || response.status === 403
      ? "NPI_AUDIENCE_DENIED"
      : detail && typeof detail.code === "string" ? detail.code : "NPI_REQUEST_FAILED";
    throw new NpiRequestError(code, "回应未完成");
  }
  if (!isRecord(value) || value.id !== signoff.id || value.project_id !== projectId
    || value.audience !== role || value.status !== draft.status) incomplete();
  stamp(value.updated_at);
  stamp(value.responded_at);
}

function ResponseCard({ signoff, draft, blocked, submitting, onDraft, onSubmit }: {
  signoff: Signoff; draft: Draft; blocked: boolean; submitting: boolean;
  onDraft: (draft: Draft) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const id = useId();
  const pending = signoff.status === "pending";
  return <article aria-labelledby={`${id}-title`} className="min-w-0 rounded-lg border bg-card p-4 sm:p-5">
    <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
      <h4 id={`${id}-title`} className="min-w-0 flex-1 break-words text-sm font-semibold">{signoff.title}</h4>
      <span className={`rounded-md px-2 py-1 text-xs ${pending ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>{labels[signoff.status]}</span>
    </div>
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <p>{signoff.dueDate ? <>请于 <time dateTime={signoff.dueDate}>{signoff.dueDate}</time> 前回应</> : "未设置回应期限"}</p>
      <p>关联样机 {signoff.sampleIds.length} 台</p>
    </div>
    <details className="mt-3 text-xs">
      <summary className="min-h-11 cursor-pointer content-center rounded-md text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50">查看本次回应对象与证据范围</summary>
      <div className="space-y-2 border-t pt-3 text-muted-foreground">
        <p>本次可读取的资料为此请求及以下样机引用。请按双方约定核对实物与资料后回应。</p>
        <p className="break-all">请求编号：{signoff.id}</p>
        <p>记录更新时间：<time dateTime={signoff.updatedAt}>{new Date(signoff.updatedAt).toLocaleString("zh-CN")}</time></p>
        <ul aria-label="本次请求关联的样机引用" className="space-y-1">{signoff.sampleIds.map(sampleId => <li className="break-all" key={sampleId}>{sampleId}</li>)}</ul>
      </div>
    </details>
    {pending ? <form className="mt-3 space-y-3 border-t pt-4" aria-label={`回应 ${signoff.title}`} onSubmit={onSubmit}>
      <label htmlFor={`${id}-status`} className="block text-sm font-medium">回应结果
        <select id={`${id}-status`} required autoComplete="off" className={field} value={draft.status} disabled={blocked} onChange={event => {
          const status = event.target.value;
          onDraft({ ...draft, status: status === "approved" || status === "rejected" ? status : "" });
        }}>
          <option value="">请选择本次回应结果</option>
          <option value="approved">确认符合</option>
          <option value="rejected">退回核对</option>
        </select>
      </label>
      <label htmlFor={`${id}-note`} className="block text-sm font-medium">回应说明（选填）
        <textarea id={`${id}-note`} rows={3} maxLength={20000} autoComplete="off" aria-describedby={`${id}-help`} className={`${field} resize-y`} value={draft.note} disabled={blocked} onChange={event => onDraft({ ...draft, note: event.target.value })} />
      </label>
      <p id={`${id}-help`} className="text-xs text-muted-foreground">可注明核对依据或需要项目团队处理的问题。回应后将保留结果与说明。</p>
      <Button type="submit" className="min-h-11 w-full sm:w-auto" disabled={blocked || !draft.status}>
        {submitting ? "正在提交并核对…" : "提交本次回应"}
      </Button>
    </form> : <div className="mt-3 space-y-2 border-t pt-4 text-sm">
      {signoff.responseNote ? <p className="whitespace-pre-wrap break-words">{signoff.responseNote}</p> : <p className="text-muted-foreground">未填写回应说明。</p>}
      {signoff.respondedAt && <p className="text-xs text-muted-foreground">记录时间：<time dateTime={signoff.respondedAt}>{new Date(signoff.respondedAt).toLocaleString("zh-CN")}</time></p>}
    </div>}
  </article>;
}

function ExternalResponseWorkspace({ projectId, role }: { projectId: string; role: ExternalRole }) {
  const id = useId();
  const [signoffs, setSignoffs] = useState<Signoff[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const busy = useRef(false);
  const active = useRef(true);
  const sequence = useRef(0);

  useEffect(() => {
    let cancelled = false;
    active.current = true;
    const request = ++sequence.current;
    void readSignoffs(projectId, role).then(next => {
      if (cancelled || request !== sequence.current) return;
      setSignoffs(next); setState("ready");
    }).catch(failure => {
      if (cancelled || request !== sequence.current) return;
      setError(messageFor(failure)); setState("error");
    });
    return () => { cancelled = true; active.current = false; sequence.current += 1; };
  }, [projectId, role]);

  async function refresh() {
    if (busy.current) return;
    busy.current = true;
    const request = ++sequence.current;
    setState("loading"); setError(null); setNotice(null);
    try {
      const next = await readSignoffs(projectId, role);
      if (!active.current || request !== sequence.current) return;
      setSignoffs(next); setState("ready");
    } catch (failure) {
      if (!active.current || request !== sequence.current) return;
      setSignoffs([]); setError(messageFor(failure)); setState("error");
    } finally {
      if (active.current && request === sequence.current) busy.current = false;
    }
  }

  async function submit(signoff: Signoff, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const draft = drafts[signoff.id];
    if (busy.current || state !== "ready" || !draft || !draft.status) return;
    busy.current = true;
    const request = ++sequence.current;
    setBusyId(signoff.id); setError(null); setNotice(null);
    try {
      await respond(projectId, signoff, role, draft);
      const next = await readSignoffs(projectId, role);
      if (!active.current || request !== sequence.current) return;
      const saved = next.find(value => value.id === signoff.id);
      if (!saved || saved.status !== draft.status) incomplete();
      setSignoffs(next);
      setDrafts(previous => { const remaining = { ...previous }; delete remaining[signoff.id]; return remaining; });
      setNotice(`已记录「${saved.title}」的回应：${draft.status === "approved" ? "确认符合" : "退回核对"}。`);
    } catch (failure) {
      if (!active.current || request !== sequence.current) return;
      // Hide stale records after an uncertain write or permission refusal;
      // drafts survive, but another write requires a fresh authorized read.
      setSignoffs([]); setError(messageFor(failure, true)); setState("error");
    } finally {
      if (active.current && request === sequence.current) { busy.current = false; setBusyId(null); }
    }
  }

  const pending = signoffs.filter(signoff => signoff.status === "pending");
  const answered = signoffs.filter(signoff => signoff.status !== "pending");
  function card(signoff: Signoff) {
    return <ResponseCard key={signoff.id} signoff={signoff} draft={drafts[signoff.id] ?? { status: "", note: "" }} blocked={busyId !== null} submitting={busyId === signoff.id} onDraft={draft => setDrafts(previous => ({ ...previous, [signoff.id]: draft }))} onSubmit={event => void submit(signoff, event)} />;
  }

  return <section aria-labelledby={`${id}-title`} className="min-w-0 space-y-5">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h2 id={`${id}-title`} className="text-lg font-semibold">{role === "customer" ? "客户回应" : "供应商回应"}</h2>
        <p className="mt-1 text-sm text-muted-foreground">查看发给您的样机确认请求，核对后将回应交回项目团队。</p>
      </div>
      <Button type="button" variant="outline" className="min-h-11 w-full sm:w-auto" disabled={state === "loading" || busyId !== null} onClick={() => void refresh()}>刷新请求</Button>
    </div>
    {notice && <p role="status" className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">{notice}</p>}
    {state === "loading" && <p role="status" className="py-6 text-sm text-muted-foreground">正在读取回应请求…</p>}
    {state === "error" && <div role="alert" className="space-y-3 rounded-lg border border-destructive/30 p-4">
      <p className="text-sm text-destructive">{error}</p>
      <Button type="button" variant="outline" className="min-h-11" onClick={() => void refresh()}>重新读取请求</Button>
    </div>}
    {state === "ready" && signoffs.length === 0 && <div className="rounded-lg border border-dashed px-4 py-10 text-center">
      <p className="text-sm font-medium">暂无发给您的回应请求</p>
      <p className="mt-2 text-sm text-muted-foreground">项目团队发起面向{role === "customer" ? "客户" : "供应商"}的请求后，会在这里显示。</p>
    </div>}
    {state === "ready" && signoffs.length > 0 && <>
      <section aria-labelledby={`${id}-pending`} className="space-y-3">
        <h3 id={`${id}-pending`} className="text-sm font-semibold">待回应 <span className="ml-1 font-normal text-muted-foreground">{pending.length}</span></h3>
        {pending.length ? pending.map(card) : <p className="text-sm text-muted-foreground">当前没有待回应请求。</p>}
      </section>
      {answered.length > 0 && <section aria-labelledby={`${id}-answered`} className="space-y-3">
        <h3 id={`${id}-answered`} className="text-sm font-semibold">已回应与已结束 <span className="ml-1 font-normal text-muted-foreground">{answered.length}</span></h3>
        {answered.map(card)}
      </section>}
    </>}
  </section>;
}

export function ExternalProjectResponses({ projectId, role }: ExternalProjectResponsesProps) {
  if (role !== "supplier" && role !== "customer") return <p className="text-sm text-muted-foreground">此入口仅供项目客户或供应商回应请求。</p>;
  return <ExternalResponseWorkspace key={`${projectId}:${role}`} projectId={projectId} role={role} />;
}
