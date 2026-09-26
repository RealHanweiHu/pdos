"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FmeaSourceValue, field, obj, rows, text, type Row } from "./fmea-sources";
import { testEvidenceLabel } from "./test-evidence-value";

export type Evidence = { kind: string; reference: string; expected_digest: string; locator: string; value: Row };
export async function qualityRequest(project: string, ncr: string, path: string, body?: unknown): Promise<Row> {
  const res = await fetch(`/api/projects/${project}/quality/ncrs/${ncr}${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const value: unknown = await res.json();
  if (!res.ok) throw new Error(text(obj(obj(value).detail).message) || "质量办理未完成，请刷新原记录");
  return obj(value);
}
export const evidenceBody = (values: Evidence[]) => values.map(v => ({ kind: v.kind, reference: v.reference, expected_digest: v.expected_digest, locator: v.locator }));
export function EvidenceValue({ value }: { value: Row }) {
  return <div className="space-y-2 text-xs"><FmeaSourceValue value={value}/>{value.event_type != null && <details><summary className="cursor-pointer">原事件：{text(value.event_type)} · {text(value.timestamp)}</summary><pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(value.payload, null, 2)}</pre></details>}</div>;
}
export function OperationEvidence({ projectId, ncrId, value, onChange, disabled }: { projectId: string; ncrId: string; value: Evidence[]; onChange: (v: Evidence[]) => void; disabled: boolean }) {
  const [kind, setKind] = useState("document"), [choices, setChoices] = useState<Row[]>([]), [next, setNext] = useState<number | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(more = false) { setBusy(true); setError(""); try { const data = await qualityRequest(projectId, ncrId, `/evidence?kind=${kind}&offset=${more ? next ?? 0 : 0}`); setChoices(old => more ? [...old, ...rows(data.items)] : rows(data.items)); setNext(typeof data.next_offset === "number" ? data.next_offset : null); } catch(e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }
  return <fieldset className="space-y-2 rounded-md border p-3" disabled={busy || disabled}><legend className="px-1 text-sm font-medium">核对实际证据</legend>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <div className="flex items-end gap-2"><label className="text-sm">证据类别<select className={field} value={kind} onChange={e => { setKind(e.target.value); setChoices([]); setNext(null); }}><option value="document">原项目文件</option><option value="test_run">实际测试记录</option><option value="event">项目原事件</option></select></label><Button type="button" size="sm" variant="outline" onClick={() => void load()}>读取证据</Button></div>
    {choices.length > 0 && <label className="block text-sm">选择原记录<select value="" className={field} onChange={e => { const source = choices.find(s => s.reference === e.target.value); if (!source) return; const index = value.findIndex(v => v.kind === kind && v.reference === source.reference); const ref = { kind, reference: text(source.reference), expected_digest: text(source.expected_digest), locator: index >= 0 ? value[index].locator : "", value: obj(source.value) }; onChange(index < 0 ? [...value, ref] : value.map((v, i) => i === index ? ref : v)); }}><option value="">请选择</option>{choices.map(c => { const v = obj(c.value); return <option key={text(c.reference)} value={text(c.reference)}>{v.test_case_id != null ? testEvidenceLabel(v) : text(v.filename || v.event_type || v.title || v.result || "原记录")} · {v.test_case_id != null ? `实际时间 ${text(v.executed_at) || "未记录"}` : text(v.actual_completed_at || v.completed_at || v.timestamp || v.created_at)}</option>; })}</select></label>}
    {next !== null && <Button type="button" size="sm" variant="outline" onClick={() => void load(true)}>更多证据</Button>}
    {value.map((v, i) => <div key={`${v.kind}:${v.reference}`} className="space-y-2 rounded-md border p-2"><EvidenceValue value={v.value}/><label className="block text-sm">对应页码、条款或指标位置<input maxLength={2000} className={field} value={v.locator} onChange={e => onChange(value.map((r, n) => n === i ? { ...r, locator: e.target.value } : r))}/></label><Button type="button" size="sm" variant="outline" onClick={() => onChange(value.filter((_, n) => n !== i))}>移除此引用</Button></div>)}
    <p className="text-xs text-muted-foreground">选中的原值会在提交时再次核对。引用材料存在不等于结论成立，请在实际调查或验证说明中写清对应依据。</p>
  </fieldset>;
}
