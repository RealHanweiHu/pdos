"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { FmeaSourceValue, field, obj, rows, text, type Row } from "./fmea-sources";

const ncrLabels: Record<string, string> = { open: "NCR 已建立", containment: "遏制中", root_cause: "根因调查", action: "措施执行", verification: "有效性验证", closed: "已关闭" };
const issueLabels: Record<string, string> = { open: "待分析", analysis: "分析中", action: "行动中", verification: "待验证", closed: "已关闭" };
async function request(project: string, path: string, body?: unknown): Promise<Row> {
  const response = await fetch(`/api/projects/${project}/quality/issue-links${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const value: unknown = await response.json();
  if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || "质量关联操作未完成，请读取原记录");
  return obj(value);
}
function StateSummary({ issue, ncr, people }: { issue: Row; ncr: Row; people: Row }) {
  const actions = rows(ncr.actions), complaint = obj(ncr.complaint);
  return <div className="space-y-2 text-sm"><p>问题协调：{text(issue.title)} · {issueLabels[text(issue.status)] ?? text(issue.status)}</p>
    {issue.owner_user_id != null && <p className="text-xs">问题负责人：{text(people[text(issue.owner_user_id)]) || "原具名负责人"}；验证人：{text(people[text(issue.verifier_user_id)]) || "尚未指定"}</p>}
    <p>质量处理：{text(ncr.code)} · {ncrLabels[text(ncr.status)] ?? text(ncr.status)} · 目标日期 {text(ncr.target_date)}</p>
    <p className="whitespace-pre-wrap">不符合事实：{text(ncr.nonconformity)}</p>
    {complaint.id != null && <details className="text-xs"><summary className="cursor-pointer">原质量反馈与证据</summary><p>{text(complaint.code)} · {({ internal: "内部发现", field: "现场失效", rma: "退货 / RMA", customer: "客户反馈" } as Record<string,string>)[text(complaint.source)] ?? text(complaint.source)} · {text(complaint.occurred_at)}</p><p className="whitespace-pre-wrap">{text(complaint.description)}</p>{rows(ncr.complaint_documents).map(d => <div key={text(d.id)} className="mt-2 rounded-md border p-2"><p>{d.available ? text(obj(d.value).filename) : "原证据文件当前不可用"}</p>{d.available === true && <><FmeaSourceValue value={obj(d.value)}/><a className="text-primary underline" href={`/projects?project=${ncr.project_id}&tab=documents&entity_id=${d.id}`}>在原项目文件中查看</a></>}</div>)}</details>}
    <FmeaSourceValue value={ncr}/>
    {actions.length > 0 && <details><summary className="cursor-pointer">实际 CAPA 措施与完成回执（{actions.length}）</summary>{actions.map(a => <div key={text(a.id)} className="mt-2 rounded-md border p-2"><p>{a.action_type === "preventive" ? "预防措施" : "纠正措施"} · {({ planned: "待执行", in_progress: "执行中", completed: "措施已完成" } as Record<string,string>)[text(a.status)] ?? text(a.status)}</p><p>{text(a.description)}</p><p>负责人：{text(people[text(a.owner_user_id)]) || "原具名负责人"} · {text(a.due_date)}</p>{a.completion_summary != null && <p className="whitespace-pre-wrap">完成说明：{text(a.completion_summary)}</p>}</div>)}</details>}
    {issue.resolution != null && <p className="whitespace-pre-wrap">问题处理说明：{text(issue.resolution)}</p>}
    {issue.closure_evidence_ref != null && <p className="whitespace-pre-wrap">问题关闭依据：{text(issue.closure_evidence_ref)}</p>}
  </div>;
}
export function IssueQualityLinks({ projectId, issueId, ncrId }: { projectId: string; issueId?: string; ncrId?: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [mode, setMode] = useState<"link" | "escalate" | null>(null), [options, setOptions] = useState<Row[]>([]), [next, setNext] = useState<number | null>(null), [selected, setSelected] = useState("");
  const [documents, setDocuments] = useState<Row[]>([]), [documentNext, setDocumentNext] = useState<number | null>(null);
  const [reason, setReason] = useState(""), [retractId, setRetractId] = useState<string | null>(null), [retractReason, setRetractReason] = useState("");
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  function id(body: unknown) { const signature = JSON.stringify(body); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() }; return attempt.current.id; }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(""); try { await fn(); } catch(e) { setError(e instanceof Error ? e.message : "办理失败"); } finally { setBusy(false); } }
  const anchorQuery = issueId ? `issue_id=${issueId}` : `ncr_id=${ncrId}`;
  async function read(more = false) { const value = await request(projectId, `?${anchorQuery}&offset=${more ? data?.next_offset ?? 0 : 0}`); setData(old => more && old ? { ...value, items: [...rows(old.items), ...rows(value.items)], people: { ...obj(old.people), ...obj(value.people) } } : value); }
  async function loadOptions(more = false) { const value = await request(projectId, `/options?kind=${issueId ? "ncr" : "issue"}&offset=${more ? next ?? 0 : 0}`); setOptions(old => more ? [...old, ...rows(value.items)] : rows(value.items)); setNext(typeof value.next_offset === "number" ? value.next_offset : null); }
  async function loadDocuments(more = false) { const value = await request(projectId, `/options?kind=document&offset=${more ? documentNext ?? 0 : 0}`); setDocuments(old => more ? [...old, ...rows(value.items)] : rows(value.items)); setDocumentNext(typeof value.next_offset === "number" ? value.next_offset : null); }
  const anchor = obj(data?.anchor), other = options.find(o => o.id === selected), people = obj(data?.people);
  const locked = busy || mode !== null || retractId !== null;
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => read()); }}>
    <summary className="cursor-pointer font-medium">{issueId ? "质量升级与 NCR/CAPA 关联" : "关联的问题协调与执行反馈"}</summary>
    <div className="mt-3 space-y-3"><p className="text-xs text-muted-foreground">关联与升级保留双方原状态。问题关闭、措施完成和质量有效性分别按原流程核验。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={locked} onClick={() => void act(() => read())}>刷新双方进展</Button>{data?.can_link === true && <Button size="sm" variant="outline" disabled={locked} onClick={() => void act(async () => { await read(); await loadOptions(); setSelected(""); setReason(""); setMode("link"); })}>关联已有{issueId ? " NCR" : "问题"}</Button>}{issueId && data?.can_escalate === true && <Button size="sm" disabled={locked} onClick={() => void act(async () => { await read(); setDocuments([]); setDocumentNext(null); setReason(""); setMode("escalate"); })}>升级为质量整改</Button>}</div>
      {data && !rows(data.items).length && <p className="text-sm">尚未建立质量关联。</p>}
      {rows(data?.items).map(link => { const left = obj(link.issue), right = obj(link.ncr), undone = obj(link.retraction); return <details key={text(link.id)} className="space-y-2 rounded-md border p-3"><summary className="cursor-pointer">{issueId ? text(right.code) : text(left.title)} · {link.retraction ? "历史关联已解除" : "有效关联"} · {issueLabels[text(left.status)] ?? text(left.status)} / {ncrLabels[text(right.status)] ?? text(right.status)}</summary>
        <p className="text-xs">{text(people[text(link.created_by_user_id)])} · {text(link.created_at)} · {link.origin === "escalated" ? "原问题升级" : "显式关联"}</p><p className="whitespace-pre-wrap text-sm">关联依据：{text(link.reason)}</p>
        {link.has_later_changes === true && <p className="text-xs text-primary">双方已有后续记录，以下为当前进展；原关联时快照保留在历史中。</p>}
        <StateSummary issue={left} ncr={right} people={people}/>
        <div className="flex flex-wrap gap-3 text-xs"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${left.id}#issue-${left.id}`}>打开原问题</a><a className="text-primary underline" href={`/projects?project=${projectId}&tab=quality&ncr=${right.id}`}>打开原 NCR/CAPA</a></div>
        <details className="text-xs"><summary className="cursor-pointer">关联时原始资料</summary><StateSummary issue={obj(obj(link.snapshot).issue)} ncr={obj(obj(link.snapshot).ncr)} people={people}/></details>
        {link.retraction ? <p className="text-xs">解除人：{text(people[text(undone.created_by_user_id)])} · {text(undone.created_at)} · {text(undone.reason)}</p> : data?.can_retract === true && <Button size="sm" variant="outline" disabled={locked} onClick={() => { setRetractId(text(link.id)); setRetractReason(""); }}>更正误关联 / 解除</Button>}
        {retractId === link.id && <form className="space-y-2" onSubmit={e => { e.preventDefault(); void act(async () => { const body = { expected_digest: link.digest, reason: retractReason.trim() }; await request(projectId, `/${link.id}/retract`, { ...body, request_id: id(body) }); setRetractId(null); await read(); }); }}><label className="block text-sm">解除依据<textarea required maxLength={4000} className={field} disabled={busy} value={retractReason} onChange={e => setRetractReason(e.target.value)}/></label><p className="text-xs">仅解除关联，双方业务记录和历史证据继续保留。</p><Button size="sm" disabled={busy} type="submit">记录解除</Button><Button className="ml-2" size="sm" variant="outline" disabled={busy} type="button" onClick={() => setRetractId(null)}>取消</Button></form>}
      </details>; })}
      {data?.next_offset != null && <Button size="sm" variant="outline" disabled={locked} onClick={() => void act(() => read(true))}>更早关联</Button>}
      {mode === "link" && <form className="space-y-2 rounded-md border p-3" onSubmit={e => { e.preventDefault(); if (!other) return; void act(async () => { const body = { issue_id: issueId ?? selected, ncr_id: ncrId ?? selected, expected_issue_digest: issueId ? data?.anchor_digest : other.digest, expected_ncr_digest: ncrId ? data?.anchor_digest : other.digest, reason: reason.trim() }; await request(projectId, "", { ...body, request_id: id(body) }); setMode(null); await read(); }); }}><fieldset className="space-y-2" disabled={busy}>
        <label className="block text-sm">选择本项目原{issueId ? " NCR" : "问题"}<select required className={field} value={selected} onChange={e => setSelected(e.target.value)}><option value="">请选择</option>{options.map(o => <option key={text(o.id)} value={text(o.id)}>{text(obj(o.value).code || obj(o.value).title)} · {text(obj(o.value).status)}</option>)}</select></label>
        {next !== null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadOptions(true))}>更多原记录</Button>}
        {other && <StateSummary issue={issueId ? anchor : obj(other.value)} ncr={ncrId ? anchor : obj(other.value)} people={people}/>}
        <label className="block text-sm">双方关联的具体依据<textarea required maxLength={4000} className={field} value={reason} onChange={e => setReason(e.target.value)}/></label>
        <Button type="submit" size="sm" disabled={!other}>保存关联</Button><Button className="ml-2" type="button" size="sm" variant="outline" onClick={() => setMode(null)}>取消</Button>
      </fieldset></form>}
      {mode === "escalate" && issueId && <form className="space-y-2 rounded-md border p-3" onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); void act(async () => {
        const body = { issue_id: issueId, expected_issue_digest: data?.anchor_digest, expected_links_digest: data?.links_digest, separate_nonconformity: form.get("separate") === "on", reason: String(form.get("reason")).trim(), owner_user_id: form.get("owner"), title: String(form.get("title")).trim(), source: form.get("source"), occurred_at: new Date(String(form.get("occurred_at"))).toISOString(), nonconformity: String(form.get("nonconformity")).trim(), requirement_reference: String(form.get("requirement")).trim(), severity: form.get("severity"), target_date: form.get("date"), affected_scope: String(form.get("scope")).trim() || null, affected_quantity: form.get("quantity") === "" ? null : Number(form.get("quantity")), document_ids: form.getAll("document_id").map(String) };
        await request(projectId, "/escalate", { ...body, request_id: id(body) }); setMode(null); await read();
      }); }}><fieldset disabled={busy} className="space-y-2"><legend className="px-1 font-medium">从原问题登记质量整改</legend>
        <p className="text-xs">同一次提交建立原质量反馈、NCR 和问题关联；不复制问题状态、根因或关闭结论。</p>
        <label className="block text-sm">质量记录名称<input required maxLength={512} name="title" defaultValue={text(anchor.title)} className={field}/></label>
        <label className="block text-sm">已观察到的不符合事实<textarea required maxLength={20000} name="nonconformity" defaultValue={text(anchor.description)} className={field}/></label>
        <label className="block text-sm">不符合的原要求 / 证据定位<textarea required maxLength={20000} name="requirement" className={field}/></label>
        <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">原反馈来源<select name="source" className={field}><option value="internal">内部发现</option><option value="field">现场失效</option><option value="rma">退货 / RMA</option></select></label><label className="text-sm">实际发生时间<input required type="datetime-local" name="occurred_at" className={field}/></label><label className="text-sm">质量负责人<select required name="owner" defaultValue="" className={field}><option value="">选择项目成员</option>{rows(data?.members).map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.name)}</option>)}</select></label><label className="text-sm">目标日期<input required type="date" name="date" className={field}/></label><label className="text-sm">质量严重度<select name="severity" defaultValue={text(anchor.severity) || "medium"} className={field}><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">严重</option></select></label><label className="text-sm">已知影响数量（未知留空）<input type="number" min={0} step={1} name="quantity" className={field}/></label></div>
        <label className="block text-sm">已知影响范围<textarea maxLength={20000} name="scope" className={field}/></label><label className="block text-sm">升级依据 / 与已有异常的区别<textarea required maxLength={4000} name="reason" className={field}/></label>
        {rows(data?.items).length > 0 && <label className="flex items-start gap-2 text-sm"><input required type="checkbox" name="separate"/><span>已核对原关联，本次确属另一独立不符合，需要新增 NCR。</span></label>}
        <details className="rounded-md border p-2"><summary className="cursor-pointer text-sm">关联原项目证据文件</summary><Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadDocuments())}>读取可用文件</Button>{documents.map(d => <label key={text(d.id)} className="mt-2 flex items-start gap-2 text-sm"><input type="checkbox" name="document_id" value={text(d.id)}/><span>{text(obj(d.value).filename)}</span></label>)}{documentNext !== null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadDocuments(true))}>更多文件</Button>}</details>
        <Button type="submit" size="sm">登记并关联原问题</Button><Button className="ml-2" type="button" size="sm" variant="outline" onClick={() => setMode(null)}>取消</Button>
      </fieldset></form>}
    </div>
  </details>;
}
