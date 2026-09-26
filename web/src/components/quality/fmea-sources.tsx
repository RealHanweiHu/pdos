"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { SourcePreview } from "@/components/projects/change-impact-scope";
import { TestEvidenceValue } from "./test-evidence-value";

export type Row = Record<string, unknown>;
export const obj = (v: unknown): Row => isRecord(v) ? v : {};
export const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
export const text = (v: unknown) => v == null ? "" : String(v);
export const kinds: Record<string, string> = { requirement: "需求", specification: "规格", bom_item: "物料项", test_case: "测试项", test_run: "实际测试", issue: "问题", ncr: "NCR", capa_action: "CAPA 措施", document: "项目文件" };
export type Reference = { kind: string; id: string; expected_digest: string; relationship: string; locator: string; value: Row };
export const label = (v: Row) => text(v.code || v.title || v.part_number || v.filename || v.nonconformity || v.description || "原记录");
export const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function FmeaSourceValue({ value }: { value: Row }) {
  const ncr = value.ncr ? obj(value.ncr) : value;
  const root = obj(ncr.approved_root_cause), review = obj(ncr.latest_effectiveness_review);
  return <div className="space-y-2 text-xs"><SourcePreview snapshot={value}/>
    {value.test_case_id != null && value.run_number != null && <TestEvidenceValue value={value}/>}
    {value.nonconformity != null && <p className="whitespace-pre-wrap">不符合事实：{text(value.nonconformity)}</p>}
    {value.requirement_reference != null && <p className="whitespace-pre-wrap">原要求：{text(value.requirement_reference)}</p>}
    {value.completion_summary != null && <p className="whitespace-pre-wrap">措施完成说明：{text(value.completion_summary)}</p>}
    {(value.ncr || value.nonconformity) != null && <details><summary className="cursor-pointer">核对原 NCR 根因与有效性记录</summary>
      <p>NCR：{text(ncr.code)} · {text(ncr.status)}</p>
      <p className="whitespace-pre-wrap">{root.id ? `原批准根因 v${text(root.version)}：${text(root.root_cause)}` : "尚无获批根因"}</p>
      {root.analysis != null && <p className="whitespace-pre-wrap">调查过程：{text(root.analysis)}</p>}
      <p className="whitespace-pre-wrap">{review.id ? `最近独立验证：${review.result === "effective" ? "有效" : "无效"}；${text(review.actual_result)}` : "尚无独立有效性验证"}</p>
      {review.criteria != null && <p className="whitespace-pre-wrap">原验证判据：{text(review.criteria)}</p>}
      <p className="text-muted-foreground">保留原质量裁决；仍须核对该结论对本条失效模式是否适用。</p>
    </details>}
  </div>;
}
export async function request(project: string, path: string, body?: unknown): Promise<Row> {
  const res = await fetch(`/api/projects/${project}/quality/fmea${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const value: unknown = await res.json();
  if (!res.ok || !isRecord(value)) throw new Error(text(obj(obj(value).detail).message) || "FMEA 操作未完成，请读取原记录");
  return value;
}
export function FmeaSources({ projectId, value, onChange, disabled }: { projectId: string; value: Reference[]; onChange: (v: Reference[]) => void; disabled: boolean }) {
  const [kind, setKind] = useState("requirement"), [options, setOptions] = useState<Row[]>([]), [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(more = false) { setBusy(true); setError(""); try {
    const data = await request(projectId, `/sources?kind=${kind}&offset=${more ? next ?? 0 : 0}`);
    setOptions(old => more ? [...old, ...rows(data.items)] : rows(data.items)); setNext(typeof data.next_offset === "number" ? data.next_offset : null);
  } catch (e) { setError(e instanceof Error ? e.message : "来源读取失败"); } finally { setBusy(false); } }
  const update = (i: number, patch: Partial<Reference>) => onChange(value.map((v, index) => index === i ? { ...v, ...patch } : v));
  return <fieldset disabled={disabled || busy} className="space-y-3 rounded-md border p-3">
    <legend className="px-1 font-medium">实际关联资料</legend>
    <p className="text-sm text-muted-foreground">选择实际对象并说明它与功能、控制措施、失效或验证的关系。原值更新后须重新核对；引用不等于风险已受控。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <div className="flex flex-wrap items-end gap-2"><label>资料类别<select className={field} value={kind} onChange={e => { setKind(e.target.value); setOptions([]); setNext(null); }}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><Button size="sm" variant="outline" type="button" onClick={() => void load()}>读取实际资料</Button></div>
    {options.length > 0 && <label className="block">选择要关联或重新核对的资料<select className={field} value="" onChange={e => {
      const source = options.find(o => o.id === e.target.value); if (!source) return;
      const existing = value.findIndex(r => r.kind === kind && r.id === source.id);
      if (existing >= 0) update(existing, { expected_digest: text(source.digest), value: obj(source.value) });
      else onChange([...value, { kind, id: text(source.id), expected_digest: text(source.digest), value: obj(source.value), relationship: "", locator: "" }]);
    }}><option value="">请选择原记录</option>{options.map(o => <option key={text(o.id)} value={text(o.id)}>{text(o.label)}</option>)}</select></label>}
    {next !== null && <Button size="sm" variant="outline" type="button" onClick={() => void load(true)}>更多资料</Button>}
    {value.map((ref, i) => <div key={`${ref.kind}:${ref.id}`} className="space-y-2 rounded-md border p-2">
      <p className="font-medium">{kinds[ref.kind]} · {label(ref.value)}</p><FmeaSourceValue value={ref.value}/>
      <label className="block">关联说明<textarea required maxLength={2000} className={field} value={ref.relationship} onChange={e => update(i, { relationship: e.target.value })}/></label>
      <label className="block">原文位置 / 控制措施对应<input maxLength={2000} className={field} value={ref.locator} onChange={e => update(i, { locator: e.target.value })}/></label>
      <Button type="button" size="sm" variant="outline" onClick={() => onChange(value.filter((_, n) => n !== i))}>移除此关联</Button>
    </div>)}
  </fieldset>;
}
