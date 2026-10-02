"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Item = { id: string; created_at: string; event_at: string; event_type: string; status: "queued" | "reused" | "skipped"; reason: string; source_href: string | null; run: { id: string; status: string; error: string | null } | null };
type History = { items: Item[]; next_before_id: string | null };
type Props = { projectId: string; eventRowId: number; onSelectRun: (runId: string) => void; disabled?: boolean };
const events: Record<string, string> = { TEST_FAILED: "测试失败", NPI_RECORD_CHANGED: "物料异常核对" };
const triggers = { queued: "已排队", reused: "复用已有运行", skipped: "本次未触发" };
const runs: Record<string, string> = { queued: "等待运行", debouncing: "等待合并", running: "正在生成", waiting_input: "等待补充资料", succeeded: "运行完成", degraded: "未能完整完成", failed: "运行失败", cancelled: "已停止" };
function text(value: unknown): string { if (typeof value !== "string") throw new Error("自动触发记录不完整，请刷新核对"); return value; }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("自动触发时间不完整，请刷新核对"); return result; }
function href(value: unknown): string | null { if (value === null) return null; const path = text(value); if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) return null; try { return new URL(path, "https://pdos.invalid").origin === "https://pdos.invalid" ? path : null; } catch { return null; } }
function parse(value: unknown): History {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("自动触发历史不完整，请刷新核对");
  return { next_before_id: value.next_before_id === null ? null : text(value.next_before_id), items: value.items.map(row => {
    if (!isRecord(row) || !Object.hasOwn(triggers, String(row.status)) || (row.run !== null && !isRecord(row.run))) throw new Error("自动触发记录不完整，请刷新核对");
    return { id: text(row.id), created_at: stamp(row.created_at), event_at: stamp(row.event_at), event_type: text(row.event_type), status: row.status as Item["status"], reason: text(row.reason), source_href: href(row.source_href), run: row.run === null ? null : { id: text(row.run.id), status: text(row.run.status), error: row.run.error === null ? null : text(row.run.error) } };
  }) };
}
class ReadError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string): Promise<History> {
  const response = await fetch(path, { method: "GET", cache: "no-store" }); const body: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new ReadError(isRecord(body) && typeof body.detail === "string" ? body.detail : isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "自动触发记录暂不可用，请稍后重试", response.status);
  return parse(body);
}
function time(value: string) { return new Date(value).toLocaleString("zh-CN"); }
export function AiIssueEventHistory(props: Props) { return <EventHistory key={`${props.projectId}:${props.eventRowId}`} {...props} />; }
function EventHistory({ projectId, eventRowId, onSelectRun, disabled = false }: Props) {
  const [data, setData] = useState<History | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const active = useRef(true), pending = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function load(older = false) {
    if (pending.current) return; pending.current = true; setBusy(true); setError(null);
    try { const value = await request(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-history?event_row_id=${eventRowId}${older && data?.next_before_id ? `&before_id=${encodeURIComponent(data.next_before_id)}` : ""}`); if (active.current) setData(current => older && current ? { ...value, items: [...current.items, ...value.items.filter(item => !current.items.some(old => old.id === item.id))] } : value); }
    catch (error) { if (active.current) { setError(error instanceof Error ? error.message : "自动触发记录读取失败"); if (!older || (error instanceof ReadError && [401, 403].includes(error.status))) setData(null); } }
    finally { pending.current = false; if (active.current) setBusy(false); }
  }
  return <details className="min-w-0 border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !data && !busy) void load(); }}><summary className="cursor-pointer text-xs font-medium text-primary">自动触发记录</summary><div className="mt-3 space-y-3 text-xs"><p className="leading-5 text-muted-foreground">回查此来源当时是否安排了运行，以及关联运行的当前状态。排队或复用不代表已经建单，实际结果以原运行和办理回执为准。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新自动触发记录</Button>{busy && <p role="status">正在读取自动触发记录…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}{data?.items.length === 0 && <p className="text-muted-foreground">此来源暂无自动触发记录。</p>}<ol className="divide-y">{data?.items.map(item => <li key={item.id} className="space-y-2 py-3"><p className="font-medium">{events[item.event_type] ?? "来源事件"}</p><p className="text-muted-foreground">原事件：<time dateTime={item.event_at}>{time(item.event_at)}</time> · 触发记录：<time dateTime={item.created_at}>{time(item.created_at)}</time></p><p>当时触发结果：{triggers[item.status]}</p><p className={`break-words leading-5 ${item.status === "skipped" ? "text-primary" : "text-muted-foreground"}`}>{item.reason}</p>{item.run ? <div className="space-y-2 border-l-2 pl-3"><p>当前运行：{runs[item.run.status] ?? "状态待核对"}</p>{item.run.error && <p className="break-words leading-5 text-primary">{/[\u3400-\u9fff]/.test(item.run.error) ? item.run.error : "本次运行未完成，请查看原运行回执。"}</p>}<Button size="sm" variant="outline" disabled={disabled || busy} onClick={() => onSelectRun(item.run!.id)}>查看关联运行回执</Button></div> : <p className="text-muted-foreground">本次没有关联运行。</p>}{item.source_href && <a className="inline-block text-primary underline underline-offset-2" href={item.source_href}>查看来源记录</a>}</li>)}</ol>{data?.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早的自动触发记录</Button>}</div></details>;
}
