"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Kind = "minutes" | "actions" | "decisions";
type Entry = { id: string; created_at: string; event_at: string | null; event_action: string | null; operation_key: string; status: string; reason: string; transcript_id: string | null; run: { id: string; status: string; error: string | null } | null };
type Page = { items: Entry[]; next_before: string | null };
const operations: Record<string, { name: string; kind: Kind }> = { "meeting.minutes.draft": { name: "纪要草稿", kind: "minutes" }, "meeting.actions.draft": { name: "行动项草稿", kind: "actions" }, "meeting.decisions.draft": { name: "决策草稿", kind: "decisions" } };
const actions: Record<string, string> = { status_completed: "会议结束", transcript_uploaded: "转写上传", transcript_original_restored: "转写原文补全", transcript_speakers_confirmed: "说话人核对" };
const triggers: Record<string, string> = { queued: "已排队", reused: "复用已有运行", skipped: "本次未触发" };
const runs: Record<string, string> = { queued: "等待运行", debouncing: "等待合并", running: "正在生成", waiting_input: "等待补充资料", succeeded: "运行完成", degraded: "未能完整完成", failed: "运行失败" };
const errors: Record<string, string> = { MODEL_UNAVAILABLE: "模型当前不可用", MEETING_READING_EXECUTION_FAILED: "会议资料生成未完成", MEETING_TRANSCRIPT_CHANGED: "转写已有变化，请核对最新资料", BUDGET_EXCEEDED: "本次运行预算不足", MEETING_EVENT_AUTHORITY_CHANGED: "自动处理政策或项目起草范围已变化，本次已停止", MEETING_EVENT_SOURCE_CHANGED: "原会议或转写资料已变化，本次已停止" };
function string(value: unknown): string { if (typeof value !== "string") throw new Error("触发记录不完整，请刷新重试"); return value; }
function nullable(value: unknown): string | null { return value === null ? null : string(value); }
function parse(value: unknown): Page {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("触发历史不完整，请刷新重试");
  return { next_before: nullable(value.next_before), items: value.items.map(row => {
    if (!isRecord(row) || (row.run !== null && !isRecord(row.run))) throw new Error("触发记录不完整，请刷新重试");
    return { id: string(row.id), created_at: string(row.created_at), event_at: nullable(row.event_at), event_action: nullable(row.event_action), operation_key: string(row.operation_key), status: string(row.status), reason: string(row.reason), transcript_id: nullable(row.transcript_id), run: row.run === null ? null : { id: string(row.run.id), status: string(row.run.status), error: nullable(row.run.error) } };
  }) };
}
async function request(path: string): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store" });
  const body: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "记录暂不可用，请稍后重试");
  return body;
}
function Source({ path }: { path: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function load() {
    setBusy(true); setError(null);
    try {
      const value = await request(path);
      if (!isRecord(value)) throw new Error("转写资料不完整");
      const text = nullable(value.content);
      if (live.current) setContent(text ?? "此历史转写尚未保存完整原文，请到会议转写栏核对片段。");
    } catch (failure) { if (live.current) setError(failure instanceof Error ? failure.message : "原文读取失败"); }
    finally { if (live.current) setBusy(false); }
  }
  return <details className="rounded-lg border p-2" onToggle={event => { if (event.currentTarget.open && content === null && !busy) void load(); }}><summary className="cursor-pointer text-xs text-primary">查看本次转写原文</summary>{busy && <p role="status" className="mt-2 text-xs">读取原文中…</p>}{error && <div className="mt-2"><p role="alert" className="text-xs text-destructive">{error}</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>重试读取原文</Button></div>}{content !== null && <p className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs leading-5">{content}</p>}</details>;
}

export function AiMeetingEventHistory(props: { projectId: string; meetingId: string; onOpenDrafts: (kind: Kind) => void }) {
  return <History key={`${props.projectId}:${props.meetingId}`} {...props} />;
}
function History({ projectId, meetingId, onOpenDrafts }: { projectId: string; meetingId: string; onOpenDrafts: (kind: Kind) => void }) {
  const [data, setData] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(true);
  const pending = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const base = `/api/projects/${projectId}/meetings/${meetingId}`;
  async function load(older = false) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const page = parse(await request(`${base}/ai-event-history${older && data?.next_before ? `?before=${encodeURIComponent(data.next_before)}` : ""}`));
      if (active.current) setData(previous => older && previous ? { ...page, items: [...previous.items, ...page.items.filter(row => !previous.items.some(old => old.id === row.id))] } : page);
    } catch (failure) { if (active.current) { setError(failure instanceof Error ? failure.message : "触发历史读取失败"); if (!older) setData(null); } }
    finally { pending.current = false; if (active.current) setBusy(false); }
  }
  return <details className="rounded-lg border p-2 sm:p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer text-sm font-medium">会后 AI 触发历史</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs leading-5 text-muted-foreground">会议结束、转写补齐或说话人核对后，按租户自动模式和项目起草范围安排生成。这里可回查处理结果与原文；正式发布仍由具名人员办理。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新触发历史</Button>
      {busy && <p role="status" className="text-xs text-muted-foreground">正在读取触发记录…</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {data?.items.length === 0 && <p className="text-xs text-muted-foreground">暂无会后触发记录。</p>}
      {data?.items.map(item => <article key={item.id} className="space-y-2 rounded-lg border p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h4 className="text-sm font-medium">{operations[item.operation_key]?.name ?? "会议草稿"}</h4><time className="text-xs text-muted-foreground" dateTime={item.event_at ?? item.created_at}>{new Date(item.event_at ?? item.created_at).toLocaleString("zh-CN")}</time></div>
        <p className="text-xs text-muted-foreground">触发事件：{actions[item.event_action ?? ""] ?? "会议资料变化"}</p>
        <p className="text-xs">当时触发结果：{triggers[item.status] ?? "状态待核对"}</p>
        <p className={`text-xs leading-5 ${item.status === "skipped" ? "text-primary" : "text-muted-foreground"}`}>{item.reason}</p>
        {item.run ? <div className="space-y-1 border-l-2 pl-2"><p className="text-xs">当前运行：{runs[item.run.status] ?? "状态待核对"}</p>{item.run.error && <><p className="text-xs text-primary">{errors[item.run.error] ?? "本次生成未能完成，请核对运行配置与原始资料。"}</p><details className="text-xs text-muted-foreground"><summary className="cursor-pointer">查看失败标识</summary><p className="mt-1 break-all">{item.run.error}</p></details></>}</div> : <p className="text-xs text-muted-foreground">本次没有关联运行。</p>}
        {item.transcript_id && <Source key={item.transcript_id} path={`${base}/transcripts/${item.transcript_id}`} />}
        {item.run && operations[item.operation_key] && <Button size="sm" variant="outline" onClick={() => onOpenDrafts(operations[item.operation_key].kind)}>查看对应{operations[item.operation_key].name}</Button>}
      </article>)}
      {data?.next_before && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早的触发记录</Button>}
    </div>
  </details>;
}
