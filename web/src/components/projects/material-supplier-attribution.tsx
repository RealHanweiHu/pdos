"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type History = { id: string; version: number; supplier_id: string | null; reason: string; created_at: string; created_by_user_id: string; snapshot: { supplier: { name: string; code: string } | null; evidence: { id: string; filename: string; sha256: string } } };
type State = { source: { id: string; document_id: string; source_system: string; source_version: string; source_row: number; external_item_id: string; external_pool_id: string }; digest: string; current: boolean; history: History[]; suppliers: { id: string; code: string; name: string; status: string }[]; documents: { id: string; filename: string }[]; can_edit: boolean };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function MaterialSupplierAttribution({ projectId, sourceId, onChanged }: { projectId: string; sourceId: string; onChanged?: () => void }) {
  const [data, setData] = useState<State | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [supplier, setSupplier] = useState(""), [evidence, setEvidence] = useState(""), [reason, setReason] = useState(""), [checked, setChecked] = useState(false), [notice, setNotice] = useState<string | null>(null);
  const requests = useRef(new Map<string, string>());
  const path = `/api/projects/${projectId}/npi/supply-snapshots/${sourceId}/supplier`;
  async function request(body?: object): Promise<State> {
    const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "供方关联暂不可用，请核对项目权限及原来源");
    return value as State;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作未完成"); } finally { setBusy(false); } }
  async function load() { const value = await request(); setData(value); setSupplier(value.history[0]?.supplier_id ?? ""); setEvidence(value.source.document_id); setChecked(false); }
  async function save() {
    if (!data || !checked) return;
    const body = { expected_version: data.history[0]?.version ?? 0, expected_digest: data.digest, supplier_id: supplier || null, evidence_id: evidence, reason };
    const key = JSON.stringify(body); let id = requests.current.get(key); if (!id) { id = crypto.randomUUID(); requests.current.set(key, id); }
    await request({ ...body, request_id: id }); setNotice(supplier ? "供方关联已保存到这一版供给来源。" : "当前供方关联已解除，原历史保留。"); await load(); onChanged?.();
  }
  return <details className="mt-2 rounded-md border p-2" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}><summary className="cursor-pointer text-xs">核对本版供给的实际供方</summary><div className="mt-2 space-y-2">
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}{notice && <p role="status" className="text-xs">{notice}</p>}<Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>读取原供给与关联历史</Button>
    {data && <><p className="text-xs">{data.source.source_system} / {data.source.source_version} · 原行 {data.source.source_row} · {data.source.external_pool_id} / {data.source.external_item_id}</p><a className="text-xs text-primary underline" href={`/api/document-previews/projects/${projectId}/${data.source.document_id}/original`} target="_blank" rel="noreferrer">打开原件核对供方</a><p className="text-xs">关联仅用于识别这一版来源中的供方，不确认交期或共享库存。新来源须重新核对。</p>
      {data.can_edit && data.current ? <fieldset disabled={busy} className="space-y-2"><label className="block text-xs">实际供方<select className={field} value={supplier} onChange={event => { setSupplier(event.target.value); setChecked(false); }}><option value="">解除原关联，供方保持未知</option>{data.suppliers.map(row => <option key={row.id} value={row.id} disabled={row.status !== "active"}>{row.code} · {row.name}{row.status !== "active" ? "（已停用）" : ""}</option>)}</select></label><label className="block text-xs">关联或纠正依据（最近200份项目资料）<select className={field} value={evidence} onChange={event => { setEvidence(event.target.value); setChecked(false); }}><option value="">选择实际证据</option>{!data.documents.some(doc => doc.id === data.source.document_id) && <option value={data.source.document_id}>原供给文件</option>}{data.documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label><label className="block text-xs">原行或证据位置及核对说明<textarea className={field} maxLength={2048} value={reason} onChange={event => { setReason(event.target.value); setChecked(false); }}/></label><label className="block text-xs"><input type="checkbox" checked={checked} onChange={event => setChecked(event.target.checked)}/> 已核对本版原件、对应行及实际供方；解除时已说明纠正依据</label><Button size="sm" disabled={!checked || !evidence || !reason.trim() || (!supplier && !data.history[0]?.supplier_id)} onClick={() => void act(save)}>保存具名关联版本</Button></fieldset> : <p className="text-xs">{!data.current ? "这份快照已不是当前可读来源，只查看历史；请到新来源重新核对。" : "当前只有读取权限。"}</p>}
      <details><summary className="cursor-pointer text-xs">最近20次关联与纠正</summary>{data.history.map(row => <div className="mt-2 border-t pt-2 text-xs" key={row.id}><p>v{row.version} · {row.snapshot.supplier ? `${row.snapshot.supplier.code} · ${row.snapshot.supplier.name}` : "解除关联"}</p><p>{row.reason} · {row.created_by_user_id} · {new Date(row.created_at).toLocaleString()}</p><a className="text-primary underline" href={`/api/document-previews/projects/${projectId}/${row.snapshot.evidence.id}/original`} target="_blank" rel="noreferrer">{row.snapshot.evidence.filename}</a></div>)}</details>
    </>}
  </div></details>;
}
