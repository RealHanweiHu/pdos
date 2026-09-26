"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
export type IntakeTargetChoice = { target: Row & { id: string; digest: string } | null; reason: string };
const originalKeys: Record<string, string> = { approver_user_id: "historical_approver", owner_user_id: "historical_owner", decided_at: "historical_date", decision_kind: "historical_kind", follow_up_state: "historical_state", issue_id: "issue_ref" };
const field = "w-full rounded-md border bg-background p-2 text-xs";
const labels: Record<string, string> = { title: "标题", decision_kind: "决策类型", outcome: "结论", context: "背景", options: "选项", trade_offs: "权衡", rationale: "理由", consequence: "后果/后续要求", approver_user_id: "当前批准人ID", owner_user_id: "负责人ID", decided_at: "决策记录时间（历史记录为登记时间）", follow_up_state: "当前跟进状态", historical_source: "历史来源", issue_id: "决策原有问题关联", description: "问题描述", status: "问题当前状态", severity: "严重度", root_cause: "原因", resolution: "处理记录", closure_criteria: "关闭条件", closure_evidence_ref: "关闭证据", target_date: "目标日期", updated_at: "当前版本时间" };
function show(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
export function DecisionIntakeTarget({ base, kind, original, value, disabled, onChange, onBusyChange, operation = "intake", showReason = true }: {
  operation?: "intake" | "correct"; showReason?: boolean;
  base: string; kind: "decision" | "issue"; original: Row; value: IntakeTargetChoice | undefined;
  disabled: boolean; onChange: (value: IntakeTargetChoice | undefined) => void; onBusyChange: (busy: boolean) => void;
}) {
  const [search, setSearch] = useState(""), [savedSearch, setSavedSearch] = useState(""), [items, setItems] = useState<Row[]>([]), [cursor, setCursor] = useState<Row | null>(null), [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const label = kind === "decision" ? operation === "correct" ? "选择目标决策" : "复用已有决策" : "关联实际问题";
  async function act(work: () => Promise<void>) { setBusy(true); onBusyChange(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "读取未完成"); } finally { setBusy(false); onBusyChange(false); } }
  async function request(query: URLSearchParams) {
    const response = await fetch(`${base}/target-options?${query}`, { cache: "no-store" }), body: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(body)) throw new Error(isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "目标资料暂不可用");
    return body;
  }
  async function find(more = false) {
    const query = new URLSearchParams({ kind, search: more ? savedSearch : search });
    if (more && cursor) for (const key of ["before_updated_at", "before_id"]) query.set(key, String(cursor[key]));
    const result = await request(query);
    if (!Array.isArray(result.items) || !result.items.every(isRecord)) throw new Error("目标清单不完整");
    const next = result.items;
    setItems(old => more ? [...old, ...next.filter(item => !old.some(prior => prior.id === item.id))] : next); setCursor(isRecord(result.next) ? result.next : null); setLoaded(true); if (!more) setSavedSearch(search);
  }
  async function choose(id: string) {
    const result = await request(new URLSearchParams({ kind, target_id: id })), t = result.target;
    if (!isRecord(t) || typeof t.id !== "string" || typeof t.digest !== "string") throw new Error("目标版本不完整");
    onChange({ target: { ...t, id: t.id, digest: t.digest }, reason: value?.target?.id === id ? value.reason : "" });
  }
  const keys = kind === "decision" ? ["title", "decision_kind", "outcome", "context", "options", "trade_offs", "rationale", "consequence", "approver_user_id", "owner_user_id", "follow_up_state", "decided_at", "historical_source", "issue_id", "updated_at"] : ["title", "description", "status", "severity", "root_cause", "resolution", "closure_criteria", "closure_evidence_ref", "owner_user_id", "target_date", "updated_at"];
  return <div className="space-y-2 rounded-md border p-3">
    <label className="flex gap-2"><input type="checkbox" disabled={disabled || busy} checked={!!value} onChange={e => onChange(e.target.checked ? { target: null, reason: "" } : undefined)}/>{label}</label>
    {value && <div className="space-y-2">
      <p>{operation === "correct" ? "请选择来源修订后的实际目标，并核对当前内容和原文对应关系。" : kind === "decision" ? "复用仅增加这份历史来源，所选决策原文、批准与执行记录保持原值。相似标题不自动认定为同一决策。" : "建立本行来源、决策和实际问题的明确关联，保留问题的当前办理记录。原问题编号仅供人工核对。"}</p>
      <p>原文编号：{show(original.external_ref)} · 原问题编号/说明：{show(original.issue_ref)}</p>
      <div className="flex gap-2"><input aria-label={`${label}关键词`} className={field} maxLength={200} disabled={disabled || busy} value={search} onChange={e => setSearch(e.target.value)} placeholder="标题关键词或ID，留空查看本项目记录"/><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => find())}>查找</Button></div>
      {loaded && !items.length && <p>暂无匹配记录。</p>}
      {!!items.length && <ul className="max-h-60 space-y-2 overflow-auto">{items.map(item => <li key={String(item.id)} className="flex items-start gap-2 border-t py-2"><span className="min-w-0 flex-1 break-words">{show(item.title)} · {show(item.status ?? item.decision_kind)}{kind === "decision" && <span className="block line-clamp-2">{show(item.outcome)}</span>}</span><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => choose(String(item.id)))}>读取并选择</Button></li>)}</ul>}
      {cursor && <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => find(true))}>更多记录</Button>}
      {value.target && <div className="space-y-2 border-t pt-2"><p className="font-medium">已选：{show(value.target.title)}</p><p className="break-all">ID：{value.target.id}</p><Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void act(() => choose(value.target!.id))}>重新读取当前版本</Button><div className="max-h-96 overflow-auto"><table className="w-full text-left"><thead><tr><th>字段</th>{kind === "decision" && <th>本行原文</th>}<th>目标当前记录</th></tr></thead><tbody>{keys.map(key => <tr key={key} className="border-t"><th className="p-2 align-top font-normal">{labels[key] ?? key}</th>{kind === "decision" && <td className="max-w-72 whitespace-pre-wrap break-words p-2 align-top">{show(original[originalKeys[key] ?? key])}</td>}<td className="max-w-72 whitespace-pre-wrap break-words p-2 align-top">{show(value.target![key])}</td></tr>)}</tbody></table></div></div>}
      {showReason && <label className="block">{label}的核对依据<textarea className={field} maxLength={2000} disabled={disabled || busy} value={value.reason} onChange={e => onChange({ ...value, reason: e.target.value })}/></label>}
    </div>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
