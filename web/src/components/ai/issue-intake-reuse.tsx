"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

export type IntakeSourceRow = { row: number; errors: string[]; proposed: Record<string, string | null>; historical_state: string | null; external_ref: string | null };
export type IssueReuseTarget = Record<string, unknown> & { id: string; title: string; updated_at: string };
export type IssueReuseChoice = { target: IssueReuseTarget | null; reason: string };
type Cursor = { before_updated_at: string; before_id: string };
function target(value: unknown): IssueReuseTarget {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.title !== "string" || typeof value.updated_at !== "string") throw new Error("已有问题资料不完整");
  return { ...value, id: value.id, title: value.title, updated_at: value.updated_at };
}
async function request(path: string): Promise<Record<string, unknown>> {
  const response = await fetch(path, { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "已有问题暂不可用，请重新查询");
  return value;
}
const statuses: Record<string, string> = { open: "开放", analysis: "分析", action: "处理", verification: "验证", closed: "关闭" };
function show(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
export function IssueIntakeReuse({ base, row, value, disabled, onChange, onBusyChange, allowNew = true }: { base: string; row: IntakeSourceRow; value: IssueReuseChoice | undefined; disabled: boolean; onChange: (value: IssueReuseChoice | undefined) => void; onBusyChange: (busy: boolean) => void; allowNew?: boolean }) {
  const [search, setSearch] = useState(""), [loadedSearch, setLoadedSearch] = useState(""), [items, setItems] = useState<IssueReuseTarget[] | null>(null), [cursor, setCursor] = useState<Cursor | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function act(work: () => Promise<void>) { setBusy(true); onBusyChange(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "查找未完成"); } finally { setBusy(false); onBusyChange(false); } }
  async function find(more = false) {
    const query = new URLSearchParams({ search: more ? loadedSearch : search });
    if (more && cursor) { query.set("before_updated_at", cursor.before_updated_at); query.set("before_id", cursor.before_id); }
    const result = await request(`${base}/issue-options?${query}`);
    if (!Array.isArray(result.items)) throw new Error("问题清单不完整");
    const next = result.items.map(target);
    setItems(old => more ? [...(old ?? []), ...next.filter(item => !old?.some(prior => prior.id === item.id))] : next);
    setCursor(isRecord(result.next) && typeof result.next.before_id === "string" && typeof result.next.before_updated_at === "string" ? { before_id: result.next.before_id, before_updated_at: result.next.before_updated_at } : null);
    if (!more) setLoadedSearch(search);
  }
  async function choose(id: string) {
    const result = await request(`${base}/issue-options?issue_id=${encodeURIComponent(id)}`);
    onChange({ target: target(result.target), reason: value?.target?.id === id ? value.reason : "" });
  }
  const selected = value?.target;
  return <details className="rounded-md border p-3">
    <summary className="cursor-pointer text-xs">第{row.row}行 · {row.proposed.title || "缺少标题"} · {value ? selected ? `关联已有：${selected.title}` : "待选择复用问题" : "新建开放问题 / 精确来源复用"}</summary>
    <div className="mt-3 space-y-3 text-xs">
      {allowNew && <label className="flex gap-2"><input type="checkbox" disabled={disabled || busy} checked={!!value} onChange={e => onChange(e.target.checked ? { target: null, reason: "" } : undefined)}/>此行属于已有问题，人工选择关联（包括其他文件或手工登记的问题）</label>}
      {value && <>
        <p className="text-muted-foreground">标题相似只供查找，请核对具体对象、现象和历史编号。关联只添加来源，标题、类型、日期、原因、处理记录和当前状态均保留原问题的值。</p>
        <div className="flex flex-wrap gap-2"><input aria-label={`第${row.row}行查找已有问题`} className="min-w-0 flex-1 rounded-md border bg-background p-2" disabled={disabled || busy} maxLength={200} placeholder="输入标题关键词或问题ID；留空查看本项目问题" value={search} onChange={e => setSearch(e.target.value)}/><Button size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => find())}>查找</Button></div>
        {items?.length === 0 && <p>未找到匹配问题，可更换关键词。</p>}
        {items && items.length > 0 && <ul className="max-h-56 space-y-2 overflow-y-auto rounded-md border p-2">{items.map(item => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2"><span className="min-w-0 flex-1 break-words">{item.title} · {statuses[String(item.status)] ?? show(item.status)} · {show(item.target_date)}</span><Button size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => choose(item.id))}>读取并选择</Button></li>)}</ul>}
        {cursor && <Button size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => find(true))}>更多匹配问题</Button>}
        {selected && <div className="space-y-2 rounded-md border p-3">
          <p className="font-medium">所选原问题：{selected.title} · {statuses[String(selected.status)] ?? show(selected.status)}</p>
          <p className="break-all">问题ID：{selected.id} · 当前版本时间：{new Date(selected.updated_at).toLocaleString("zh-CN")}</p>
          <Button size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => choose(selected.id))}>重新读取所选问题，再核对</Button>
          <p>清单历史编号：{row.external_ref || "未提供"} · 历史状态：{row.historical_state || "未提供"}</p>
          <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th className="p-2">字段</th><th className="p-2">本行来源映射</th><th className="p-2">保留的原问题当前值</th></tr></thead><tbody>{Object.entries({ title: "标题", description: "说明", target_date: "目标日期", root_cause: "原因", resolution: "处理记录" }).map(([key, label]) => <tr key={key} className="border-t"><td className="p-2 align-top">{label}</td><td className="max-w-80 whitespace-pre-wrap break-words p-2 align-top">{show(row.proposed[key])}</td><td className="max-w-80 whitespace-pre-wrap break-words p-2 align-top">{show(selected[key])}</td></tr>)}</tbody></table></div>
          <p>原问题类型：{show(selected.issue_type)} · 严重度：{show(selected.severity)} · 负责人：{show(selected.owner_user_id)} · 验证人：{show(selected.verifier_user_id)} · 样机：{show(selected.sample_id)}</p>
          <p>关闭条件：{show(selected.closure_criteria)}<br/>关闭证据：{show(selected.closure_evidence_ref)}</p>
        </div>}
        <label className="block">属于同一问题的核对依据<textarea className="mt-1 min-h-20 w-full rounded-md border bg-background p-2" disabled={disabled || busy} maxLength={2000} value={value.reason} onChange={e => onChange({ ...value, reason: e.target.value })} placeholder="说明历史编号、样机/对象、现象等对应依据及差异"/></label>
      </>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
