"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const text = (value: unknown) => value == null || value === "" ? "未记录" : String(value);
export function TestVerificationPath({ projectId, caseId, canEdit, onSaved }: {
  projectId: string; caseId: string; canEdit: boolean; onSaved: () => Promise<void>;
}) {
  const [data, setData] = useState<{ case: Row; plan: Row; specs: Row[]; digest: string; editable: boolean } | null>(null);
  const [specId, setSpecId] = useState(""), [method, setMethod] = useState(""), [criteria, setCriteria] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [saved, setSaved] = useState(false);
  const base = `/api/projects/${projectId}/npi/test-cases/${caseId}/verification-path`;
  async function read() {
    const response = await fetch(base, { cache: "no-store" }); const value: unknown = await response.json();
    if (!response.ok || !isRecord(value) || !isRecord(value.case) || !isRecord(value.plan) || !Array.isArray(value.specifications)) throw new Error("验证关系暂不可用，请刷新重试");
    setData({ case: value.case, plan: value.plan, specs: value.specifications.filter(isRecord), digest: String(value.digest), editable: value.can_edit === true });
    setSpecId(typeof value.case.specification_id === "string" ? value.case.specification_id : "");
    setMethod(typeof value.case.method === "string" ? value.case.method : ""); setCriteria(typeof value.case.acceptance_criteria === "string" ? value.case.acceptance_criteria : ""); setReason("");
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "保存未完成"); } finally { setBusy(false); } }
  const selected = data?.specs.find(spec => spec.id === specId);
  return <details className="basis-full rounded-md border p-2" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(read); }}>
    <summary className="cursor-pointer text-sm font-medium">客户要求、规格与验证方法</summary>
    <div className="mt-3 space-y-3">
      {data && <>
        <p className="text-xs">{text(data.plan.phase).toUpperCase()} · 计划样机 {text(data.plan.sample_size)} 台 · {text(data.case.category)}</p>
        {!data.editable && <p className="text-xs text-muted-foreground">已有测试、结果或后续计划版本，本项验证关系保留追溯；调整请在最新计划修订中办理。</p>}
        <form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(async () => {
          const response = await fetch(base, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_digest: data.digest, specification_id: specId || null, specification_digest: selected?.digest ?? null, method: method.trim(), acceptance_criteria: criteria.trim(), reason: reason.trim() }) });
          const value: unknown = await response.json();
          if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "验证关系保存未完成");
          setSaved(true); await read(); await onSaved();
        }); }}>
          <fieldset disabled={busy || !canEdit || !data.editable} className="space-y-3">
            <label className="block text-xs">验证哪一项项目规格<select className={field} value={specId} onChange={e => { setSpecId(e.target.value); setSaved(false); }}><option value="">尚未关联，需要说明原因</option>{data.specs.map(spec => <option key={text(spec.id)} value={text(spec.id)}>{text(spec.code)} · {text(spec.title)} · v{text(spec.version)}</option>)}</select></label>
            <label className="block text-xs">本测试项的方法<textarea required maxLength={10000} className={field} value={method} onChange={e => { setMethod(e.target.value); setSaved(false); }} /></label>
            <label className="block text-xs">本测试项的判定依据<textarea required maxLength={10000} className={field} value={criteria} onChange={e => { setCriteria(e.target.value); setSaved(false); }} /></label>
            {canEdit && data.editable && <><label className="block text-xs">关联与方法核对依据<textarea required maxLength={2000} className={field} value={reason} onChange={e => setReason(e.target.value)} /></label><Button type="submit" size="sm" disabled={!reason.trim() || !method.trim() || !criteria.trim()}>保存验证关系及方法</Button></>}
          </fieldset>
        </form>
        {selected && <div className="space-y-1 rounded-md bg-muted/40 p-3 text-xs"><p>规格：{text(selected.code)} · {text(selected.title)} · v{text(selected.version)} · {selected.criticality === "key" ? "关键规格" : "普通规格"}</p><p>来源需求：{text(selected.requirement_code)} · {text(selected.requirement_title)}</p><p className="whitespace-pre-wrap">规格验证方法：{text(selected.verification_method)}</p><p className="whitespace-pre-wrap">规格判据：{text(selected.acceptance_criteria)}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=engineering#spec-${text(selected.id)}`}>查看当前规格</a></div>}
        <p className="text-xs text-muted-foreground">关联表示验证路径已登记；测试结果、实际样机数量和证据由逐次测试记录确定。</p>
      </>}
      {saved && <p role="status" className="text-xs">验证关系已保存。</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      <Button type="button" size="sm" variant="outline" disabled={busy || (!!data && !!reason.trim())} onClick={() => void act(read)}>重新读取当前关系</Button>
    </div>
  </details>;
}
