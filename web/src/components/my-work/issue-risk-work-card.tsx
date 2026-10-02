"use client";

import { CostGaps } from "@/components/projects/cost-gaps";
import { RiskTemplateFields } from "@/components/projects/risk-template-fields";
import { RiskBusinessReferences } from "@/components/projects/risk-business-references";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { IssueTemplateFields } from "@/components/projects/issue-template-fields";
import { MaterialExceptions } from "@/components/projects/material-exceptions";
import { IssueIntakeSource } from "@/components/projects/issue-intake-source";
import { DecisionSourceRows } from "@/components/projects/decision-intake-source";
import { MaterialIssueClosureReview, linkedMaterialReference, materialClosureContext, materialSelectionReady } from "@/components/projects/material-issue-closure-review";
import { WorkItemRequestError } from "@/components/projects/project-work-item-api";
import type { MaterialClosureReference } from "@/components/projects/project-work-item-types";

type Row = Record<string, unknown>;
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "" : String(value);
const labels: Record<string, string> = { open: "待处理", analysis: "分析中", action: "行动中", verification: "待验证", closed: "已关闭", mitigating: "缓解中", watching: "观察中" };
const fields: Record<string, string> = { description: "事实与说明", root_cause: "原因分析", resolution: "实际处理与解决措施", closure_criteria: "关闭条件", target_date: "目标日期", owner_user_id: "负责人", verifier_user_id: "验证人", mitigation_plan: "缓解措施", contingency_plan: "应急安排", likelihood: "发生可能性（1–5）", impact: "影响程度（1–5）" };
const assignment = new Set(["owner_user_id", "verifier_user_id", "target_date", "closure_criteria"]);
const fieldClass = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
export function IssueRiskWorkCard({ projectId, itemId, kind, onChanged, onNotice }: { projectId: string; itemId: string; kind: "issues" | "risks"; onChanged: () => Promise<void>; onNotice: (message: string) => void }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [mustRefresh, setMustRefresh] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({}), [evidence, setEvidence] = useState(""), [comment, setComment] = useState("");
  const [materialSelection, setMaterialSelection] = useState<MaterialClosureReference[] | null>(null), [linkedMaterial, setLinkedMaterial] = useState<MaterialClosureReference | null>(null);
  const base = `/api/projects/${projectId}/${kind}/${itemId}`, isIssue = kind === "issues";
  async function request(suffix: string, method = "GET", body?: Row) {
    const response = await fetch(base + suffix, { method, cache: "no-store", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new WorkItemRequestError(isRecord(value) && typeof obj(value.detail).message === "string" ? text(obj(value.detail).message) : "暂未取得办理结果，请保留输入并刷新原记录核对", response.status);
    if (!isRecord(value)) throw new Error("暂未取得办理结果，请保留输入并刷新原记录核对");
    return value;
  }
  async function load() {
    setBusy(true); setError(null);
    try { const card = await request("/work-card"); if (obj(card.item).id !== itemId || obj(card.item).project_id !== projectId) throw new Error("当前记录与办理入口不符，请刷新核对"); setData(card); setMaterialSelection(null); setLinkedMaterial(linkedMaterialReference(projectId, itemId, window.location.search)); setMustRefresh(false); }
    catch (e) { if (e instanceof WorkItemRequestError && [401, 403, 404].includes(e.status)) { setData(null); setMaterialSelection(null); } else if (e instanceof WorkItemRequestError && e.status === 409) setMaterialSelection(null); setError(e instanceof Error ? e.message : "读取失败"); setMustRefresh(true); }
    finally { setBusy(false); }
  }
  const item = obj(data?.item), permissions = obj(data?.permissions), people = rows(data?.people), state = text(item.status), actor = text(data?.actor_id);
  const editable = permissions.edit === true && state !== "closed" && (isIssue || item.draft_state === "confirmed");
  const relevant = isIssue ? ["description", "owner_user_id", "verifier_user_id", "target_date", "closure_criteria", "root_cause", "resolution"] : ["description", "owner_user_id", "target_date", "likelihood", "impact", "mitigation_plan", "contingency_plan"];
  const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) => relevant.includes(key) && value !== text(item[key])).map(([key, value]) => [key, ["likelihood", "impact"].includes(key) ? Number(value) : value.trim() || null]));
  const dirty = Object.keys(changes).length > 0;
  const person = (id: unknown) => !id ? "未指定" : text(people.find(value => value.id === id)?.name) || "原责任人（请核对项目成员）";
  const independentVerification = isIssue && (["high", "critical"].includes(text(item.severity)) || obj(data?.verification_policy)[`issue_verify_${item.severity}`] === true);
  const materialContext = materialClosureContext(data?.material_closure);
  const missing = isIssue ? ["owner_user_id", "verifier_user_id", "target_date", "closure_criteria"].filter(key => !item[key]) : [];
  async function save() {
    if (!dirty || !editable) return;
    setBusy(true); setError(null);
    try { const saved = await request("", "PATCH", { ...changes, expected_updated_at: item.updated_at }); setDraft({}); setData(old => ({ ...old, item: saved })); onNotice(`「${text(saved.title)}」的处理资料已保存。`); await onChanged(); await load(); }
    catch (e) { if (e instanceof WorkItemRequestError && [401, 403, 404].includes(e.status)) { setData(null); setMaterialSelection(null); } else if (e instanceof WorkItemRequestError && e.status === 409) setMaterialSelection(null); setError(e instanceof Error ? e.message : "保存未完成"); setMustRefresh(true); }
    finally { setBusy(false); }
  }
  async function transition(to: string) {
    setBusy(true); setError(null);
    try {
      const result = await request("/transitions", "POST", { to_status: to, expected_updated_at: item.updated_at, ...(isIssue ? { ...(to === "closed" ? { closure_evidence_ref: evidence.trim() || null, ...(materialContext?.required ? { material_closures: materialSelection } : {}) } : {}), ...(state === "verification" && to === "action" ? { comment: comment.trim() } : {}) } : {}) });
      setData(old => ({ ...old, item: result })); onNotice(`「${text(result.title)}」已更新为${labels[text(result.status)] ?? text(result.status)}。`); await onChanged(); await load();
    } catch (e) { if (e instanceof WorkItemRequestError && [401, 403, 404].includes(e.status)) { setData(null); setMaterialSelection(null); } else if (e instanceof WorkItemRequestError && e.status === 409) setMaterialSelection(null); setError(e instanceof Error ? e.message : "状态办理未完成"); setMustRefresh(true); }
    finally { setBusy(false); }
  }
  const disabled = busy || mustRefresh || dirty;
  const execute = permissions.execute === true;
  return <details className="mx-4 mb-3 rounded-lg border p-3 text-sm" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">查看依据并办理{isIssue ? "问题" : "风险"}</summary>
    <div className="mt-3 space-y-3">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新当前记录（保留填写内容）</Button>
      {data && <>
        <p className="font-medium">{text(item.title)} · {labels[state] ?? state}</p>
        <p>负责人：{person(item.owner_user_id)}{isIssue ? ` · 验证人：${person(item.verifier_user_id)}` : ""} · 目标日期：{text(item.target_date) || "未指定"}</p>
        <p className="text-xs text-muted-foreground">按实际业务记录与规则办理。{isIssue ? `提交验证后由${person(item.verifier_user_id)}接续核对；${independentVerification ? "本问题要求独立验证人及关闭证据。" : "关闭仍须符合项目流程要求。"}` : "缓解与观察状态分别记录，关闭不自动解除关联问题或其他项目工作。"}</p>
        {isIssue && missing.length > 0 && <p className="text-destructive">进入分析前需补齐：{missing.map(key => fields[key]).join("、")}。{permissions.assign !== true ? "请由有分派权限的成员补齐。" : "可在下方补齐并保存。"}</p>}
        {!isIssue && <RiskBusinessReferences projectId={projectId} riskId={itemId} />}
        {!isIssue && item.draft_state !== "confirmed" && <p className="text-destructive">风险当前尚未确认，请进入原风险记录核对候选状态。</p>}
        <fieldset disabled={busy || mustRefresh || !editable} className="grid gap-3 md:grid-cols-2">
          {relevant.map(key => { const value = draft[key] ?? text(item[key]), canEdit = !isIssue || !assignment.has(key) || permissions.assign === true; return <label key={key} className="block">{fields[key]}{key.endsWith("user_id") ? <select className={fieldClass} disabled={!canEdit} value={value} onChange={e => setDraft(old => ({ ...old, [key]: e.target.value }))}><option value="">未指定</option>{value && !people.some(person => person.id === value) && <option value={value}>原责任人（不在当前成员列表）</option>}{people.map(person => <option key={text(person.id)} value={text(person.id)} disabled={person.active !== true}>{text(person.name)}{person.active !== true ? "（已停用）" : ""}</option>)}</select> : key === "target_date" || ["likelihood", "impact"].includes(key) ? <input className={fieldClass} disabled={!canEdit} type={key === "target_date" ? "date" : "number"} min={key === "target_date" ? undefined : 1} max={key === "target_date" ? undefined : 5} value={value} onChange={e => setDraft(old => ({ ...old, [key]: e.target.value }))}/> : <textarea className={fieldClass} rows={3} maxLength={20000} disabled={!canEdit} value={value} onChange={e => setDraft(old => ({ ...old, [key]: e.target.value }))}/>}</label>; })}
        </fieldset>
        {dirty && <div className="space-y-2 rounded-md border p-2"><p>本次将修改 {Object.keys(changes).map(key => fields[key]).join("、")}；原状态保持，保存后再推进流程。</p>{Object.keys(changes).map(key => <p key={key} className="whitespace-pre-wrap break-words">{fields[key]} · 当前保存值：{key.endsWith("user_id") ? person(item[key]) : text(item[key]) || "未提供"}</p>)}<Button type="button" size="sm" disabled={busy || mustRefresh || !editable} onClick={() => void save()}>保存处理资料</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setDraft({})}>放弃本页字段修改</Button></div>}
        {!isIssue && <RiskTemplateFields projectId={projectId} riskId={itemId} currentStatus={state} currentVersion={text(item.updated_at)} onChanged={() => void load()}/>}
        {isIssue && <IssueTemplateFields projectId={projectId} issueId={itemId} currentStatus={state} currentVersion={text(item.updated_at)} onChanged={() => void load()}/>}
        {isIssue && state === "verification" && <div className="space-y-2"><MaterialIssueClosureReview context={materialContext} selected={materialSelection} onSelect={setMaterialSelection} disabled={busy || mustRefresh || permissions.verify !== true} linked={linkedMaterial}/><label className="block">验证及关闭证据<textarea className={fieldClass} rows={2} maxLength={2000} disabled={busy} value={evidence} onChange={e => setEvidence(e.target.value)}/></label><label className="block">验证未通过的退回原因<textarea className={fieldClass} rows={2} maxLength={2000} disabled={busy} value={comment} onChange={e => setComment(e.target.value)}/></label></div>}
        <div className="flex flex-wrap gap-2">
          {isIssue ? <>
            {state === "open" && <Button type="button" size="sm" disabled={disabled || !execute || missing.length > 0} onClick={() => void transition("analysis")}>进入分析</Button>}
            {state === "analysis" && <Button type="button" size="sm" disabled={disabled || !execute} onClick={() => void transition("action")}>进入行动</Button>}
            {state === "action" && <Button type="button" size="sm" disabled={disabled || !execute || item.owner_user_id !== actor} onClick={() => void transition("verification")}>提交验证</Button>}
            {state === "verification" && <><Button type="button" size="sm" disabled={disabled || permissions.verify !== true || !materialSelectionReady(materialContext, materialSelection) || (independentVerification && (item.verifier_user_id !== actor || item.owner_user_id === actor || !evidence.trim()))} onClick={() => void transition("closed")}>验证通过并关闭</Button><Button type="button" size="sm" variant="outline" disabled={disabled || !execute || item.verifier_user_id !== actor || !comment.trim()} onClick={() => void transition("action")}>退回行动</Button></>}
          </> : <>
            {["open", "watching"].includes(state) && <Button type="button" size="sm" disabled={disabled || !editable} onClick={() => void transition("mitigating")}>开始缓解</Button>}
            {["open", "mitigating"].includes(state) && <Button type="button" size="sm" variant="outline" disabled={disabled || !editable} onClick={() => void transition("watching")}>转为观察</Button>}
            {["mitigating", "watching"].includes(state) && <Button type="button" size="sm" variant="outline" disabled={disabled || !editable} onClick={() => void transition("closed")}>登记风险关闭</Button>}
          </>}
        </div>
        {typeof item.source_finding_id === "string" && <a className="block text-primary underline" href={`/ai-review?finding=${item.source_finding_id}`}>查看原建议、来源与人审回执</a>}
        {typeof item.source_field_capture_id === "string" && <a className="block text-primary underline" href={`/capture?project=${projectId}&capture=${item.source_field_capture_id}`}>查看现场原件与人工核对记录</a>}
        {isIssue && <><IssueIntakeSource projectId={projectId} issueId={itemId}/><MaterialExceptions projectId={projectId} issueId={itemId}/><CostGaps projectId={projectId} issueId={itemId}/><DecisionSourceRows projectId={projectId} issueId={itemId} onChanged={load}/></>}
        <a className="block text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${itemId}`}>查看原业务完整记录</a>
      </>}
      {mustRefresh && <p>资料可能已变化，或尚未取得明确回执。请先刷新原记录再继续，已填写内容保留。</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
