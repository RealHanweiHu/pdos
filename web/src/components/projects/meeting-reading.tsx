"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

function text(value: unknown): string { if (typeof value !== "string") throw new Error("纪要阅读记录不完整"); return value; }
function id(value: unknown): string { const result = text(value); if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("阅读来源标识不完整"); return result; }
function list(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error("阅读清单不完整"); return value; }
function parse(value: unknown) {
  if (!isRecord(value)) throw new Error("阅读运行资料不完整");
  return { businessRollout: text(value.business_rollout), businessAvailable: value.business_available === true, decisionsRollout: text(value.decisions_rollout), decisionsAvailable: value.decisions_available === true, actionsRollout: text(value.actions_rollout), actionsAvailable: value.actions_available === true, rollout: text(value.rollout), minutesRollout: text(value.minutes_rollout), minutesVersion: value.minutes_version === null ? null : Number(value.minutes_version), items: list(value.items).map(row => {
    if (!isRecord(row) || typeof row.current !== "boolean") throw new Error("阅读结果不完整");
    const result = isRecord(row.result) ? { disposition: text(row.result.disposition), questions: list(row.result.open_questions).map(text),
      claims: list(row.result.claims).map(claim => {
        if (!isRecord(claim)) throw new Error("归纳内容不完整");
        return { text: text(claim.text), quotes: list(claim.citations).map(quote => {
          if (!isRecord(quote)) throw new Error("原句引用不完整");
          return { segmentId: id(quote.segment_id), text: text(quote.exact_quote) };
        }) };
      }) } : null;
    return { id: id(row.run_id), status: text(row.status), current: row.current, time: text(row.created_at), error: row.error_code === null ? null : text(row.error_code), result, business: row.business === true, decisions: row.decisions === true, actions: row.actions === true, findingIds: list(row.finding_ids).map(id), proposal: row.proposal === true, findingId: row.finding_id === null ? null : id(row.finding_id) };
  }) };
}
type Data = ReturnType<typeof parse>;
const states: Record<string, string> = { running: "正在阅读", succeeded: "阅读已完成", degraded: "本次阅读不可用", failed: "阅读失败", queued: "等待运行" };
const errors: Record<string, string> = {
  MEETING_READING_CITATION_INVALID: "生成内容未能通过原句核对，未保存该结果。",
  MEETING_READING_SOURCE_CHANGED: "生成期间来源或说话人校正已变化，请刷新后按新版重试。",
  APPLICATION_CONTEXT_SOURCE_CHANGED: "来源已经变化，请先刷新原文。",
  MEETING_READING_TRACE_MISSING: "本次缺少完整运行记录，未保存生成内容。",
  MEETING_READING_EXECUTION_FAILED: "本次生成未完成，可查看运行状态后重试。",
  MEETING_BUSINESS_PROPOSAL_INVALID: "业务候选无法通过来源核对或当前质量控制，请核对原文后重新整理。",
  MEETING_DECISION_PROPOSAL_INVALID: "决策候选无法通过来源核对，请刷新后重新整理。",
  MEETING_ACTION_PROPOSAL_INVALID: "行动候选无法通过原句或来源核对，请刷新后重新整理。",
  MEETING_MINUTES_PROPOSAL_INVALID: "未通过纪要候选校验，请核对原文、引用和当前纪要版本后重试。",
  APPLICATION_RUN_LEASE_EXPIRED: "执行已中断；如有完整结果回执，可继续本次请求恢复。",
};
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "纪要阅读暂不可用，请刷新核对运行状态");
  return value;
}
export function MeetingReadingPanel({ projectId, meetingId, transcriptId, sourceDigest, canGenerate, dirty }: {
  projectId: string; meetingId: string; transcriptId: string; sourceDigest: string; canGenerate: boolean; dirty: boolean;
}) {
  const [data, setData] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const retry = useRef<{ source: string; requestId: string } | null>(null);
  const path = `/api/projects/${projectId}/meetings/${meetingId}/transcripts/${transcriptId}/reading`;
  async function load() { setData(parse(await request(path))); }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "阅读未完成"); } finally { setBusy(false); }
  }
  async function generate(proposal = false, actions = false, decisions = false, business = false) {
    const binding = JSON.stringify([sourceDigest, proposal, actions, decisions, business, proposal ? data?.minutesVersion : null]);
    if (retry.current?.source !== binding) retry.current = { source: binding, requestId: crypto.randomUUID() };
    const value = await request(path, { request_id: retry.current.requestId, expected_digest: sourceDigest, propose_minutes: proposal, propose_actions: actions, propose_decisions: decisions, propose_business: business, expected_minutes_version: proposal ? data?.minutesVersion : null });
    if (!isRecord(value)) throw new Error("本次阅读回执不完整，请刷新查看运行状态");
    setNotice(business ? (Array.isArray(value.finding_ids) && value.finding_ids.length ? `已整理${value.finding_ids.length}项业务待审稿，请逐项核对类别与办理资料。` : value.status === "succeeded" ? "现有原文未形成有据的问题、风险或变更建议。" : "业务事项整理尚未完成，请查看运行记录。") : decisions ? (Array.isArray(value.finding_ids) && value.finding_ids.length ? `已整理${value.finding_ids.length}项决策待审稿，请补齐依据并指定批准人。` : value.status === "succeeded" ? "现有原文未形成有据决策建议。" : "决策整理尚未完成，请查看运行记录。") : actions ? (Array.isArray(value.finding_ids) && value.finding_ids.length ? `已整理${value.finding_ids.length}项行动待审稿，请逐项核对并独立应用。` : value.status === "succeeded" ? "现有原文未形成有据行动建议。" : "行动整理尚未完成，请查看运行记录。") : proposal && typeof value.finding_id === "string" ? "纪要待审稿已进入审阅队列，接受后仍须独立应用。" : value.status === "succeeded" ? (proposal ? "未形成纪要候选，请核对转写是否提供足够依据。" : "已保存可核对的阅读结果；正式纪要与业务办理仍需各自确认。") : value.status === "running" ? "本次请求仍在运行，请刷新查看进度。" : "本次阅读未完成，请查看下方原因。");
    await load();
  }
  return <details className="rounded-lg border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">AI纪要阅读与原句核对</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">根据保存的转写和说话人校正生成带引用的归纳，辅助核对会议讨论。正式纪要、决定与行动仍通过各自确认和应用流程办理。</p>
      {data && data.rollout !== "live" && <p className="text-xs">本能力尚在阶段验证中，暂未开放生成；转写原文与人工核对可继续使用。</p>}
      {dirty && <p className="text-xs">请先保存说话人校正，再生成新版阅读结果。</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新阅读记录</Button>{data?.rollout === "live" && canGenerate && <><Button size="sm" disabled={busy || dirty} onClick={() => void act(() => generate())}>生成或继续本次阅读</Button>{data.minutesRollout === "live" && data.minutesVersion !== null && <Button size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(() => generate(true))}>生成纪要待审稿</Button>}{data.actionsRollout === "live" && data.actionsAvailable && <Button size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(() => generate(false, true))}>整理行动待审稿</Button>}{data.decisionsRollout === "live" && data.decisionsAvailable && <Button size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(() => generate(false, false, true))}>整理决策待审稿</Button>}{data.businessRollout === "live" && data.businessAvailable && <Button size="sm" variant="outline" disabled={busy || dirty} onClick={() => void act(() => generate(false, false, false, true))}>整理问题、风险和变更</Button>}</>}</div>
      {data && data.businessRollout !== "live" && <p className="text-xs text-muted-foreground">问题、风险和变更候选尚待阶段验证。</p>}
      {data && data.decisionsRollout !== "live" && <p className="text-xs text-muted-foreground">决策待审稿尚待阶段验证，人工决策办理可继续使用。</p>}
      {data && data.actionsRollout !== "live" && <p className="text-xs text-muted-foreground">行动待审稿尚待阶段验证，人工会后办理可继续使用。</p>}
      {data?.minutesRollout !== "live" && data && <p className="text-xs text-muted-foreground">正式纪要候选尚待阶段验证；开放后沿独立审阅与应用办理。</p>}
      {busy && <p role="status" className="text-xs">正在读取或生成…</p>}{notice && <p role="status" className="text-xs">{notice}</p>}{error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {data?.items.length === 0 && <p className="text-xs text-muted-foreground">尚无阅读记录。</p>}
      {data?.items.map(entry => <article key={entry.id} className="space-y-3 rounded-md border p-3">
        <p className="text-xs font-medium">{states[entry.status] ?? entry.status} · {new Date(entry.time).toLocaleString("zh-CN")}</p>
        {!entry.current && <p className="text-xs text-destructive">来源已变化或不可用于生成，此记录保留为历史参考。</p>}
        {entry.error && <p className="text-xs">{errors[entry.error] ?? "当前模型、预算或授权条件不满足，请核对运行配置。"}</p>}
        {entry.findingIds.map((findingId, index) => <p key={findingId}><a className="text-sm text-primary underline" href={`/ai-review?finding=${findingId}`}>打开{entry.business ? "业务" : entry.decisions ? "决策" : "行动"}待审稿 {index + 1} 与办理回执</a></p>)}
        {entry.findingId && <a className="text-sm text-primary underline" href={`/ai-review?finding=${entry.findingId}`}>打开纪要待审稿与办理回执</a>}
        {entry.proposal && entry.status === "succeeded" && !entry.findingId && data.minutesRollout === "live" && <p className="text-xs">未形成纪要候选，需继续补充会议依据。</p>}
        {entry.result?.disposition === "insufficient_evidence" && <p className="text-sm">现有转写不足以形成有据归纳。</p>}
        {entry.result?.claims.map((claim, index) => <div key={index} className="space-y-2"><p className="whitespace-pre-wrap text-sm">{claim.text}</p>{claim.quotes.map((quote, quoteIndex) => <blockquote key={quoteIndex} className="border-l-2 pl-3 text-xs text-muted-foreground"><p className="whitespace-pre-wrap">{quote.text}</p><a className="text-primary underline" href={`#transcript-segment-${quote.segmentId}`}>核对完整原句片段</a></blockquote>)}</div>)}
        {!!entry.result?.questions.length && <div className="space-y-1"><h4 className="text-xs font-medium">仍需澄清</h4><ul className="list-disc space-y-1 pl-4 text-xs">{entry.result.questions.map((question, index) => <li key={index}>{question}</li>)}</ul></div>}
      </article>)}
      {!!data?.items.length && <p className="text-xs text-muted-foreground">显示最近20次运行。</p>}
    </div>
  </details>;
}
