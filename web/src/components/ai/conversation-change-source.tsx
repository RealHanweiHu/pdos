"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { ChangeAnalysisPreparation } from "@/components/projects/change-analysis-preparation";

export type ConversationChangeSourceValue = { ecrId: string; digest: string; depth: number; ready: boolean; allowDiscussion: boolean; includeSupplierNotices: boolean };
export function ConversationChangeSource({ projectId, disabled, onChange }: { projectId: string; disabled: boolean; onChange: (value: ConversationChangeSourceValue | null) => void }) {
  const [choices, setChoices] = useState<{ id: string; label: string }[]>([]), [ecrId, setEcrId] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [allowDiscussion, setAllowDiscussion] = useState(false), [includeSupplierNotices, setIncludeSupplierNotices] = useState(false);
  type Prepared = { ecrId: string; digest: string; depth: number; baseReady: boolean; discussionAvailable: boolean };
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  function publish(value: Prepared | null, allow: boolean) {
    onChange(value ? { ecrId: value.ecrId, digest: value.digest, depth: value.depth, ready: value.baseReady && (!allow || value.discussionAvailable), allowDiscussion: allow, includeSupplierNotices } : null);
  }
  return <div className="space-y-3 rounded-md border p-3 text-xs"><p>选择本条消息的实际工程变更，展开并核对本次资料。引用、范围及正式排程按本次版本固定；会话补充只用于理解请求。</p>
    <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={async () => { setBusy(true); setError(null); try {
      const response = await fetch(`/api/projects/${projectId}/changes`, { cache: "no-store" }); const value: unknown = await responseBody(response);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.ecrs)) throw new Error("当前无法读取本项目工程变更");
      setChoices(value.ecrs.filter(isRecord).filter(r => typeof r.id === "string").map(r => ({ id: String(r.id), label: `${String(r.code ?? "工程变更")} · ${String(r.title ?? r.reason ?? "")}` })));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }}>读取本项目工程变更</Button>
    <label className="block">本次工程变更<select aria-label="本次工程变更" className="mt-1 w-full rounded-md border bg-background p-2" disabled={disabled || busy} value={ecrId} onChange={e => { setEcrId(e.target.value); setPrepared(null); setAllowDiscussion(false); onChange(null); }}><option value="">请选择原业务记录</option>{choices.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
    <label className="flex items-start gap-2"><input type="checkbox" checked={includeSupplierNotices} disabled={disabled || busy} onChange={e => { setIncludeSupplierNotices(e.target.checked); setPrepared(null); setAllowDiscussion(false); onChange(null); }}/><span>将已关联厂商通告、人审核对及原文纳入本次资料</span></label>
    {ecrId && <fieldset disabled={disabled || busy}><ChangeAnalysisPreparation key={`${ecrId}:${includeSupplierNotices}`} projectId={projectId} ecrId={ecrId} showRuns={false} includeSupplierNotices={includeSupplierNotices} onPrepared={value => {
      const coverage = isRecord(value?.model_context) && isRecord(value.model_context.coverage) ? value.model_context.coverage : null;
      const ready = !!value && value.rollout === "live" && value.can_request === true;
      const next = value && typeof value.digest === "string" && typeof coverage?.depth === "number" ? { ecrId, digest: value.digest, depth: coverage.depth, baseReady: ready, discussionAvailable: value.discussion_available === true } : null;
      setPrepared(next); publish(next, allowDiscussion);
    }}/></fieldset>}
    {prepared && <div className="space-y-2"><label className="flex items-start gap-2"><input type="checkbox" checked={allowDiscussion} disabled={disabled || busy || (!prepared.discussionAvailable && !allowDiscussion)} onChange={e => { setAllowDiscussion(e.target.checked); publish(prepared, e.target.checked); }}/><span>允许 Agent 根据原资料发起专业讨论，完成后继续分析</span></label><p className="text-muted-foreground">此选项随本条消息保存，重复办理沿用原选择。发起判断、讨论和后续分析共用原请求预算；新候选仍需人工审阅与独立应用。</p>{!prepared.discussionAvailable && <p>讨论与接续能力尚待阶段评测，目前可按原资料准备单次分析。</p>}</div>}
    {includeSupplierNotices && <p>本条消息固定通告资料版本与具名读取范围，重试沿用原选择。专业讨论和后续分析共用原预算，须阶段评测开放；候选仍须人工审阅后独立应用。</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
