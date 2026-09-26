"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AgentRunProgressPanel } from "./agent-run-progress";
import { ConversationIntakeReview } from "./conversation-intake-review";
import { cancelAgentRun } from "./ai-api";
type Row = Record<string, unknown>;
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "" : String(value);
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
const labels: Record<string, string> = { running: "正在整理", succeeded: "本次整理已返回", degraded: "本次未完整完成", failed: "本次运行已停止或失败" };
export function ConversationIntakeRuns({ conversationId, brief, archived }: { conversationId: string; brief: Row; archived: boolean }) {
  const [data, setData] = useState<Row | null>(null), [generating, setGenerating] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState<string | null>(null);
  const pending = useRef<{ brief: string; id: string } | null>(null);
  const base = `/api/conversations/${conversationId}/intake-ai-sources`;
  async function request(id: string, body?: object): Promise<Row> {
    const response = await fetch(`${base}/${id}/runs`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "运行回执暂不可读，请读取原运行后继续");
    return value;
  }
  async function load() { setLoading(true); setError(null); try { setData(await request(text(brief.id))); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setLoading(false); } }
  async function generate(run?: Row) {
    setGenerating(true); setError(null);
    const id = run ? text(run.brief_id) : text(brief.id);
    if (run) pending.current = { brief: id, id: text(run.request_id) };
    else if (pending.current?.brief !== id) pending.current = { brief: id, id: crypto.randomUUID() };
    try {
      await request(id, { request_id: pending.current!.id, expected_source_digest: run?.source_digest ?? brief.source_digest });
      pending.current = null; await load();
    } catch (e) { setError(e instanceof Error ? e.message : "整理未完成"); } finally { setGenerating(false); }
  }
  async function stop(id: string) { setError(null); try { await cancelAgentRun(id); await load(); } catch (e) { setError(e instanceof Error ? e.message : "停止未完成，请刷新运行回执"); } }
  return <details className="space-y-2 rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !loading) void load(); }}>
    <summary className="cursor-pointer font-medium">AI整理运行与原文建议</summary>
    <p className="mt-2 text-xs text-muted-foreground">{text(data?.generation_message) || "读取能力状态后可查看运行。"} 修订与再次生成沿用这条原要求的累计预算和截止时间。停止后保留已保存来源及历史结果。</p>
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={loading} onClick={() => void load()}>刷新运行回执</Button><Button type="button" size="sm" disabled={generating || archived || data?.generation_available !== true || brief.source_current !== true} onClick={() => void generate()}>请求AI整理当前版本</Button></div>
    {generating && <p role="status" className="text-xs">正在请求整理；可刷新回执查看已创建的运行和累计用量，或停止当前运行。</p>}
    {rows(data?.items).map(run => {
      const finding = isRecord(run.finding) ? run.finding : null, payload = finding && isRecord(finding.proposed_payload) ? finding.proposed_payload : isRecord(run.reading) ? run.reading : {};
      return <article key={text(run.id)} className="space-y-2 border-t pt-2 text-xs">
        <p>{labels[text(run.status)] ?? text(run.status)} · {text(run.created_at)}{run.brief_id !== brief.id ? " · 同一原要求的其他版本" : ""}</p>
        {run.error_code != null && <p className="text-destructive">停止原因：{text(run.error_code)}</p>}
        {run.source_current !== true && <p className="text-destructive">本次运行来源、权限或固定合同已不再适用，历史结果仅供回查。</p>}
        <AgentRunProgressPanel projectId={text(run.project_id)} runId={text(run.id)}/>
        <div className="flex flex-wrap gap-2">{["running", "degraded"].includes(text(run.status)) && <Button type="button" size="sm" variant="outline" disabled={generating || archived || run.source_current !== true || data?.generation_available !== true} onClick={() => void generate(run)}>沿原请求核对或恢复</Button>}{(run.status === "running" || run.error_code === "APPLICATION_RUN_LEASE_EXPIRED") && <Button type="button" size="sm" variant="outline" onClick={() => void stop(text(run.id))}>停止这条要求的运行</Button>}</div>
        {finding && <ConversationIntakeReview conversationId={conversationId} findingId={text(finding.id)} archived={archived} onReviewed={() => void load()}/> }
        {payload.disposition === "insufficient_evidence" && <p>所选资料不足，未生成业务对象建议。</p>}
        {rows(payload.proposals).map(item => <details key={Number(item.number)} className="rounded-md border p-2"><summary className="cursor-pointer">建议 {text(item.number)} · {text(item.kind)} · {text(item.model_summary)}</summary><p className="text-muted-foreground">以上为模型归纳；下方为所引原文字段。</p>{isRecord(item.anchor) && <p className="whitespace-pre-wrap">主要依据 · {text(item.anchor.locator)}：{text(item.anchor.value)}</p>}{isRecord(item.original) && Object.entries(item.original).map(([key, value]) => isRecord(value) && <div key={key} className="my-2"><p>{key} · {text(value.locator)} · 字符 {Number(value.start)+1}–{text(value.end)}</p><pre className="max-h-40 overflow-auto whitespace-pre-wrap bg-muted p-2">{text(value.value)}</pre><a className="text-primary underline" href={`/ask?project=${run.project_id}&conversation=${conversationId}&attachment=${value.attachment_id}&fragment=${value.ordinal}`}>核对实际原文</a></div>)}{strings(item.missing_information).map((gap, i) => <p key={i}>待补：{gap}</p>)}</details>)}
        {rows(payload.possible_duplicates).map((item, i) => <p key={i}>建议 {text(item.first)} 与 {text(item.second)} 可能重复，待人工核对：{text(item.explanation)}</p>)}
        {strings(payload.open_questions).map((question, i) => <p key={i}>待确认：{question}</p>)}
      </article>;
    })}
    {data?.truncated === true && <p className="text-xs text-muted-foreground">显示原要求最近30次运行，更早回执保留在运行记录中。</p>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </details>;
}
