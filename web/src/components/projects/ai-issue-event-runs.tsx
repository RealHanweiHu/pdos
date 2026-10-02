"use client";

import { useEffect, useRef, useState } from "react";
import { AiIssueApplication } from "./ai-issue-application";
import { AiIssueEventHistory } from "./ai-issue-event-history";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AgentRunProgressPanel } from "@/components/ai/agent-run-progress";
import { cancelAgentRun } from "@/components/ai/ai-api";

type Reference = { reference_id: string; label: string; excerpt: string };
type Preparation = { event_row_id: number; source_digest: string; source_status: string; source_title: string; rollout: string; can_request: boolean; notice: string; references: Reference[]; existing_issue_id: string | null };
type Proposal = { disposition: "create_issue" | "reuse_issue" | "insufficient_evidence"; title: string | null; description: string | null; severity: string | null; existing_issue_id: string | null; citations: { reference_id: string; exact_quote: string }[]; open_questions: string[] };
type GenerationBinding = { status: "trial_candidate" | "evidence_only" | "not_recorded"; reason: string; created_at: string | null; policyRevision: number | null; scopeRevision: number | null };
type WriteExecution = { route: "direct" | "confirm" | "exception"; reason_label: string; application_id: string | null };
type Run = { run_id: string; request_id: string; event_row_id: number; source_digest: string; status: string; error_code: string | null; created_at: string; sources_current: boolean; requested_by_me: boolean; proposal: Proposal | null; frozen_sources: Reference[]; generation_binding: GenerationBinding; write_execution: WriteExecution | null };
type History = { items: Run[]; next_before_id: string | null; rollout: string; can_request: boolean };
type Command = { request_id: string; event_row_id: number; expected_digest: string };
const states: Record<string, string> = { queued: "等待运行", running: "正在整理", succeeded: "建议已保存", degraded: "本次未完成", failed: "运行失败", waiting_input: "等待补充资料" };
const errorLabels: Record<string, string> = { APPLICATION_RUN_LEASE_EXPIRED: "运行已中断，可沿原请求核对回执或恢复。", APPLICATION_RUN_CANCELLED: "本次运行已停止。", APPLICATION_CONTEXT_SOURCE_CHANGED: "原来源已有变化，请重新核对资料。", MODEL_UNAVAILABLE: "模型当前不可用，请稍后核对。", ISSUE_EVENT_SOURCE_CHANGED: "来源已变化，本次未保存可用建议。", ISSUE_EVENT_PROPOSAL_INVALID: "建议未通过原依据核对，未作为可用结果保存。" };
function text(value: unknown): string { if (typeof value !== "string") throw new Error("运行资料不完整，请刷新核对"); return value; }
function nullable(value: unknown): string | null { return value === null ? null : text(value); }
function positive(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) throw new Error("来源或分页位置不完整"); return value; }
function object(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("运行资料不完整，请刷新核对"); return value; }
function list(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error("运行资料清单不完整"); return value; }
function refs(value: unknown): Reference[] { return list(value).map(row => { const item = object(row); return { reference_id: text(item.reference_id), label: text(item.label), excerpt: text(item.excerpt) }; }); }
function preparation(value: unknown): Preparation { const row = object(value); return { event_row_id: positive(row.event_row_id), source_digest: text(row.source_digest), source_status: text(row.source_status), source_title: text(row.source_title), rollout: text(row.rollout), can_request: row.can_request === true, notice: text(row.notice), references: refs(row.references), existing_issue_id: nullable(row.existing_issue_id) }; }
function proposal(value: unknown): Proposal | null {
  if (value === null) return null;
  const row = object(value), disposition = text(row.disposition);
  if (!["create_issue", "reuse_issue", "insufficient_evidence"].includes(disposition)) throw new Error("建议类型不完整");
  const result: Proposal = { disposition: disposition as Proposal["disposition"], title: nullable(row.title), description: nullable(row.description), severity: nullable(row.severity), existing_issue_id: nullable(row.existing_issue_id), citations: list(row.citations).map(value => { const quote = object(value); return { reference_id: text(quote.reference_id), exact_quote: text(quote.exact_quote) }; }), open_questions: list(row.open_questions).map(text) };
  if ((disposition === "create_issue" && (!result.title || !result.description || !["low", "medium", "high", "critical"].includes(result.severity ?? "") || result.existing_issue_id !== null)) || (disposition !== "create_issue" && (result.title !== null || result.description !== null || result.severity !== null)) || ((disposition === "reuse_issue") !== (result.existing_issue_id !== null)) || (disposition === "insufficient_evidence" ? result.open_questions.length === 0 : result.citations.length === 0 || result.open_questions.length > 0)) throw new Error("建议结果与处理类型不一致，请刷新核对原回执");
  return result;
}
const bindingLabels: Record<GenerationBinding["status"], string> = { trial_candidate: "试运行候选", evidence_only: "仅保留建议证据", not_recorded: "未留存" };
function generationBinding(value: unknown): GenerationBinding {
  if (value == null) return { status: "not_recorded", reason: "此历史运行未留存生成时政策与项目授权，不补记为试运行候选。", created_at: null, policyRevision: null, scopeRevision: null };
  const row = object(value), status = text(row.status);
  if (!["trial_candidate", "evidence_only", "not_recorded"].includes(status)) throw new Error("生成时依据状态不完整，请刷新核对");
  if (status === "not_recorded") return { status, reason: text(row.reason), created_at: null, policyRevision: null, scopeRevision: null };
  return { status: status as GenerationBinding["status"], reason: text(row.reason), created_at: text(row.created_at), policyRevision: row.policy == null ? null : positive(object(row.policy).revision), scopeRevision: row.scope == null ? null : positive(object(row.scope).revision) };
}
function GenerationBasis({ binding }: { binding: GenerationBinding }) {
  return <details className="space-y-2 border-l-2 pl-3"><summary className="cursor-pointer text-primary">生成时依据 · {bindingLabels[binding.status]}</summary><p className="leading-5">{binding.reason}</p>{binding.status !== "not_recorded" && <dl className="grid gap-2 sm:grid-cols-2"><div><dt className="text-muted-foreground">当时政策版本</dt><dd>{binding.policyRevision === null ? "未登记" : `第 ${binding.policyRevision} 版`}</dd></div><div><dt className="text-muted-foreground">当时项目授权版本</dt><dd>{binding.scopeRevision === null ? "未登记" : `第 ${binding.scopeRevision} 版`}</dd></div>{binding.created_at && <div className="sm:col-span-2"><dt className="text-muted-foreground">依据留存时间</dt><dd><time dateTime={binding.created_at}>{new Date(binding.created_at).toLocaleString("zh-CN")}</time></dd></div>}</dl>}<p className="leading-5 text-muted-foreground">这是原生成时的记录；当前能否办理须另行核对，不代表已取得自动写入资格。</p></details>;
}
function writeExecution(value: unknown): WriteExecution | null {
  if (value == null) return null;
  const row = object(value);
  if (!["direct", "confirm", "exception"].includes(String(row.route))) throw new Error("自动办理回执状态不完整，请刷新核对");
  return { route: row.route as WriteExecution["route"], reason_label: text(row.reason_label), application_id: row.application_id == null ? null : text(row.application_id) };
}
function WriteExecutionNotice({ value }: { value: WriteExecution | null }) {
  if (!value) return null;
  return <p className={value.route === "direct" ? "text-muted-foreground" : "text-primary"}>{value.route === "direct" ? value.application_id ? "AI 自动办理已完成" : "自动办理结果待核对" : value.route === "confirm" ? "已转逐次确认" : "自动办理遇到例外"}：{value.reason_label}</p>;
}
function run(value: unknown): Run {
  const row = object(value);
  return { run_id: text(row.run_id), request_id: text(row.request_id), event_row_id: positive(row.event_row_id), source_digest: text(row.source_digest), status: text(row.status), error_code: nullable(row.error_code), created_at: text(row.created_at), sources_current: row.sources_current === true, requested_by_me: row.requested_by_me === true, proposal: proposal(row.proposal), frozen_sources: row.frozen_sources === undefined ? [] : refs(row.frozen_sources), generation_binding: generationBinding(row.generation_binding), write_execution: writeExecution(row.write_execution) };
}
function history(value: unknown): History { const row = object(value); return { items: list(row.items).map(run), next_before_id: nullable(row.next_before_id), rollout: text(row.rollout), can_request: row.can_request === true }; }
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, command?: Command): Promise<unknown> {
  const response = await fetch(path, { method: command ? "POST" : "GET", cache: "no-store", headers: command ? { "Content-Type": "application/json" } : undefined, body: command ? JSON.stringify(command) : undefined });
  const body: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new RequestError(isRecord(body) && typeof body.detail === "string" ? body.detail : isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "运行回执暂不可用，请沿原请求核对", response.status);
  return body;
}
function Sources({ items }: { items: Reference[] }) { return <details><summary className="cursor-pointer text-xs text-primary">查看本次固定依据 · {items.length} 项</summary><div className="mt-2 space-y-2">{items.map(item => <blockquote key={item.reference_id} className="border-l-2 pl-2 text-xs"><p className="text-muted-foreground">{item.label}</p><p className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words leading-5">{item.excerpt}</p></blockquote>)}</div></details>; }

export function AiIssueEventRuns(props: { projectId: string; eventRowId: number; initialRunId?: string; withdrawnIssueIds?: string[]; onIssueChanged?: (withdrawnIssueIds: string[]) => Promise<void> }) { return <Runs key={`${props.projectId}:${props.eventRowId}`} {...props} />; }
function Runs({ projectId, eventRowId, initialRunId, onIssueChanged, withdrawnIssueIds = [] }: { projectId: string; eventRowId: number; initialRunId?: string; withdrawnIssueIds?: string[]; onIssueChanged?: (withdrawnIssueIds: string[]) => Promise<void> }) {
  const [locallyWithdrawn, setLocallyWithdrawn] = useState<string[]>([]);
  const isWithdrawn = (id: string) => withdrawnIssueIds.includes(id) || locallyWithdrawn.includes(id);
  async function issueChanged(ids: string[]) {
    if (active.current) setLocallyWithdrawn(current => [...new Set([...current, ...ids])]);
    await onIssueChanged?.(ids);
  }
  const base = `/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-runs`;
  const [prepared, setPrepared] = useState<Preparation | null>(null), [data, setData] = useState<History | null>(null), [selected, setSelected] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false), [generating, setGenerating] = useState(false), [error, setError] = useState<string | null>(null), [pending, setPending] = useState<Command | null>(null);
  const active = useRef(true), loading = useRef(false), posting = useRef(false), selection = useRef(0);
  useEffect(() => { active.current = true; return () => { active.current = false; selection.current += 1; }; }, []);
  async function refresh() {
    if (loading.current) return;
    loading.current = true; setBusy(true); setError(null); selection.current += 1; setSelected(null);
    const results = await Promise.allSettled([request(`${base}/preparation?event_row_id=${eventRowId}`).then(preparation), request(`${base}?event_row_id=${eventRowId}`).then(history)]);
    if (active.current) {
      setPrepared(results[0].status === "fulfilled" ? results[0].value : null);
      setData(results[1].status === "fulfilled" ? results[1].value : null);
      for (const result of results) if (result.status === "rejected") setError(result.reason instanceof Error ? result.reason.message : "资料读取失败");
      setBusy(false);
    }
    loading.current = false;
    if (active.current && initialRunId && results[1].status === "fulfilled") await open(initialRunId);
  }
  async function open(id: string) {
    const current = ++selection.current; setSelected(null); setError(null);
    try { const page = history(await request(`${base}?run_id=${encodeURIComponent(id)}`)); const value = page.items.find(item => item.run_id === id); if (!value) throw new Error("指定运行回执不存在，请刷新核对"); if (active.current && current === selection.current) setSelected(value); }
    catch (failure) { if (active.current && current === selection.current) setError(failure instanceof Error ? failure.message : "原回执读取失败"); }
  }
  async function older() {
    if (!data?.next_before_id || loading.current) return;
    loading.current = true; setBusy(true); setError(null);
    try { const page = history(await request(`${base}?event_row_id=${eventRowId}&before_id=${data.next_before_id}`)); if (active.current) setData(previous => previous ? { ...page, items: [...previous.items, ...page.items.filter(row => !previous.items.some(old => old.run_id === row.run_id))] } : page); }
    catch (failure) { if (active.current) { setError(failure instanceof Error ? failure.message : "历史读取失败"); if (failure instanceof RequestError && [401, 403].includes(failure.status)) { selection.current += 1; setData(null); setPrepared(null); setSelected(null); } } }
    finally { loading.current = false; if (active.current) setBusy(false); }
  }
  async function generate(command: Command) {
    if (posting.current) return;
    posting.current = true; setPending(command); setGenerating(true); setError(null);
    try {
      const result = run(await request(base, command));
      if (!active.current) return;
      setPending(null); await refresh(); if (active.current) await open(result.run_id);
      if (active.current && result.write_execution?.route === "direct" && result.write_execution.application_id) await issueChanged([]);
    } catch (failure) {
      if (active.current) { setError(failure instanceof Error ? failure.message : "未取得明确回执，请沿原请求核对"); if (failure instanceof RequestError && failure.status >= 400 && failure.status < 500) setPending(null); }
    } finally { posting.current = false; if (active.current) setGenerating(false); }
  }
  async function stop(item: Run) {
    setBusy(true); setError(null);
    try { await cancelAgentRun(item.run_id); if (active.current) { await refresh(); if (active.current) await open(item.run_id); } }
    catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : "停止回执暂不可用，请刷新核对"); }
    finally { if (active.current) setBusy(false); }
  }
  const canGenerate = prepared?.can_request === true && prepared.rollout === "live" && prepared.source_status === "current";
  return <details open={initialRunId ? true : undefined} className="min-w-0 border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !prepared && !data && !busy) void refresh(); }}>
    <summary className="cursor-pointer text-xs font-medium text-primary">AI 建议与运行记录</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="leading-5 text-muted-foreground">根据本条异常的原依据整理问题建议。建议与实际建单分别记录，可回查每次运行的原文和结果。</p>
      <Button size="sm" variant="outline" disabled={busy || (!!pending && !generating)} onClick={() => void refresh()}>核对资料并刷新记录</Button>
      {busy && <p role="status">正在读取资料与运行记录…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      {prepared && <div className="space-y-2 rounded-lg bg-muted/20 p-2 sm:p-3"><p className="font-medium">{prepared.source_title}</p><p className="leading-5 text-muted-foreground">{prepared.notice}</p>{prepared.rollout !== "live" && <p className="text-primary">此能力尚未开放生成，当前可核对资料和回查原运行。</p>}{prepared.source_status !== "current" && <p className="text-primary">来源已有变化或暂不可用，请核对来源记录。</p>}<Sources items={prepared.references} />{prepared.existing_issue_id && <a className="inline-block text-primary underline" href={`/projects?project=${encodeURIComponent(projectId)}&tab=work-items&entity_id=${encodeURIComponent(prepared.existing_issue_id)}`}>{isWithdrawn(prepared.existing_issue_id) ? "查看已撤回问题历史（不可继续办理）" : "查看已有问题"}</a>}{canGenerate && <div><Button size="sm" disabled={busy || generating || !!pending} onClick={() => void generate({ request_id: crypto.randomUUID(), event_row_id: eventRowId, expected_digest: prepared.source_digest })}>生成问题建议</Button></div>}</div>}
      {generating && <p role="status">正在核对本次请求，可在原运行中查看预算和进度。</p>}{pending && !generating && <div className="space-y-2"><p className="text-primary">本次请求尚未取得明确回执，继续核对会复用原请求。</p><Button size="sm" onClick={() => void generate(pending)}>沿原请求核对结果</Button></div>}
      {data?.items.length === 0 && <p className="text-muted-foreground">本条异常暂无运行记录。</p>}
      {data?.items.map(item => <div key={item.run_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-2"><div className="min-w-0 space-y-1"><p>{new Date(item.created_at).toLocaleString("zh-CN")} · {states[item.status] ?? "运行状态待核对"}</p><p className="text-muted-foreground">生成时：{bindingLabels[item.generation_binding.status]}</p><WriteExecutionNotice value={item.write_execution} /></div><Button size="sm" variant="outline" className="h-auto min-h-8 max-w-full whitespace-normal py-1.5 text-left" disabled={busy} onClick={() => void open(item.run_id)}>查看本次建议与回执</Button></div>)}
      {data?.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void older()}>更早的运行记录</Button>}
      <AiIssueEventHistory projectId={projectId} eventRowId={eventRowId} onSelectRun={id => { void open(id); }} disabled={busy} />
      {selected && <section className="space-y-3 rounded-lg border p-2 sm:p-3"><p className="font-medium">本次运行 · {states[selected.status] ?? "状态待核对"}</p>{!selected.sources_current && <p className="text-primary">当前来源或权限已变化，以下保留本次运行的原依据。</p>}{selected.error_code && <p className="text-primary">{errorLabels[selected.error_code] ?? "本次生成未完成，请核对原资料与运行详情。"}</p>}<AgentRunProgressPanel key={selected.run_id} projectId={projectId} runId={selected.run_id} />
        <WriteExecutionNotice value={selected.write_execution} /><GenerationBasis binding={selected.generation_binding} />
        {selected.proposal && <div className="space-y-2">{selected.proposal.disposition === "create_issue" ? <><p className="font-medium">原建议：新建问题</p><p className="text-sm">{selected.proposal.title}</p><p className="whitespace-pre-wrap break-words leading-5">{selected.proposal.description}</p><p>建议严重度：{({ low: "低", medium: "中", high: "高", critical: "严重" } as Record<string, string>)[selected.proposal.severity ?? ""]}</p></> : selected.proposal.disposition === "reuse_issue" ? <><p className="font-medium">建议沿用已有问题</p><a className="inline-block text-primary underline" href={`/projects?project=${encodeURIComponent(projectId)}&tab=work-items&entity_id=${encodeURIComponent(selected.proposal.existing_issue_id ?? "")}`}>查看建议复用的问题</a></> : <p className="font-medium">资料不足，尚未形成建单建议</p>}{selected.proposal.open_questions.map((question, index) => <p key={index} className="text-primary">待补：{question}</p>)}{selected.proposal.citations.map((citation, index) => <blockquote key={index} className="border-l-2 pl-2"><p className="text-muted-foreground">{selected.frozen_sources.find(ref => ref.reference_id === citation.reference_id)?.label ?? "本次原文引用"}</p><p className="mt-1 whitespace-pre-wrap break-words leading-5">{citation.exact_quote}</p></blockquote>)}</div>}
        {selected.status === "succeeded" && selected.proposal && <AiIssueApplication projectId={projectId} runId={selected.run_id} onIssueChanged={issueChanged} />}
        <Sources items={selected.frozen_sources} />
        {selected.requested_by_me && <div className="flex flex-wrap gap-2">{canGenerate && selected.sources_current && (selected.status === "running" || (selected.status === "degraded" && selected.error_code === "APPLICATION_RUN_LEASE_EXPIRED")) && <Button size="sm" variant="outline" disabled={busy || generating || !!pending} onClick={() => void generate({ request_id: selected.request_id, event_row_id: selected.event_row_id, expected_digest: selected.source_digest })}>沿原请求核对或恢复</Button>}{selected.status === "running" && <Button size="sm" variant="outline" disabled={busy || (!!pending && !generating)} onClick={() => void stop(selected)}>停止本次运行</Button>}</div>}
      </section>}
    </div>
  </details>;
}
