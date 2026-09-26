"use client";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null || v === "" ? "未记录" : String(v);
const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function ProfessionalChangeRoute({ projectId, sourceId, kind, canEdit }: { projectId: string; sourceId: string; kind: "engineering_review" | "firmware_package" | "cost_alternative"; canEdit: boolean }) {
  const [data, setData] = useState<Row | null>(null), [mode, setMode] = useState("new"), [ecrId, setEcrId] = useState(""), [code, setCode] = useState(""), [title, setTitle] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const attempt = useRef<{ id: string; signature: string } | null>(null);
  const base = `/api/projects/${projectId}/changes/professional-sources/${kind}/${sourceId}`;
  async function request(body?: unknown): Promise<Row> { const r = await fetch(base, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const v: unknown = await r.json(); if (!r.ok || !isRecord(v)) throw new Error(isRecord(v) && isRecord(v.detail) && typeof v.detail.message === "string" ? v.detail.message : "转入办理未完成，请重新核对"); return v; }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "办理未完成"); } finally { setBusy(false); } }
  async function read() { setData(await request()); }
  const existing = rows(data?.ecrs).find(e => e.id === ecrId), routed = obj(data?.routed_ecr);
  return <details className="mt-3 rounded-md border p-2" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(read); }}><summary className="cursor-pointer text-sm font-medium">转入正式工程变更</summary><div className="mt-3 space-y-3 text-xs">
    <p className="text-muted-foreground">核对资料版本和转入依据后，创建ECR或关联仍待分析的原ECR。影响分析与独立批准继续在工程变更中办理。</p>
    {data?.route != null ? <div className="space-y-1"><p>本资料已转入 <a className="text-primary underline" href={`/projects?project=${projectId}&tab=engineering#ecr-${text(routed.id)}`}>{text(routed.code)} · {text(routed.title)}</a></p><p>当前状态：{{ request: "变更申请", impact_analysis: "影响分析", approval: "待批准", approved: "已批准", rejected: "已拒绝" }[text(routed.status)] ?? text(routed.status)}</p><p>转入依据：{text(obj(data?.route).reason)}</p></div> : data && <>
      {!obj(data.basis).ready && <p className="text-primary">资料已有新版或出处已变化，请先核对并修订最新来源资料。</p>}
      {canEdit && obj(data.basis).ready === true && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
        const payload = { expected_digest: data.digest, reason: reason.trim(), ...(mode === "new" ? { code: code.trim(), title: title.trim() } : { ecr_id: ecrId, ecr_digest: existing?.digest }) };
        const signature = JSON.stringify(payload); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() }; await request({ ...payload, request_id: attempt.current.id }); setDirty(false); setNotice("转入回执已保存，继续在ECR办理影响分析。"); attempt.current = null; await read();
      }); }}><fieldset disabled={busy} className="space-y-3"><label className="block">转入方式<select className={input} value={mode} onChange={e => { setMode(e.target.value); setDirty(true); }}><option value="new">创建新的ECR</option><option value="existing" disabled={!rows(data.ecrs).length}>关联仍待分析的原ECR</option></select></label>{mode === "new" ? <div className="grid gap-3 sm:grid-cols-2"><label>ECR编号<input required maxLength={64} className={input} value={code} onChange={e => { setCode(e.target.value); setDirty(true); }} /></label><label>ECR标题<input required maxLength={512} className={input} value={title} onChange={e => { setTitle(e.target.value); setDirty(true); }} /></label></div> : <label className="block">原ECR<select required className={input} value={ecrId} onChange={e => { setEcrId(e.target.value); setDirty(true); }}><option value="">请选择</option>{rows(data.ecrs).map(e => <option key={text(e.id)} value={text(e.id)}>{text(e.code)} · {text(e.title)}</option>)}</select></label>}<label className="block">需要正式变更的范围与转入依据<textarea required maxLength={4000} className={input} value={reason} onChange={e => { setReason(e.target.value); setDirty(true); }} /></label><Button size="sm" type="submit" disabled={!reason.trim() || (mode === "new" ? !code.trim() || !title.trim() : !existing)}>确认转入ECR</Button></fieldset></form>}
    </>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}<Button type="button" size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(read)}>刷新来源与办理回执</Button>{dirty && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setDirty(false); setCode(""); setTitle(""); setReason(""); setEcrId(""); attempt.current = null; void act(read); }}>放弃未保存输入并刷新</Button>}
  </div></details>;
}
