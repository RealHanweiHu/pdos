"use client";

import { useState } from "react";
import { SupplierRecoveryRuns } from "./supplier-recovery-runs";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Choice = { id: string; title?: string; code?: string; name?: string; round_label?: string; version?: number };
type Choices = { exceptions: Choice[]; tooling: Choice[]; suppliers: Choice[]; has_more: Record<string, boolean> };
type Selection = { exception_ids: string[]; tooling_ids: string[]; supplier_ids: string[] };
type Prepared = { digest: string; context_version: string; model_context: { references: { reference_id: string; label: string; digest: string; fields: Record<string, unknown>; omitted_fields: string[] }[]; omitted_references: string[]; coverage_limits: string[] } };
const categories = [{ key: "exception_ids", choices: "exceptions", label: "实际物料异常", max: 20 }, { key: "tooling_ids", choices: "tooling", label: "实际工装轮次", max: 20 }, { key: "supplier_ids", choices: "suppliers", label: "补充供方工程资料", max: 10 }] as const;
const names: Record<string, string> = { id: "记录标识", build_id: "实际批次", issue_id: "原问题", material_key: "物料条目", material_reference: "物料标识", version: "版本", status: "状态", title: "事项", code: "编号", name: "名称", kind: "类型", material: "当前物料核对", supply_ready: "已核对齐备", review_current: "原核对仍有效", latest_review: "最新人工核对", source_digest: "来源版本摘要", facts: "实际事实", first_promise: "首次承诺", availability: "实际可用核对", outcome: "本轮结果", round_label: "轮次", phase: "阶段", planning_resource_id: "实际资源", metrics: "本项目实际指标", scope: "适用范围", times: "原保存时间", baseline: "基线", commitment: "承诺", forecast: "预测", actual: "实际", start: "开始", end: "结束", created_at: "记录时间", node_id: "实际节点", forecast_current: "预测有效性", promised: "当前具名承诺", estimated_ready: "预计可用", started: "实际开始", completed: "实际完成", available: "接受后实际可用", at: "时间", location: "原件位置", evidence_id: "依据原件", source_reference: "原资料编号", requested: "实际请求", responded: "首次实际响应", received: "实际收样", detected: "实际发现", reason: "具名依据", required: "需求数量", unit: "单位", quantity: "数量", allocated_on_hand: "已分配现货", qualified_issued: "合格净领料", on_hand_gap: "现货缺口", disposition: "人工结论" };
function EvidenceValue({ value }: { value: unknown }) {
  if (value === null) return <span className="text-muted-foreground">未知／未登记</span>;
  if (typeof value === "boolean") return <span>{value ? "是" : "否"}</span>;
  if (Array.isArray(value)) return value.length ? <ol className="space-y-1 border-l pl-3">{value.map((item, i) => <li key={i}><EvidenceValue value={item}/></li>)}</ol> : <span>无记录</span>;
  if (isRecord(value)) return <dl className="space-y-1">{Object.entries(value).map(([key, item]) => <div key={key}><dt className="text-muted-foreground">{names[key] ?? key}</dt><dd className="pl-2"><EvidenceValue value={item}/></dd></div>)}</dl>;
  return <span className="whitespace-pre-wrap break-all">{value === "not_rechecked" ? "尚未复核" : String(value)}</span>;
}
async function read<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "资料暂不可用，请核对项目权限和所选原记录");
  return value as T;
}

export function SupplierRecoveryPreparation({ projectId }: { projectId: string }) {
  const [choices, setChoices] = useState<Choices | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>({ exception_ids: [], tooling_ids: [], supplier_ids: [] });
  const [prepared, setPrepared] = useState<Prepared | null>(null), [selectionKey, setSelectionKey] = useState("");
  const [manual, setManual] = useState<Record<string, string>>({});
  const base = `/api/projects/${projectId}/npi/supplier-recovery`;
  async function act(action: () => Promise<void>) { setBusy(true); setError(null); try { await action(); } catch (failure) { setError(failure instanceof Error ? failure.message : "资料读取未完成"); } finally { setBusy(false); } }
  async function load() { setChoices(await read<Choices>(`${base}/sources`)); }
  async function prepare() { setPrepared(await read<Prepared>(`${base}/context`, selection)); setSelectionKey(JSON.stringify(selection)); }
  const current = selectionKey === JSON.stringify(selection);
  return <details className="rounded-lg border p-4" onToggle={event => { if (event.currentTarget.open && !choices && !busy) void act(load); }}>
    <summary className="cursor-pointer font-medium">供应恢复方案资料</summary>
    <div className="mt-3 space-y-3"><p className="text-sm text-muted-foreground">选择需要处理的物料异常或工装，核对当前供给、原承诺、实际交付及需用节点时间，作为催交、替代验证、拆借核对或工装恢复的依据。此处读取实际资料。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新可选资料</Button>
      {choices && <fieldset disabled={busy} className="space-y-3">{categories.map(category => <details className="rounded-md border p-2" key={category.key}><summary className="cursor-pointer text-sm">{category.label} · 已选 {selection[category.key].length} / {category.max}</summary><div className="max-h-52 overflow-y-auto space-y-1">{[...choices[category.choices], ...selection[category.key].filter(id => !choices[category.choices].some(row => row.id === id)).map(id => ({ id }))].map((row: Choice) => <label className="block text-xs" key={row.id}><input type="checkbox" checked={selection[category.key].includes(row.id)} disabled={!selection[category.key].includes(row.id) && selection[category.key].length >= category.max} onChange={event => setSelection({ ...selection, [category.key]: event.target.checked ? [...selection[category.key], row.id] : selection[category.key].filter(id => id !== row.id) })}/> {row.code} {row.title ?? row.name ?? row.id} {row.round_label} {row.version ? `v${row.version}` : ""}</label>)}</div>{choices.has_more[category.choices] && <p className="text-xs">列表仅展示最近/前列部分，可按原记录标识补充。</p>}<label className="block text-xs">按原记录标识选择<input className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={manual[category.key] ?? ""} onChange={event => setManual({ ...manual, [category.key]: event.target.value })}/></label><Button size="sm" variant="ghost" disabled={!/^[0-9a-f-]{36}$/i.test(manual[category.key] ?? "") || selection[category.key].length >= category.max} onClick={() => { const id = manual[category.key].toLowerCase(); setSelection({ ...selection, [category.key]: [...new Set([...selection[category.key], id])] }); setManual({ ...manual, [category.key]: "" }); }}>加入所选资料</Button></details>)}<Button size="sm" disabled={!selection.exception_ids.length && !selection.tooling_ids.length} onClick={() => void act(prepare)}>整理所选资料</Button></fieldset>}
      {prepared && <div className="space-y-2 rounded-md border p-3"><p className="text-sm">{current ? "本次所选资料" : "选择已变化，请重新整理"} · {prepared.model_context.references.length} 条来源</p>{prepared.model_context.coverage_limits.map(note => <p className="text-xs text-muted-foreground" key={note}>{note}</p>)}{prepared.model_context.references.map(ref => <details className="border-t py-2 text-xs" key={ref.reference_id}><summary className="cursor-pointer">{ref.label} · {ref.reference_id}</summary><EvidenceValue value={ref.fields}/>{ref.omitted_fields.length > 0 && <p>受资料容量限制，未纳入：{ref.omitted_fields.map(key => names[key] ?? key).join("、")}</p>}</details>)}{prepared.model_context.omitted_references.length > 0 && <p className="text-xs">有 {prepared.model_context.omitted_references.length} 条来源超出本次容量，未包含在资料中。可减少选择后分别读取。</p>}</div>}
      <SupplierRecoveryRuns projectId={projectId} selection={selection} digest={prepared?.digest ?? null} current={current}/>
    </div>
  </details>;
}
