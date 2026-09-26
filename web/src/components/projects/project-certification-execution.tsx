"use client";

import { QualityResponsibility } from "@/components/quality/quality-responsibility";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Certificate = { id: string; certificate_type: string; certificate_number: string | null; issuing_body: string | null; status: string; effective_status: string; target_markets: string[]; owner_name: string; is_required: boolean; valid_from: string | null; valid_until: string | null; evidence_reference: string | null; started_at: string | null; completed_at: string | null; payload_digest: string; can_start: boolean; can_complete: boolean; can_recertify: boolean; replaces_certification_id: string | null; recertification_reason: string | null };
type State = { items: Certificate[]; history: { id: string; certification_id: string; action: string; evidence: string; actor_name: string; created_at: string; event_row_id: number }[]; has_more: boolean; can_create: boolean };
const types: Record<string, string> = { un38_3: "UN 38.3", msds: "MSDS", battery_safety: "电池安全", product_safety: "产品安全", component_safety: "元器件安全", market_access: "市场准入", regulatory_compliance: "法规符合性" };
const statuses: Record<string, string> = { draft: "待形成证书", valid: "有效", expired: "已过期", revoked: "已撤销" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const when = (value: string | null) => value ? new Date(value).toLocaleString() : "未知";

export function ProjectCertificationExecution({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const [ownerLock, setOwnerLock] = useState<string | null>(null);
  const requests = useRef(new Map<string, string>());
  const path = `projects/${projectId}/execution/certifications`;
  async function load() { setData(await caseLinkRequest<State>(path)); }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "认证记录读取失败"); } finally { setBusy(false); } }
  async function create(form: HTMLFormElement) {
    const values = new FormData(form);
    setBusy(true); setError(null); setNotice(null);
    try {
      await caseLinkRequest(`projects/${projectId}/npi/certifications`, { certificate_type: values.get("certificate_type"), target_markets: String(values.get("markets") ?? "").split(/[,，]/).map((value) => value.trim()).filter(Boolean), is_required: values.get("is_required") === "on", status: "draft" });
      await load(); form.reset(); onChanged(); setNotice("认证工作已登记，可先纳入排程，再办理开工。");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "认证登记未完成"); }
    finally { setBusy(false); }
  }
  async function recertify(item: Certificate, form: HTMLFormElement) {
    const body = { expected_digest: item.payload_digest, reason: new FormData(form).get("reason") };
    const key = JSON.stringify({ projectId, id: item.id, operation: "recertification", body });
    let requestId = requests.current.get(key); if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    setBusy(true); setError(null); setNotice(null);
    try { await caseLinkRequest(`${path}/${item.id}/recertification`, { ...body, request_id: requestId }); await load(); onChanged(); setNotice("已创建关联原证书的新认证工作。登记新排程节点后，可在计划情景中明确替换原节点并转接依赖。"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "重新认证未创建"); }
    finally { setBusy(false); }
  }
  async function act(item: Certificate, form: HTMLFormElement, action: "start" | "complete") {
    const values = new FormData(form);
    const body = { action, expected_digest: item.payload_digest, evidence: values.get("evidence"), ...(action === "complete" ? { certificate_number: values.get("certificate_number"), issuing_body: values.get("issuing_body"), valid_from: values.get("valid_from") || null, valid_until: values.get("valid_until"), evidence_reference: values.get("evidence_reference") } : {}) };
    const key = JSON.stringify({ projectId, id: item.id, body }); let requestId = requests.current.get(key);
    if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    setBusy(true); setError(null); setNotice(null);
    try { await caseLinkRequest(`${path}/${item.id}`, { ...body, request_id: requestId }); await load(); onChanged(); setNotice(action === "start" ? "认证开工及依据已记录。" : "认证完成、证书资料和实际时间已记录。"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "认证办理未完成"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3">
    <Button size="sm" type="button" variant="outline" disabled={busy || !!ownerLock} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起认证办理" : "认证登记与办理"}</Button>
    {open && <>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <p className="text-xs text-muted-foreground">开工与完成记录办理时间，证书有效期单独填写。历史证书缺少实际时间时保持未知；重新认证登记新记录。</p>
      {data?.can_create && <details><summary className="cursor-pointer text-sm">登记认证工作</summary><form className="space-y-2 pt-2" onSubmit={(event) => { event.preventDefault(); void create(event.currentTarget); }}>
        <label className="block text-sm">认证类别<select required name="certificate_type" className={field} disabled={busy || !!ownerLock}>{Object.entries(types).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label className="block text-sm">目标市场<input name="markets" className={field} disabled={busy || !!ownerLock} maxLength={1024} placeholder="多个市场用逗号分隔" /></label>
        <label className="flex gap-2 text-sm"><input name="is_required" type="checkbox" disabled={busy || !!ownerLock} />本项目必需认证</label>
        <p className="text-xs">登记人作为初始负责人。</p><Button size="sm" disabled={busy || !!ownerLock}>登记待办认证</Button>
      </form></details>}
      {data && !data.items.length && <p className="text-sm">尚无认证记录。</p>}
      {data?.items.map((item) => <article className="space-y-2 border-t pt-3 text-sm" key={item.id} id={`certification-${item.id}`}>
        <p className="font-medium">{types[item.certificate_type] ?? item.certificate_type} · {item.certificate_number ?? "尚无证书编号"} · {statuses[item.effective_status] ?? item.effective_status}</p>
        <QualityResponsibility projectId={projectId} kind="certification" recordId={item.id} disabled={busy || !!ownerLock && ownerLock !== item.id} onLock={value => setOwnerLock(value ? item.id : null)} onChanged={async () => { await load(); onChanged(); }}/>
        <p className="text-xs">负责人：{item.owner_name} · {item.is_required ? "必需认证" : "按需认证"} · 市场：{item.target_markets.join("、") || "未填写"}</p>
        {item.replaces_certification_id && <p className="text-xs">重新认证来源：<a className="text-primary underline" href={`#certification-${item.replaces_certification_id}`}>{data.items.find((previous) => previous.id === item.replaces_certification_id)?.certificate_number ?? item.replaces_certification_id}</a> · {item.recertification_reason}</p>}
        <p className="text-xs">原始开工记录：{when(item.started_at)} · 原始完成记录：{when(item.completed_at)}</p>
        <p className="text-xs">证书有效期：{item.valid_from ?? "未填写"} → {item.valid_until ?? "未填写"}{item.issuing_body && ` · 签发机构：${item.issuing_body}`}</p>
        {item.evidence_reference && <p className="whitespace-pre-wrap text-xs">证书证据：{item.evidence_reference}</p>}
        {(item.can_start || item.can_complete) && <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void act(item, event.currentTarget, item.can_start ? "start" : "complete"); }}>
          {item.can_complete && <>
            <label className="block">证书编号<input required name="certificate_number" maxLength={256} defaultValue={item.certificate_number ?? ""} className={field} disabled={busy || !!ownerLock} /></label>
            <label className="block">签发机构<input required name="issuing_body" maxLength={256} defaultValue={item.issuing_body ?? ""} className={field} disabled={busy || !!ownerLock} /></label>
            <div className="grid gap-2 sm:grid-cols-2"><label>有效期开始<input type="date" name="valid_from" defaultValue={item.valid_from ?? ""} className={field} disabled={busy || !!ownerLock} /></label><label>有效期结束<input required type="date" name="valid_until" defaultValue={item.valid_until ?? ""} className={field} disabled={busy || !!ownerLock} /></label></div>
            <label className="block">证书证据引用<textarea required name="evidence_reference" maxLength={2048} defaultValue={item.evidence_reference ?? ""} className={field} disabled={busy || !!ownerLock} /></label>
          </>}
          <label className="block">{item.can_start ? "开工依据" : "完成依据"}<textarea required name="evidence" maxLength={2048} className={field} disabled={busy || !!ownerLock} /></label>
          <Button size="sm" disabled={busy || !!ownerLock}>{item.can_start ? "记录认证开工" : "确认认证完成与有效证书"}</Button>
        </form>}
        {item.can_recertify && <details><summary className="cursor-pointer text-xs">发起重新认证</summary><form className="space-y-2 pt-2" onSubmit={(event) => { event.preventDefault(); void recertify(item, event.currentTarget); }}><label className="block">重新认证原因<textarea required name="reason" maxLength={2048} className={field} disabled={busy || !!ownerLock} placeholder="说明到期续证、配置变更或其他重新认证依据" /></label><p className="text-xs">继承认证类别、目标市场和必需性；新记录单独办理，原证书、排程和资源预约保留。</p><Button size="sm" disabled={busy || !!ownerLock}>创建关联的认证工作</Button></form></details>}
        {data.history.some((entry) => entry.certification_id === item.id) && <details><summary className="cursor-pointer text-xs">办理依据</summary>{data.history.filter((entry) => entry.certification_id === item.id).map((entry) => <div className="my-2 border-l pl-2 text-xs" key={entry.id}><p>{entry.action === "start" ? "开工" : "完成"} · {entry.actor_name} · {when(entry.created_at)}</p><p className="whitespace-pre-wrap">{entry.evidence}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${entry.event_row_id}`}>查看办理事件</a></div>)}</details>}
      </article>)}
      {data?.has_more && <p className="text-xs">显示最近 500 项认证，更早记录仍保留。</p>}
      <Button size="sm" type="button" variant="ghost" disabled={busy || !!ownerLock} onClick={() => void refresh()}>刷新认证办理</Button>
    </>}
  </section>;
}
