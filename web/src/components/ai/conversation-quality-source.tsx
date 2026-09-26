"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { OperationEvidence, evidenceBody, qualityRequest, type Evidence } from "@/components/quality/quality-operation-evidence";

export type ConversationQualitySourceValue = { ncrId: string; digest: string; selections: ReturnType<typeof evidenceBody>; ready: boolean };

export function ConversationQualitySource({ projectId, disabled, onChange }: { projectId: string; disabled: boolean; onChange: (value: ConversationQualitySourceValue | null) => void }) {
  const [choices, setChoices] = useState<Row[]>([]), [next, setNext] = useState<number | null>(null), [ncrId, setNcrId] = useState("");
  const [evidence, setEvidence] = useState<Evidence[]>([]), [snapshot, setSnapshot] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function act(fn: () => Promise<void>) { setBusy(true); setError(""); try { await fn(); } catch(e) { setError(e instanceof Error ? e.message : "读取品质资料失败"); } finally { setBusy(false); } }
  async function load(more = false) {
    const res = await fetch(`/api/projects/${projectId}/quality/issue-links/options?kind=ncr&offset=${more ? next ?? 0 : 0}`, { cache: "no-store" });
    const value: unknown = await res.json();
    if (!res.ok) throw new Error(text(obj(obj(value).detail).message) || "当前无法读取本项目 NCR");
    const result = obj(value);
    setChoices(old => more ? [...old, ...rows(result.items)] : rows(result.items));
    setNext(typeof result.next_offset === "number" ? result.next_offset : null);
  }
  return <fieldset disabled={disabled || busy} className="space-y-3 rounded-md border p-3 text-sm">
    <legend className="px-1">本条消息使用的原质量资料</legend>
    <p className="text-xs text-muted-foreground">选择实际 NCR 并核对资料。会话记录仅用于说明请求，调查结论和根因仍以实际证据及人工批准为准。</p>
    <Button type="button" size="sm" variant="outline" onClick={() => void act(() => load())}>读取本项目 NCR</Button>
    <label className="block">本次 NCR<select className={field} value={ncrId} onChange={e => { setNcrId(e.target.value); setEvidence([]); setSnapshot(null); onChange(null); }}><option value="">请选择原质量记录</option>{choices.map(choice => { const value = obj(choice.value); return <option key={text(choice.id)} value={text(choice.id)}>{text(value.code)} · {text(value.nonconformity)} · {text(value.status)}</option>; })}</select></label>
    {next !== null && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => load(true))}>更多 NCR</Button>}
    {ncrId && <>
      <a className="text-xs text-primary underline" href={`/projects?project=${projectId}&tab=quality&ncr=${ncrId}`}>核对原 NCR 与当前办理进展</a>
      <OperationEvidence key={ncrId} projectId={projectId} ncrId={ncrId} value={evidence} disabled={disabled || busy} onChange={value => { setEvidence(value); setSnapshot(null); onChange(null); }}/>
      <Button type="button" size="sm" variant="outline" onClick={() => void act(async () => { setSnapshot(null); onChange(null); const result = await qualityRequest(projectId, ncrId, "/preparation-context", { selections: evidenceBody(evidence) }); setSnapshot(result); onChange({ ncrId, digest: text(result.digest), selections: evidenceBody(evidence), ready: result.rollout === "live" && result.can_request === true }); })}>读取并核对本次资料</Button>
    </>}
    {snapshot && <div className="space-y-2 text-xs"><p>{snapshot.phase === "investigation" ? "当前准备根因调查任务" : "当前准备纠正与预防措施"} · 已读取 {rows(snapshot.references).length} 项原资料</p>
      {rows(snapshot.references).map(ref => <details key={text(ref.reference_id)}><summary className="cursor-pointer">{text(ref.label)}</summary><pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(ref.fields, null, 2)}</pre>{Array.isArray(ref.omitted_fields) && ref.omitted_fields.length > 0 && <p>未纳入字段：{ref.omitted_fields.map(String).join("、")}</p>}</details>)}
      {Array.isArray(snapshot.omitted_references) && snapshot.omitted_references.length > 0 && <p>另有 {snapshot.omitted_references.length} 项超出本次读取范围，请缩小选定资料。</p>}
      <p>{snapshot.rollout === "live" && snapshot.can_request === true ? "本次资料已绑定，可填写请求并保存；生成时会再次核对是否变化。" : "资料已读取；此项生成仍受阶段评测及当前办理权限限制。"}</p>
    </div>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </fieldset>;
}
