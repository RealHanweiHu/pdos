"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("历史议题资料不完整");
  return value;
}
function id(value: unknown): string {
  const result = text(value);
  if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("历史议题标识不完整");
  return result;
}
function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error("历史议题清单不完整");
  return value;
}
function parse(value: unknown, projectId: string) {
  if (!isRecord(value) || typeof value.editable !== "boolean" || typeof value.scanned_count !== "number") throw new Error("复查资料不完整");
  return {
    editable: value.editable, scanned: value.scanned_count,
    next: value.next_cursor === null ? null : id(value.next_cursor),
    items: list(value.items).map(row => {
      if (!isRecord(row) || !isRecord(row.agenda)) throw new Error("历史议题资料不完整");
      const href = text(row.href);
      if (!href.startsWith(`/projects?project=${projectId}&`)) throw new Error("历史议题超出当前项目");
      return {
        id: id(row.agenda.id), meetingId: id(row.agenda.meeting_id), title: text(row.agenda.title),
        meetingTitle: text(row.meeting_title), start: text(row.meeting_start),
        basis: text(row.basis_digest), href, represented: row.represented_agenda_id !== null, reasons: list(row.reasons).map(text),
        tasks: list(row.actions).map(task => {
          if (!isRecord(task)) throw new Error("原行动资料不完整");
          return { id: id(task.id), title: text(task.title), status: text(task.status) };
        }),
      };
    }),
  };
}
type Data = ReturnType<typeof parse>;
export type ReviewCandidate = Data["items"][number];
const states: Record<string, string> = { todo: "待办", in_progress: "进行中", blocked: "受阻", done: "已完成", skipped: "已跳过", pending_approval: "待批准" };

function Candidate({ entry, projectId, editable, onCarry }: { entry: ReviewCandidate; projectId: string; editable: boolean; onCarry: (entry: ReviewCandidate, reason: string, requestId: string) => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retry = useRef<{ signature: string; id: string } | null>(null);
  async function carry() {
    const signature = JSON.stringify([entry.id, entry.basis, reason.trim()]);
    if (retry.current?.signature !== signature) retry.current = { signature, id: crypto.randomUUID() };
    setBusy(true); setError(null);
    try { await onCarry(entry, reason.trim(), retry.current.id); }
    catch (error) { setError(error instanceof Error ? error.message : "承接未完成，请刷新核对"); }
    finally { setBusy(false); }
  }
  return <article className="space-y-2 rounded-lg border p-3">
    <h5 className="text-sm font-medium">{entry.title}</h5>
    <p className="text-xs"><a className="text-primary underline" href={entry.href}>{entry.meetingTitle}</a> · {new Date(entry.start).toLocaleString("zh-CN")}</p>
    <p className="text-xs text-muted-foreground">{entry.reasons.join("；")}</p>
    {entry.tasks.length > 0 && <ul className="space-y-1 text-xs">{entry.tasks.map(task => <li key={task.id}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${task.id}`}>{task.title}</a> · {states[task.status] ?? task.status}</li>)}</ul>}
    <form className="space-y-2" onSubmit={event => { event.preventDefault(); void carry(); }}>
      <label className="block text-xs">本次需要复查什么<textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" maxLength={3000} required disabled={!editable || busy} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <Button size="sm" variant="outline" disabled={!editable || busy || !reason.trim()}>{entry.represented ? "补入已有复查议题" : "列入本次复查"}</Button>
    </form>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </article>;
}

export function MeetingReviewCandidates({ projectId, meetingId, editable, dirty, locked, onCarry }: {
  projectId: string; meetingId: string; editable: boolean; dirty: boolean; locked: boolean;
  onCarry: (entry: ReviewCandidate, reason: string, requestId: string) => Promise<void>;
}) {
  const [page, setPage] = useState<{ cursor: string | null; revision: number }>({ cursor: null, revision: 0 });
  const [data, setData] = useState<Data | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`/api/projects/${projectId}/meetings/${meetingId}/review-candidates${page.cursor ? `?cursor=${page.cursor}` : ""}`, { cache: "no-store", signal: controller.signal });
        const value: unknown = await responseBody(response).catch(() => null);
        if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "待复查事项暂不可用");
        const next = parse(value, projectId);
        if (!controller.signal.aborted) { setData(next); setError(null); }
      } catch (error) {
        if (!controller.signal.aborted) { setData(null); setError(error instanceof Error ? error.message : "复查资料读取失败"); }
      } finally { if (!controller.signal.aborted) setBusy(false); }
    }
    void load();
    return () => controller.abort();
  }, [projectId, meetingId, page]);
  function navigate(cursor: string | null) { setBusy(true); setPage(current => ({ cursor, revision: current.revision + 1 })); }
  return <section className="space-y-3">
    <h4 className="text-sm font-medium">往次会议待复查事项</h4>
    <p className="text-xs text-muted-foreground">自动核对已开始的较早会议及当前行动状态，已完整承接的议题不再列出；原会议后补行动会提示补入。列入时保留原任务和出处。</p>
    {dirty && <p className="text-xs">先保存当前议程修改，再列入复查事项。</p>}
    {busy && <p role="status" className="text-xs">正在核对历史议题…</p>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {!busy && data && <>
      {data.items.map(entry => <Candidate key={`${entry.id}:${entry.basis}`} entry={entry} projectId={projectId} editable={editable && !dirty && !locked && data.editable} onCarry={onCarry} />)}
      <p className="text-xs text-muted-foreground">本页已核对 {data.scanned} 项历史议题，发现 {data.items.length} 项待复查。{data.next ? "还有更早记录可继续核对。" : "已到本次查询末尾。"}</p>
    </>}
    <div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy || locked} onClick={() => navigate(null)}>从最新记录重新核对</Button>{data?.next && <Button size="sm" variant="outline" disabled={busy || locked} onClick={() => navigate(data.next)}>继续核对更早记录</Button>}</div>
  </section>;
}
