"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { obj, rows, text, type Row } from "./fmea-sources";

type Kind = "complaint" | "ncr" | "capa" | "certification" | "reservation" | "specification";
type Request = { request_id: string; expected_digest: string; owner_user_id: string; reason: string };
const labels = { complaint: "客诉", ncr: "不符合项", capa: "CAPA 措施", certification: "认证工作", reservation: "资源预约", specification: "产品规格" };
const statuses: Record<string, string> = { proposed: "预约提案", reserved: "已占用", released: "已释放", cancelled: "已取消", draft: "办理中，尚未形成证书", valid: "证书有效", expired: "已过期", revoked: "已撤销", open: "待办理", triaged: "已分诊", investigating: "调查中", resolved: "已解决", closed: "已关闭", containment: "遏制办理", root_cause: "根因调查", action: "措施执行", verification: "独立有效性验证", planned: "待执行", in_progress: "执行中", completed: "已完成" };
async function readWorkspace(url: string): Promise<Row> {
  const response = await fetch(url, { cache: "no-store" });
  const value = await responseBody(response);
  if (!response.ok || !isRecord(value) || !isRecord(value.record) || typeof value.digest !== "string" || !Array.isArray(value.history) || !Array.isArray(value.members)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "责任记录暂不可用");
  return value;
}
export function QualityResponsibilityLanding({ projectId }: { projectId: string }) {
  const search = useSearchParams(), kind = search.get("quality_owner_kind"), id = search.get("quality_owner_id");
  if (!kind || !["complaint", "ncr", "capa", "certification"].includes(kind) || !id || !/^[0-9a-f-]{36}$/.test(id)) return null;
  return <div className="mb-4 rounded-md border p-3"><h3 className="mb-2 font-medium">本次移交的质量责任</h3><QualityResponsibility key={`${projectId}:${kind}:${id}`} projectId={projectId} kind={kind as Kind} recordId={id} initiallyOpen/></div>;
}
export function ReservationResponsibilityLanding({ projectId }: { projectId: string }) {
  const id = useSearchParams().get("reservation_owner_id");
  if (!id || !/^[0-9a-f-]{36}$/.test(id)) return null;
  return <div className="mb-4 rounded-md border p-3"><h3 className="mb-2 font-medium">本次移交的资源预约</h3><QualityResponsibility key={`${projectId}:${id}`} projectId={projectId} kind="reservation" recordId={id} initiallyOpen/></div>;
}
export function SpecificationResponsibilityLanding({ projectId }: { projectId: string }) {
  const id = useSearchParams().get("specification_owner_id");
  if (!id || !/^[0-9a-f-]{36}$/.test(id)) return null;
  return <div className="mb-4 rounded-md border p-3"><h3 className="mb-2 font-medium">本次移交的规格责任</h3><QualityResponsibility key={`${projectId}:${id}`} projectId={projectId} kind="specification" recordId={id} initiallyOpen/></div>;
}
export function QualityResponsibility({ projectId, kind, recordId, disabled = false, initiallyOpen = false, onLock, onChanged }: { projectId: string; kind: Kind; recordId: string; disabled?: boolean; initiallyOpen?: boolean; onLock?: (locked: boolean) => void; onChanged?: () => void | Promise<void> }) {
  const base = kind === "specification" ? `/api/projects/${projectId}/product-engineering/specifications/${recordId}/owner-transfer` : kind === "reservation" ? `/api/projects/${projectId}/resource-reservations/${recordId}/owner-transfer` : `/api/projects/${projectId}/quality/responsibilities/${kind}/${recordId}`;
  const [data, setData] = useState<Row | null>(null), [opened, setOpened] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [owner, setOwner] = useState(""), [reason, setReason] = useState(""), [receipt, setReceipt] = useState("");
  const [replacementId, setReplacementId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Request | null>(null), [pending, setPending] = useState<Request | null>(null);
  useEffect(() => {
    if (!initiallyOpen) return;
    let active = true;
    void readWorkspace(base).then(value => { if (active) { setData(value); setOpened(true); } }, failure => { if (active) setError(failure instanceof Error ? failure.message : "读取失败"); });
    return () => { active = false; };
  }, [base, initiallyOpen]);
  async function load(before?: number) {
    const value = await readWorkspace(`${base}${before ? `?before_id=${before}` : ""}`);
    setData(old => before && old ? { ...old, history: [...rows(old.history), ...rows(value.history).filter(r => !rows(old.history).some(v => v.id === r.id))], next_before_id: value.next_before_id } : value);
  }
  async function refresh(before?: number) {
    setBusy(true); setError("");
    try { await load(before); setOpened(true); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save(body: Request) {
    setPending(body); setBusy(true); setError(""); onLock?.(true);
    try {
      const response = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); }
        throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "责任调整结果待确认，请按原请求重试");
      }
      if (!isRecord(value) || value.request_id !== body.request_id || typeof value.audit_id !== "number") throw new Error("回执不完整，请按原请求重试");
      if ((kind === "reservation" || kind === "specification") && isRecord(value.record) && typeof value.record.id === "string" && /^[0-9a-f-]{36}$/.test(value.record.id)) setReplacementId(value.record.id);
      setReceipt(`负责人已调整，回执 ${value.audit_id} · 原请求 ${body.request_id}`); setPending(null); setPreview(null); setOwner(""); setReason(""); onLock?.(false);
      await load(); await onChanged?.();
    } catch (e) { setError(e instanceof Error ? e.message : "办理失败"); }
    finally { setBusy(false); }
  }
  const successorLink = (id: string) => `/projects?project=${projectId}&tab=overview&${kind === "specification" ? "specification" : "reservation"}_owner_id=${id}`;
  const locked = disabled || busy || !!preview || !!pending;
  const current = obj(data?.record);
  return <section className="space-y-2 text-sm" aria-label={`${labels[kind]}责任调整`}>
    <Button type="button" size="sm" variant="outline" disabled={disabled || busy || !!pending} onClick={() => { if (opened) { setOpened(false); setPreview(null); setOwner(""); setReason(""); onLock?.(false); } else void refresh(); }}>{opened ? "收起责任办理" : "负责人调整与历史"}</Button>
    {error && <p role="alert" className="text-destructive">{error}</p>}{receipt && <p role="status" className="break-all">{receipt}</p>}
    {replacementId && <Link className="block text-primary underline" href={successorLink(replacementId)}>{kind === "specification" ? "打开接手人新规格版本" : "打开新负责人预约"}</Link>}
    {opened && data && <div className="space-y-3 rounded-md border p-3">
      <p>{labels[kind]}所选记录负责人：{text(data.owner_name) || "未指定"}{kind === "specification" ? ` · v${text(current.version)}` : ` · ${statuses[text(current.status)] ?? text(current.status)}`}</p>
      <p className="whitespace-pre-wrap">{text(current.title) || text(current.nonconformity) || text(current.description) || text(current.certificate_type)}</p>
      {kind === "reservation" && <p>{text(current.window_start)} — {text(current.window_end)} · {text(current.parallel_units)} 单位 · {current.occupancy_policy === "working_only" ? "工作时段" : "全窗口"}<br/>原预约依据：{text(current.basis)}</p>}
      {kind === "specification" && <div className="space-y-2"><p>{text(current.code)} · {current.criticality === "key" ? "关键规格" : "一般规格"}</p><p className="whitespace-pre-wrap">验证方法：{text(current.verification_method) || "未填写"}</p><p className="whitespace-pre-wrap">验收标准：{text(current.acceptance_criteria) || "未填写"}</p><details><summary className="cursor-pointer">原规格内容（新版本沿用）</summary><pre className="whitespace-pre-wrap break-words text-xs">{JSON.stringify(current.content, null, 2)}</pre></details>{typeof data.latest_id === "string" && /^[0-9a-f-]{36}$/.test(data.latest_id) && data.latest_id !== recordId && <p>本版为历史记录，<Link className="text-primary underline" href={successorLink(data.latest_id)}>打开当前 v{text(data.latest_version)} 规格</Link>。</p>}</div>}
      {current.due_date || current.target_date ? <p>原目标日期：{text(current.due_date) || text(current.target_date)}</p> : null}
      <p className="text-xs text-muted-foreground">{kind === "specification" ? "以同编号下一版本接续负责人，保留原内容、来源需求、验证方法和验收标准。已有 BOM、测试与评审仍固定原版本；引用升级须另行核对并按原业务办理。" : kind === "reservation" ? "同一事务中结束旧预约并以新负责人建立相同节点、资源、容量版本、时间和数量的预约。正式占用须由资源管理员重新确认；容量或节点条件不满足时旧预约保持不变。此操作不转移原任务责任。" : kind === "certification" ? "保留原认证类别、目标市场、原证书关系、开工时间及办理依据；调整负责人不代表取得新证书，也不变更排程或资源预约。" : "调整在办责任，保留原内容、期限、进度和证据。历任措施负责人仍须回避独立有效性验证；接手不代表已完成或已通过验证。"}</p>
      <Button type="button" size="sm" variant="ghost" disabled={locked || !!owner || !!reason} onClick={() => void refresh()}>刷新原记录</Button>
      {data.can_reassign === true && <fieldset className="space-y-2" disabled={locked}>
        <label className="block">接手人<select className="mt-1 w-full rounded-md border bg-background p-2" value={owner} onChange={e => { setOwner(e.target.value); onLock?.(!!e.target.value || !!reason); }}><option value="">选择具备此项职责的项目成员</option>{rows(data.members).filter(m => m.id !== current.owner_user_id).map(m => <option value={text(m.id)} key={text(m.id)}>{text(m.name)}</option>)}</select></label>
        <label className="block">责任调整原因<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={2048} value={reason} onChange={e => { setReason(e.target.value); onLock?.(!!owner || !!e.target.value); }}/></label>
        <Button type="button" size="sm" disabled={!owner || !reason.trim()} onClick={() => { setPreview({ request_id: crypto.randomUUID(), expected_digest: text(data.digest), owner_user_id: owner, reason: reason.trim() }); onLock?.(true); }}>预览责任调整</Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => { setOwner(""); setReason(""); onLock?.(false); }}>清除输入</Button>
      </fieldset>}
      {preview && !pending && <div className="space-y-2 rounded-md border p-2"><p>将由 {text(data.owner_name)} 移交给 {text(rows(data.members).find(m => m.id === preview.owner_user_id)?.name)}。</p><p className="whitespace-pre-wrap">{preview.reason}</p>{kind === "specification" && <p>将创建 v{Number(current.version) + 1}，原 v{text(current.version)} 及其引用保持历史记录。</p>}<Button type="button" size="sm" disabled={busy || disabled} onClick={() => void save(preview)}>{kind === "specification" ? "确认新建接续版本" : "确认调整负责人"}</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div>}
      {pending && <div><p className="break-all">原请求 {pending.request_id} 的结果待确认。</p><Button type="button" size="sm" disabled={busy} variant="outline" onClick={() => void save(pending)}>按原请求重试</Button></div>}
      <details><summary className="cursor-pointer">历次责任调整（{rows(data.history).length} 条已加载）</summary><div className="mt-2 space-y-2">{rows(data.history).map(h => {
        const context = obj(h.context), people = obj(context.people), before = obj(h.before_snapshot), after = obj(h.after_snapshot);
        const person = (id: unknown) => text(people[text(id)]) || text(id);
        return <article className="rounded-md border p-2" key={text(h.id)}><p>{person(before.owner_user_id)} → {person(after.owner_user_id)}</p><p>{text(h.created_at)} · 办理人 {person(h.actor_user_id)}</p><p className="whitespace-pre-wrap">{text(context.reason)}</p>{kind === "specification" ? <p className="text-xs">规格 v{text(before.version)} → v{text(after.version)}</p> : <p className="text-xs text-muted-foreground">当时进度：{statuses[text(after.status ?? after.state)] ?? text(after.status ?? after.state)} · {text(after.due_date) || text(after.target_date) || "未设目标日期"}</p>}{(kind === "reservation" || kind === "specification") && typeof after.id === "string" && /^[0-9a-f-]{36}$/.test(after.id) && <Link className="text-primary underline" href={successorLink(after.id)}>{kind === "specification" ? "查看本次接续版本" : "查看本次新预约"}</Link>}</article>;
      })}{!rows(data.history).length && <p>暂无责任调整记录。</p>}{typeof data.next_before_id === "number" && <Button type="button" size="sm" disabled={busy} variant="outline" onClick={() => void refresh(data.next_before_id as number)}>加载更早记录</Button>}</div></details>
    </div>}
  </section>;
}
