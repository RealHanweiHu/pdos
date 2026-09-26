"use client";

import { useRef, useState } from "react";
import { MeetingPlanningReview } from "./meeting-planning-review";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import { cancelAgentRun } from "@/components/ai/ai-api";

type Row = Record<string, unknown>;
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "" : String(value);
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
const labels: Record<string, string> = { running: "正在起草", succeeded: "本次起草已返回", degraded: "本次未完整完成", failed: "本次运行已停止或失败" };

export function MeetingPlanningRuns({ projectId, briefId, sourceDigest, canGenerate, onShowBrief }: { projectId: string; briefId: string; sourceDigest: string; canGenerate: boolean; onShowBrief: (id: string) => void }) {
  const [data, setData] = useState<Row | null>(null), [generating, setGenerating] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState<string | null>(null);
  const [awaiting, setAwaiting] = useState(false);
  const pending = useRef<{ brief: string; id: string; digest: string } | null>(null);
  const base = `/api/projects/${projectId}/meetings/planning`;
  async function request(id: string, body?: object, before?: string): Promise<Row> {
    const response = await fetch(`${base}/${id}/runs${before ? `?before=${encodeURIComponent(before)}` : ""}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "运行回执暂不可读，请读取原运行后继续");
    return value;
  }
  async function load(before?: string) { setLoading(true); setError(null); try { const value = await request(briefId, undefined, before); setData(prior => before && prior ? { ...value, items: [...rows(prior.items), ...rows(value.items)] } : value); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setLoading(false); } }
  async function generate(run?: Row) {
    setGenerating(true); setAwaiting(true); setError(null);
    if (run) pending.current = { brief: text(run.brief_id), id: text(run.request_id), digest: text(run.source_digest) };
    else if (!pending.current) pending.current = { brief: briefId, id: crypto.randomUUID(), digest: sourceDigest };
    try {
      const original = pending.current!;
      const value = await request(original.brief, { request_id: original.id, expected_source_digest: original.digest });
      if (value.request_id !== original.id || typeof value.id !== "string" || typeof value.status !== "string") throw new Error("原起草请求回执尚未完整返回，请核对同一请求");
      pending.current = null; setAwaiting(false); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "起草未完成"); } finally { setGenerating(false); }
  }
  async function stop(id: string) { setError(null); try { await cancelAgentRun(id); await load(); } catch (e) { setError(e instanceof Error ? e.message : "停止未完成，请刷新运行回执"); } }
  return <details className="space-y-2 rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !loading) void load(); }}>
    <summary className="cursor-pointer font-medium">AI 起草运行与原文依据</summary>
    <p className="mt-2 text-xs text-muted-foreground">{text(data?.generation_message) || "读取能力状态后可查看运行。"} 同一原要求的再次运行与资料修订沿用累计预算及截止时间。起草不会创建会议、预约或发送通知。</p>
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void load()}>刷新运行回执</Button><Button type="button" size="sm" disabled={generating || !canGenerate || data?.generation_available !== true} onClick={() => void generate()}>{awaiting ? "核对原起草请求" : "请求 AI 起草当前版本"}</Button></div>
    {generating && <p role="status" className="text-xs">正在请求起草；可以刷新原运行、查看累计用量或停止运行。</p>}
    {rows(data?.items).map(run => {
      const finding = isRecord(run.finding) ? run.finding : null;
      const payload = finding && isRecord(finding.proposed_payload) ? finding.proposed_payload : isRecord(run.reading) ? run.reading : {};
      const assessment = isRecord(payload.assessment) ? payload.assessment : null;
      const plan = assessment && isRecord(assessment.plan) ? assessment.plan : null;
      const people = isRecord(run.source_people) ? run.source_people : {};
      return <article key={text(run.id)} className="space-y-2 border-t pt-2 text-xs">
        <p>{labels[text(run.status)] ?? text(run.status)} · {text(run.created_at)}{run.brief_id !== briefId ? " · 同一原要求的其他版本" : ""}</p>
        {run.error_code != null && <p className="text-destructive">停止原因：{text(run.error_code)}</p>}
        {run.source_current !== true && <p className="text-destructive">原资料版本、人员或权限已变化。历史建议保留，不能继续按旧资料应用。</p>}
        <AgentRunProgressPanel projectId={projectId} runId={text(run.id)}/>
        <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="ghost" disabled={generating} onClick={() => onShowBrief(text(run.brief_id))}>回查本次原起草资料</Button>{["running", "degraded"].includes(text(run.status)) && <Button type="button" size="sm" variant="outline" disabled={generating || !canGenerate || run.source_current !== true || data?.generation_available !== true} onClick={() => void generate(run)}>沿原请求核对或恢复</Button>}{(run.status === "running" || run.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button type="button" size="sm" variant="outline" onClick={() => void stop(text(run.id))}>停止这条要求的运行</Button>}</div>
        {assessment?.disposition === "insufficient_evidence" && <p>所选资料不足，未形成会议草案。</p>}
        {plan && <div className="space-y-2 rounded-md border p-3"><h5 className="font-medium">{text(plan.title)}</h5><p>模型建议目的：{text(plan.purpose)}</p><p>此为原 AI 建议，可在下方核对人工稿和实际创建回执。</p>{rows(plan.participants).map(p => <p key={text(p.user_id)}>{text(people[text(p.user_id)]) || text(p.user_id)} · {p.participation === "required" ? "建议必需参会" : "建议可选参会"} · {text(p.reason)}</p>)}{rows(plan.agenda).map((a, i) => <details key={i} className="rounded-md border p-2"><summary>议题 {i + 1}：{text(a.title)}</summary><p className="whitespace-pre-wrap">建议讨论：{text(a.detail)}</p><p className="whitespace-pre-wrap">期望产出：{text(a.expected_output)}</p><p>建议议题负责人：{a.suggested_owner_id ? text(people[text(a.suggested_owner_id)]) || text(a.suggested_owner_id) : "待核对"}</p>{rows(a.citations).map((citation, n) => <div className="my-2" key={n}><p>原文 {text(citation.reference_id)} · 字符 {Number(citation.start) + 1}–{text(citation.end)}</p><blockquote className="whitespace-pre-wrap border-l-2 pl-2">{text(citation.exact_quote)}</blockquote></div>)}</details>)}</div>}
        {finding && typeof finding.id === "string" && <MeetingPlanningReview projectId={projectId} findingId={finding.id}/>}
        {strings(assessment?.open_questions).map((question, i) => <p key={i}>待确认：{question}</p>)}
      </article>;
    })}
    {typeof data?.next_before === "string" && <Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void load(text(data.next_before))}>读取更早运行</Button>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </details>;
}
