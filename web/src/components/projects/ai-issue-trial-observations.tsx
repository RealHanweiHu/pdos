"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const countLabels = {
  total_runs: "全部原请求", succeeded_runs: "生成成功", failed_runs: "失败或未完成", pending_runs: "尚在运行",
  proposal_runs: "有建议结果", insufficient_runs: "资料不足待补证", unhandled_proposals: "建议尚未办理", declined_runs: "当前不采纳", reopened_runs: "当前重新考虑",
  created_issues: "本运行新建问题", reused_issues: "本运行复用问题", same_source_applied_runs: "同源其他运行已办理", withdrawn_issues: "已撤回的新建问题", human_edited_issues: "人工修改的问题",
  trial_candidates: "生成时试运行候选", evidence_only_runs: "仅保留建议证据", unrecorded_bindings: "生成时依据未留存",
};
type CountKey = keyof typeof countLabels;
type Summary = { id: string; created_at: string; actor_name: string; window_start: string; window_end: string; total_runs: number };
type Sample = { run_id: string; event_row_id: number; status: string; result_id: string | null; disposition: string | null; binding_kind: string; review_state: string; application_kind: string | null; same_source_applied: boolean; withdrawn: boolean; human_edited: boolean; created_at: string; issue_id: string | null; source_title: string; source_href: string | null };
type Observation = Summary & { as_of: string; counts: Record<CountKey, number | null>; ratios: { handled_proposals: number; confirmed_proposals: number; confirmation_basis_points: number | null; withdrawal_basis_points: number | null }; items: Sample[]; notice: string };
type History = { items: Summary[]; next_before_id: string | null; can_capture: boolean };
type Command = { request_id: string; window_start: string; window_end: string };
const statusLabels: Record<string, string> = { queued: "等待运行", running: "运行中", succeeded: "生成成功", failed: "运行失败", degraded: "本次未完成", waiting_input: "等待补充资料", cancelled: "已停止" };
const dispositionLabels: Record<string, string> = { create_issue: "建议新建", reuse_issue: "建议沿用", insufficient_evidence: "资料不足" };
const bindingLabels: Record<string, string> = { trial_candidate: "生成时试运行候选", evidence_only: "仅保留建议证据", not_recorded: "生成时依据未留存" };
const reviewLabels: Record<string, string> = { unreviewed: "未处置", declined: "不采纳", reopened: "重新考虑" };
function record(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("观察资料不完整，请重新核对"); return value; }
function text(value: unknown): string { if (typeof value !== "string") throw new Error("观察资料不完整，请重新核对"); return value; }
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
function count(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("观察数量不完整，请重新核对"); return value; }
function nullableCount(value: unknown): number | null { return value === null ? null : count(value); }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("观察时间不完整，请重新核对"); return result; }
function flag(value: unknown): boolean { if (typeof value !== "boolean") throw new Error("观察状态不完整，请重新核对"); return value; }
function sourceHref(value: unknown): string | null { if (value == null) return null; const href = text(value); if (!href.startsWith("/") || href.startsWith("//") || href.includes("\\")) return null; try { return new URL(href, "https://pdos.invalid").origin === "https://pdos.invalid" ? href : null; } catch { return null; } }
function summary(value: unknown): Summary { const row = record(value); return { id: text(row.id), created_at: stamp(row.created_at), actor_name: text(row.actor_name), window_start: stamp(row.window_start), window_end: stamp(row.window_end), total_runs: count(row.total_runs) }; }
function history(value: unknown): History { const row = record(value); if (!Array.isArray(row.items)) throw new Error("观察历史不完整"); return { items: row.items.map(summary), next_before_id: nullableText(row.next_before_id), can_capture: flag(row.can_capture) }; }
function observation(value: unknown): Observation {
  const row = record(value), head = summary(row), counts = record(row.counts), ratios = record(row.ratios);
  if (row.qualification_granted !== false || ratios.descriptive_only !== true || !Array.isArray(row.items) || row.items.length !== head.total_runs || row.items.length > 5000 || counts.total_runs !== head.total_runs) throw new Error("观察样本或统计口径不完整，请重新核对；不会展示截断结果");
  const rate = (value: unknown) => { const result = nullableCount(value); if (result !== null && result > 10000) throw new Error("观察比率不完整"); return result; };
  return { ...head, as_of: stamp(row.as_of), counts: Object.fromEntries(Object.keys(countLabels).map(key => [key, nullableCount(counts[key])])) as Observation["counts"], ratios: { handled_proposals: count(ratios.handled_proposals), confirmed_proposals: count(ratios.confirmed_proposals), confirmation_basis_points: rate(ratios.confirmation_basis_points), withdrawal_basis_points: rate(ratios.withdrawal_basis_points) }, notice: text(row.notice), items: row.items.map(value => {
    const item = record(value);
    return { run_id: text(item.run_id), event_row_id: count(item.event_row_id), status: text(item.status), result_id: nullableText(item.result_id), disposition: nullableText(item.disposition), binding_kind: text(item.binding_kind), review_state: text(item.review_state), application_kind: nullableText(item.application_kind), same_source_applied: flag(item.same_source_applied), withdrawn: flag(item.withdrawn), human_edited: flag(item.human_edited), created_at: stamp(item.created_at), issue_id: nullableText(item.issue_id), source_title: text(item.source_title), source_href: sourceHref(item.source_href) };
  }) };
}
class ReadError extends Error { constructor(message: string, readonly status: number, readonly code: string | null) { super(message); } }
async function request(path: string, body?: Command): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new ReadError(isRecord(value) && typeof value.detail === "string" ? value.detail : isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "观察记录暂不可用，请重试核对", response.status, isRecord(value) && isRecord(value.detail) && typeof value.detail.code === "string" ? value.detail.code : null);
  return value;
}
function time(value: string) { return new Date(value).toLocaleString("zh-CN"); }
function localTime(date: Date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`; }
function captureCommand(windowStart: string, windowEnd: string): Command {
  const start = new Date(windowStart), end = new Date(windowEnd);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end || end.getTime() - start.getTime() > 366 * 86400000 || end.getTime() > Date.now() || localTime(start) !== windowStart || localTime(end) !== windowEnd) throw new Error("请选择有效的已结束窗口：开始早于结束，结束时间不能在未来，最长 366 天。");
  return { request_id: crypto.randomUUID(), window_start: start.toISOString(), window_end: end.toISOString() };
}
function percent(value: number | null) { return value === null ? "—" : `${value / 100}%`; }

function ObservationDetail({ value }: { value: Observation }) {
  const [page, setPage] = useState(0);
  const samples = value.items.slice(page * 20, (page + 1) * 20), pages = Math.max(1, Math.ceil(value.items.length / 20));
  return <section className="space-y-3 border-t pt-3" aria-label="原运行观察详情">
    <div className="space-y-1"><p className="font-medium">{value.actor_name} 保存的运行观察</p><p className="text-muted-foreground">窗口：{time(value.window_start)} 至 {time(value.window_end)}（不含结束时刻）</p><p className="text-muted-foreground">观察截至：{time(value.as_of)} · 保存于 {time(value.created_at)}</p></div>
    <p className="leading-5 text-muted-foreground">{value.notice}</p>
    <details><summary className="cursor-pointer font-medium text-primary">窗口统计 · 全部 {value.total_runs} 个原请求</summary><dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">{(Object.keys(countLabels) as CountKey[]).map(key => <div key={key}><dt className="leading-5 text-muted-foreground">{countLabels[key]}</dt><dd className="mt-1 font-medium tabular-nums">{value.counts[key] ?? "—"}</dd></div>)}</dl></details>
    <div className="grid gap-3 sm:grid-cols-2"><div><p className="text-muted-foreground">本窗口办理中的确认比例</p><p className="mt-1 text-base font-medium tabular-nums">{percent(value.ratios.confirmation_basis_points)}</p><p className="mt-1 leading-5 text-muted-foreground">本运行确认 {value.ratios.confirmed_proposals} / 已办理原请求 {value.ratios.handled_proposals}；已办理含不采纳，同源其他运行办理不重复计确认。</p></div><div><p className="text-muted-foreground">本运行新建问题的撤回比例</p><p className="mt-1 text-base font-medium tabular-nums">{percent(value.ratios.withdrawal_basis_points)}</p><p className="mt-1 leading-5 text-muted-foreground">已撤回 {value.counts.withdrawn_issues ?? "—"} / 本运行新建 {value.counts.created_issues ?? "—"}。</p></div></div>
    <p className="leading-5 text-primary">比率只描述本窗口，模拟记录和观察结果不等于真实模型成绩，也不授予自动写入资格。</p>
    <div className="space-y-2"><p className="font-medium">全部样本 · 共 {value.total_runs} 条，当前第 {page + 1} / {pages} 页（每页 20 条）</p>{samples.length === 0 && <p className="text-muted-foreground">此窗口没有运行记录。</p>}<ol className="divide-y">{samples.map(item => <li className="space-y-1.5 py-3" key={item.run_id}><p className="break-words font-medium">{item.source_title}</p><p className="text-muted-foreground">{time(item.created_at)} · {statusLabels[item.status] ?? "运行状态待核对"} · {item.disposition ? dispositionLabels[item.disposition] ?? "建议类型待核对" : "尚无建议结果"}</p><p>{bindingLabels[item.binding_kind] ?? "生成依据待核对"} · {reviewLabels[item.review_state] ?? "处置待核对"} · {item.application_kind === "created" ? "本运行已新建问题" : item.application_kind === "reused" ? "本运行已复用问题" : "本运行未应用"}</p>{item.same_source_applied && <p className="text-muted-foreground">同一来源已由其他运行办理，本运行不重复计确认。</p>}{item.withdrawn && <p className="text-primary">原问题已撤回，历史保留。</p>}{item.human_edited && <p>原问题已有人工修改。</p>}{item.source_href && <a className="inline-block text-primary underline underline-offset-2" href={item.source_href}>查看来源记录</a>}</li>)}</ol>{pages > 1 && <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(value => value - 1)}>上一页样本</Button><Button size="sm" variant="outline" disabled={page + 1 === pages} onClick={() => setPage(value => value + 1)}>下一页样本</Button></div>}</div>
  </section>;
}

export function AiIssueTrialObservations({ projectId }: { projectId: string }) { return <Observations key={projectId} projectId={projectId} />; }
function Observations({ projectId }: { projectId: string }) {
  const [windowEnd, setWindowEnd] = useState(() => localTime(new Date())), [windowStart, setWindowStart] = useState(() => localTime(new Date(Date.now() - 7 * 86400000)));
  const [data, setData] = useState<History | null>(null), [selected, setSelected] = useState<Observation | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [pending, setPending] = useState<Command | null>(null);
  const active = useRef(true), locked = useRef(false), selection = useRef(0);
  useEffect(() => { active.current = true; return () => { active.current = false; selection.current += 1; }; }, []);
  const base = `/api/projects/${encodeURIComponent(projectId)}/ai-issue-observations`;
  function failure(error: unknown) { setError(error instanceof Error ? error.message : "观察读取失败，请重试"); if (error instanceof ReadError && [401, 403].includes(error.status)) { setData(null); setSelected(null); setBusy(false); selection.current += 1; } }
  async function load(older = false) {
    if (locked.current) return; locked.current = true; setBusy(true); setError(null);
    try { const page = history(await request(`${base}?limit=20${older && data?.next_before_id ? `&before_id=${encodeURIComponent(data.next_before_id)}` : ""}`)); if (active.current) setData(current => older && current ? { ...page, items: [...current.items, ...page.items.filter(item => !current.items.some(old => old.id === item.id))] } : page); }
    catch (error) { if (active.current) failure(error); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function open(id: string) {
    const current = ++selection.current; setError(null); setSelected(null); setBusy(true);
    try { const value = observation(await request(`${base}/${encodeURIComponent(id)}`)); if (value.id !== id) throw new Error("原观察记录不匹配，请重新读取"); if (active.current && current === selection.current) setSelected(value); }
    catch (error) { if (active.current && current === selection.current) failure(error); }
    finally { if (active.current && current === selection.current) setBusy(false); }
  }
  async function save(command?: Command) {
    if (locked.current || (!command && !data?.can_capture)) return;
    if (!command) { try { command = captureCommand(windowStart, windowEnd); } catch (error) { failure(error); return; } }
    const current = ++selection.current;
    locked.current = true; setPending(command); setBusy(true); setError(null);
    try {
      const value = observation(await request(base, command));
      if (Date.parse(value.window_start) !== Date.parse(command.window_start) || Date.parse(value.window_end) !== Date.parse(command.window_end)) throw new Error("观察回执与原窗口不匹配，请沿原请求核对");
      if (active.current && current === selection.current) { setSelected(value); setPending(null); setData(old => old ? { ...old, items: [value, ...old.items.filter(item => item.id !== value.id)] } : old); }
    } catch (error) { if (active.current && current === selection.current) { failure(error); if (error instanceof ReadError && error.status >= 400 && error.status < 500 && error.code !== "OBSERVATION_RETRY") setPending(null); } }
    finally { locked.current = false; if (active.current && current === selection.current) setBusy(false); }
  }
  return <details className="min-w-0 border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !data && !busy && !pending) void load(); }}><summary className="cursor-pointer text-sm font-medium text-primary">项目问题运行观察</summary><div className="mt-3 space-y-3 text-xs">
    <p className="leading-5 text-muted-foreground">按运行创建时间纳入窗口内全部原请求，包含失败、补证和未办理记录。包含开始、不含结束；同一来源的不同运行分别保留。保存只固定观察，不改业务记录。</p>
    <p className="text-muted-foreground">时间按本地时区填写：{Intl.DateTimeFormat().resolvedOptions().timeZone}。超过 5000 条须缩小窗口，不会静默截断。</p>
    <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1"><span className="block">窗口开始</span><input type="datetime-local" className="min-h-10 w-full min-w-0 rounded-lg border bg-background px-3 py-2" value={windowStart} disabled={busy || !!pending} onChange={event => setWindowStart(event.target.value)} /></label><label className="space-y-1"><span className="block">窗口结束（不含）</span><input type="datetime-local" className="min-h-10 w-full min-w-0 rounded-lg border bg-background px-3 py-2" value={windowEnd} disabled={busy || !!pending} onChange={event => setWindowEnd(event.target.value)} /></label></div>
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || !!pending || !data?.can_capture} onClick={() => void save()}>保存本窗口观察</Button><Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void load()}>刷新观察历史</Button></div>
    {data && !data.can_capture && <p className="text-muted-foreground">当前账号仅可查看运行观察，不能保存。</p>}{busy && <p role="status">正在核对观察记录…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    {pending && !busy && <div className="space-y-2"><p className="text-primary">保存结果尚未明确，窗口与请求已保留，继续核对不会另存一份。</p><Button size="sm" onClick={() => void save(pending)}>沿原请求核对观察结果</Button></div>}
    {data?.items.length === 0 && <p className="text-muted-foreground">尚无保存的观察记录。</p>}
    {data?.items.map(item => <div className="flex flex-wrap items-center justify-between gap-2 border-b py-2" key={item.id}><div className="min-w-0 space-y-1"><p>{time(item.created_at)} · {item.actor_name} · {item.total_runs} 个原请求</p><p className="text-muted-foreground">{time(item.window_start)} 至 {time(item.window_end)}</p></div><Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void open(item.id)}>查看原观察</Button></div>)}
    {data?.next_before_id && <Button size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void load(true)}>更早的观察记录</Button>}
    {selected && <ObservationDetail key={selected.id} value={selected} />}
  </div></details>;
}
