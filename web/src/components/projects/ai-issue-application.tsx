"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AiIssueSampleReview } from "./ai-issue-sample-review";

type AutomaticStop = { generated: number; withdrawn: number; maximum_retraction_basis_points: number; recovery_conditions: string };
type Application = { automatic_stop: AutomaticStop | null; id: string; issue_id: string; disposition: "created" | "reused"; created_at: string; writer_name: string; confirmed_by_name: string | null; capture_mode: "trial" | "direct"; requested_by_name: string | null; sampled: boolean; write_reason: string | null; run_id: string; result_id: string; requested_by_user_id: string; output_event_row_id: number; withdrawn_at: string | null; can_withdraw: boolean; withdrawal_notice: string; withdrawal_receipt: WithdrawalReceipt | null };
type Data = { result_id: string; source_digest: string; can_apply: boolean; notice: string; application: Application | null; sources_current: boolean; review: Review | null; review_receipt: Review["items"][number] | null };
type WithdrawalReceipt = { id: string; created_at: string; kind: "single" | "run"; actor_name: string; items: { application_id: string; issue_id: string; status: "withdrawn" | "skipped"; reason_code: string; reason: string }[] };
type WithdrawalCommand = { kind: "single" | "run"; run_id: string; body: { request_id: string; application_id?: string; reason: string } };
type Review = { version: number; state: "unreviewed" | "declined" | "reopened"; can_change: boolean; notice: string; items: { id: string; version: number; action: "decline" | "reopen"; reason: string; actor_name: string; created_at: string }[]; next_before_version: number | null };
type ReviewCommand = { request_id: string; result_id: string; expected_digest: string; expected_version: number; action: "decline" | "reopen"; reason: string };
type Command = { request_id: string; result_id: string; expected_digest: string };
function text(value: unknown): string { if (typeof value !== "string" || !value.trim()) throw new Error("办理回执不完整，请沿原请求核对"); return value; }
function identity(value: unknown): string { const id = text(value); if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) throw new Error("办理回执的原运行或结果标识不完整"); return id; }
function parseWithdrawal(value: unknown): WithdrawalReceipt {
  if (!isRecord(value) || !["single", "run"].includes(String(value.kind)) || !Array.isArray(value.items)) throw new Error("撤回回执不完整，请沿原请求核对");
  return { id: text(value.id), created_at: text(value.created_at), kind: value.kind as WithdrawalReceipt["kind"], actor_name: text(value.actor_name), items: value.items.map(row => {
    if (!isRecord(row) || !["withdrawn", "skipped"].includes(String(row.status))) throw new Error("撤回明细不完整，请沿原请求核对");
    return { application_id: text(row.application_id), issue_id: text(row.issue_id), status: row.status as "withdrawn" | "skipped", reason_code: text(row.reason_code), reason: text(row.reason) };
  }) };
}
function version(value: unknown, minimum = 0): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) throw new Error("处置历史版本不完整，请刷新核对"); return value; }
function parseReviewItem(value: unknown): Review["items"][number] {
  if (!isRecord(value) || !["decline", "reopen"].includes(String(value.action))) throw new Error("建议处置回执不完整，请沿原请求核对");
  return { id: text(value.id), version: version(value.version, 1), action: value.action as "decline" | "reopen", reason: text(value.reason), actor_name: text(value.actor_name), created_at: text(value.created_at) };
}
function parseReview(value: unknown): Review {
  if (!isRecord(value) || !["unreviewed", "declined", "reopened"].includes(String(value.state)) || typeof value.can_change !== "boolean" || !Array.isArray(value.items)) throw new Error("建议处置资料不完整，请刷新核对");
  return { version: version(value.version), state: value.state as Review["state"], can_change: value.can_change, notice: text(value.notice), next_before_version: value.next_before_version === null ? null : version(value.next_before_version, 1), items: value.items.map(parseReviewItem) };
}
function parse(value: unknown): Data {
  if (!isRecord(value) || typeof value.can_apply !== "boolean" || typeof value.sources_current !== "boolean") throw new Error("办理条件不完整，请刷新核对");
  let application: Application | null = null;
  if (value.application !== null) {
    const row = value.application;
    if (!isRecord(row) || !["created", "reused"].includes(String(row.disposition)) || typeof row.output_event_row_id !== "number" || !Number.isSafeInteger(row.output_event_row_id) || row.output_event_row_id < 1) throw new Error("实际办理回执不完整，请沿原请求核对");
    if (row.can_withdraw !== undefined && typeof row.can_withdraw !== "boolean") throw new Error("撤回条件不完整，请刷新核对");
    const mode = row.capture_mode ?? "trial";
    if (mode !== "trial" && mode !== "direct") throw new Error("办理方式不完整，请刷新核对");
    const write = isRecord(row.receipt) && isRecord(row.receipt.write_receipt) ? row.receipt.write_receipt : null;
    if (mode === "direct" && (row.confirmed_by_name !== null || row.confirmed_by_user_id !== null || !isRecord(row.receipt) || row.receipt.route !== "automatic" || write?.route !== "direct" || typeof write.sampled !== "boolean")) throw new Error("自动办理署名或原回执不完整，请刷新核对");
    let stop: AutomaticStop | null = null;
    if (row.automatic_stop != null) {
      if (!isRecord(row.automatic_stop) || !isRecord(row.automatic_stop.receipt)) throw new Error("自动暂停依据不完整，请刷新核对");
      const original = row.automatic_stop.receipt, threshold = version(original.maximum_retraction_basis_points);
      if (threshold > 10000) throw new Error("自动暂停门槛不完整，请刷新核对");
      stop = { generated: version(original.generated), withdrawn: version(original.withdrawn), maximum_retraction_basis_points: threshold, recovery_conditions: text(original.recovery_conditions) };
    }
    application = { automatic_stop: stop, capture_mode: mode, confirmed_by_name: mode === "direct" ? null : text(row.confirmed_by_name), requested_by_name: row.requested_by_name == null ? null : text(row.requested_by_name), sampled: mode === "direct" && write?.sampled === true, write_reason: write && typeof write.reason_label === "string" ? write.reason_label : null, withdrawn_at: row.withdrawn_at == null ? null : text(row.withdrawn_at), can_withdraw: row.can_withdraw === true, withdrawal_notice: typeof row.withdrawal_notice === "string" ? row.withdrawal_notice : "当前未提供撤回条件，请刷新核对。", withdrawal_receipt: row.withdrawal_receipt == null ? null : parseWithdrawal(row.withdrawal_receipt), id: text(row.id), issue_id: text(row.issue_id), disposition: row.disposition as Application["disposition"], created_at: text(row.created_at), writer_name: text(row.writer_name), run_id: identity(row.run_id), result_id: identity(row.result_id), requested_by_user_id: text(row.requested_by_user_id), output_event_row_id: row.output_event_row_id };
  }
  return { result_id: identity(value.result_id), source_digest: text(value.source_digest), can_apply: value.can_apply, notice: text(value.notice), application, sources_current: value.sources_current, review: value.review == null ? null : parseReview(value.review), review_receipt: value.review_receipt == null ? null : parseReviewItem(value.review_receipt) };
}
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function requestBody(path: string, command?: Command | WithdrawalCommand["body"] | ReviewCommand): Promise<unknown> {
  const response = await fetch(path, { method: command ? "POST" : "GET", cache: "no-store", headers: command ? { "Content-Type": "application/json" } : undefined, body: command ? JSON.stringify(command) : undefined });
  const body: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new RequestError(isRecord(body) && typeof body.detail === "string" ? body.detail : isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "办理回执暂不可用，请沿原请求核对", response.status);
  return body;
}
async function request(path: string, command?: Command): Promise<Data> { return parse(await requestBody(path, command)); }

export function AiIssueApplication(props: { projectId: string; runId: string; onIssueChanged?: (withdrawnIssueIds: string[]) => Promise<void> }) { return <Application key={`${props.projectId}:${props.runId}`} {...props} />; }
function Application({ projectId, runId, onIssueChanged }: { projectId: string; runId: string; onIssueChanged?: (withdrawnIssueIds: string[]) => Promise<void> }) {
  const [data, setData] = useState<Data | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [pending, setPending] = useState<Command | null>(null);
  const [withdrawPending, setWithdrawPending] = useState<WithdrawalCommand | null>(null), [withdrawal, setWithdrawal] = useState<WithdrawalReceipt | null>(null), [reason, setReason] = useState("");
  const [reviewReason, setReviewReason] = useState(""), [reviewPending, setReviewPending] = useState<ReviewCommand | null>(null);
  const active = useRef(true), locked = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const path = `/api/projects/${encodeURIComponent(projectId)}/ai-issue-applications/${encodeURIComponent(runId)}`;
  async function load() {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(null);
    try { const value = await request(path); if (active.current) setData(value); }
    catch (failure) { if (active.current) { setData(null); setError(failure instanceof Error ? failure.message : "办理条件读取失败"); } }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function apply(command: Command) {
    if (locked.current) return;
    locked.current = true; setPending(command); setBusy(true); setError(null);
    try {
      const value = await request(path, command);
      if (value.result_id !== command.result_id || value.application === null) throw new Error("尚未取得完整办理回执，请沿原请求核对");
      if (active.current) { setData(value); setPending(null); }
    } catch (failure) {
      if (active.current) { setError(failure instanceof Error ? failure.message : "尚未取得明确办理回执，请沿原请求核对"); if (failure instanceof RequestError && failure.status >= 400 && failure.status < 500) { setPending(null); setData(null); } }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function withdraw(command: WithdrawalCommand) {
    if (locked.current) return;
    locked.current = true; setWithdrawPending(command); setBusy(true); setError(null);
    try {
      const value = parseWithdrawal(await requestBody(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-applications/${encodeURIComponent(command.run_id)}/${command.kind === "single" ? "withdraw" : "withdraw-run"}`, command.body));
      if (value.kind !== command.kind || (command.kind === "single" && !value.items.some(item => item.application_id === command.body.application_id))) throw new Error("尚未取得对应的撤回回执，请沿原请求核对");
      if (active.current) { setWithdrawal(value); setWithdrawPending(null); setReason(""); setData(current => current?.application ? { ...current, application: { ...current.application, can_withdraw: false } } : current); }
      if (active.current) await onIssueChanged?.(value.items.filter(item => item.status === "withdrawn").map(item => item.issue_id));
      const refreshed = await request(path);
      if (active.current) setData(refreshed);
    } catch (failure) {
      if (active.current) { setError(failure instanceof Error ? failure.message : "撤回结果尚未明确，请沿原请求核对"); if (failure instanceof RequestError && failure.status >= 400 && failure.status < 500) { setWithdrawPending(null); setData(current => current?.application ? { ...current, application: { ...current.application, can_withdraw: false, withdrawal_notice: "请刷新核对最新撤回条件。" } } : current); } }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function reviewSuggestion(command: ReviewCommand) {
    if (locked.current) return;
    locked.current = true; setReviewPending(command); setBusy(true); setError(null);
    try {
      const value = parse(await requestBody(`${path}/review`, command));
      if (value.result_id !== command.result_id || !value.review || !value.review_receipt || value.review_receipt.action !== command.action || value.review_receipt.reason !== command.reason || value.review_receipt.version !== command.expected_version + 1 || value.review.version < value.review_receipt.version) throw new Error("尚未取得完整处置回执，请沿原请求核对");
      if (active.current) { setData(value); setReviewPending(null); setReviewReason(""); }
    } catch (failure) {
      if (active.current) { setError(failure instanceof Error ? failure.message : "处置结果尚未明确，请沿原请求核对"); if (failure instanceof RequestError && failure.status >= 400 && failure.status < 500) { setReviewPending(null); setData(null); } }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function olderReviews(before: number) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(null);
    try {
      const page = parseReview(await requestBody(`${path}/review?before_version=${before}`));
      if (active.current && data?.review && page.version !== data.review.version) setError("处置记录已有更新，请刷新查看最新回执。");
      if (active.current) setData(current => current?.review ? { ...current, can_apply: current.can_apply && page.can_change && page.state !== "declined" && page.version === current.review.version, review: { ...page, items: [...current.review.items, ...page.items.filter(item => !current.review!.items.some(old => old.id === item.id))] } } : current);
    } catch (failure) {
      if (active.current) { setError(failure instanceof Error ? failure.message : "处置历史读取失败"); if (failure instanceof RequestError && [401, 403].includes(failure.status)) setData(null); }
    } finally { locked.current = false; if (active.current) setBusy(false); }
  }
  const mutationPending = !!pending || !!withdrawPending || !!reviewPending;
  const receipt = data?.application;
  const withdrawalReceipt = withdrawal ?? receipt?.withdrawal_receipt;
  const priorApplication = !!receipt && (receipt.run_id !== runId || receipt.result_id !== data?.result_id);
  return <details className="border-t pt-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !data && !busy && !mutationPending) void load(); }}>
    <summary className="cursor-pointer text-xs font-medium text-primary">实际办理与回链</summary>
    <div className="mt-3 space-y-2 text-xs">
      <p className="leading-5 text-muted-foreground">按原回执核对建议、来源与实际办理结果，保留原问题、本次运行及办理署名。</p>
      <Button size="sm" variant="outline" disabled={busy || mutationPending} onClick={() => void load()}>刷新办理条件与回执</Button>
      {busy && <p role="status">正在核对办理回执…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      {data && <p className="leading-5 text-muted-foreground">{data.notice}</p>}
      {data && !data.sources_current && <p className="text-primary">当前来源已有变化，原办理记录保留；请核对来源记录。</p>}
      {receipt ? <div className="space-y-2 border-l-2 pl-3">
        {priorApplication && <div className="space-y-1"><p className="font-medium">同一来源已有办理回执，沿原问题继续</p><p className="text-muted-foreground">本条原建议未被再次应用；以下保留当时的实际办理记录。</p></div>}
        <p className="font-medium">{receipt.withdrawn_at ? "AI 创建的问题已撤回" : receipt.disposition === "created" ? "AI 已创建问题" : "已关联已有问题，原问题保持"}</p>
        {receipt.capture_mode === "direct" ? <><p className="font-medium">AI 自动办理</p><p>办理署名：{receipt.writer_name} · 请求来源：{receipt.requested_by_name ?? "原生成请求人（沿原运行留存）"}</p>{receipt.write_reason && <p className="text-muted-foreground">{receipt.write_reason}</p>}</> : <p>办理署名：{receipt.writer_name} · 确认人：{receipt.confirmed_by_name}</p>}
        <p className="text-muted-foreground">办理时间：<time dateTime={receipt.created_at}>{new Date(receipt.created_at).toLocaleString("zh-CN")}</time></p>
        <a className="inline-block text-primary underline underline-offset-2" href={`/projects?project=${encodeURIComponent(projectId)}&tab=work-items&entity_id=${encodeURIComponent(receipt.issue_id)}`}>{receipt.withdrawn_at ? "查看原问题历史" : "查看原问题与继续办理"}</a>
        {receipt.withdrawn_at && <p className="text-primary">撤回时间：<time dateTime={receipt.withdrawn_at}>{new Date(receipt.withdrawn_at).toLocaleString("zh-CN")}</time>；原建议与办理回执保留。</p>}
        {receipt.capture_mode === "direct" && receipt.sampled && <AiIssueSampleReview projectId={projectId} runId={receipt.run_id} applicationId={receipt.id} issueId={receipt.issue_id} disabled={busy || mutationPending} />}
        {receipt.automatic_stop && <section aria-label="自动建单暂停说明" className="space-y-1 border-t pt-2 text-primary"><p className="font-medium">自动建单已暂停，后续转逐次确认</p><p>原统计：自动创建 {receipt.automatic_stop.generated} 条，撤回 {receipt.automatic_stop.withdrawn} 条；原撤回率门槛不高于 {receipt.automatic_stop.maximum_retraction_basis_points / 100}%。</p><p className="whitespace-pre-wrap break-words leading-5">恢复条件：{receipt.automatic_stop.recovery_conditions}</p></section>}
        <p className="leading-5 text-muted-foreground">{receipt.withdrawal_notice}</p>
        {receipt.disposition === "created" && receipt.can_withdraw && !receipt.withdrawn_at && !mutationPending && <div className="space-y-2 pt-2">
          <label className="block space-y-1"><span>撤回原因（必填，办理时记录你的姓名）</span><textarea className="min-h-20 w-full rounded-lg border bg-background px-3 py-2" value={reason} disabled={busy} maxLength={2000} onChange={event => setReason(event.target.value)} /></label>
          <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || !reason.trim()} onClick={() => void withdraw({ kind: "single", run_id: receipt.run_id, body: { request_id: crypto.randomUUID(), application_id: receipt.id, reason: reason.trim() } })}>撤回这条AI创建的问题</Button><Button size="sm" variant="outline" disabled={busy || !reason.trim()} onClick={() => void withdraw({ kind: "run", run_id: receipt.run_id, body: { request_id: crypto.randomUUID(), reason: reason.trim() } })}>撤销本次运行</Button></div>
          <p className="text-muted-foreground">整次运行仅撤回仍符合条件的 AI 问题，跳过项及原因会保留。</p>
        </div>}
      </div> : data && data.can_apply && data.sources_current && data.review?.state !== "declined" && !mutationPending ? <Button size="sm" disabled={busy} onClick={() => void apply({ request_id: crypto.randomUUID(), result_id: data.result_id, expected_digest: data.source_digest })}>一次确认并办理</Button> : null}
      {data?.review && <section aria-label="建议处置" className="space-y-2 border-t pt-3">
        <p className="font-medium">{data.review.state === "declined" ? "已不采纳" : data.review.state === "reopened" ? "已重新考虑 · 待核对" : "建议尚未处置"}</p>
        <p className="leading-5 text-muted-foreground">{data.review.notice}</p>
        <p className="leading-5 text-muted-foreground">不采纳只记录本条建议的处置，不撤回或删除问题；重新考虑恢复待核，不会自动建单。</p>
        {data.review.can_change && !receipt && !mutationPending && <div className="space-y-2">
          <label className="block space-y-1"><span>处置原因（必填，办理时记录你的姓名）</span><textarea className="min-h-20 w-full rounded-lg border bg-background px-3 py-2" value={reviewReason} disabled={busy} maxLength={2000} onChange={event => setReviewReason(event.target.value)} /></label>
          <Button size="sm" variant="outline" disabled={busy || !reviewReason.trim()} onClick={() => void reviewSuggestion({ request_id: crypto.randomUUID(), result_id: data.result_id, expected_digest: data.source_digest, expected_version: data.review!.version, action: data.review!.state === "declined" ? "reopen" : "decline", reason: reviewReason.trim() })}>{data.review.state === "declined" ? "重新考虑" : "不采纳这条建议"}</Button>
        </div>}
        {data.review_receipt && <div className="space-y-1 border-l-2 pl-3"><p>本次请求回执：{data.review_receipt.action === "decline" ? "不采纳" : "重新考虑"} · {data.review_receipt.actor_name}</p><p className="whitespace-pre-wrap break-words">{data.review_receipt.reason}</p><time className="text-muted-foreground" dateTime={data.review_receipt.created_at}>{new Date(data.review_receipt.created_at).toLocaleString("zh-CN")}</time></div>}
        <details><summary className="cursor-pointer text-primary">建议处置历史 · {data.review.version} 次</summary><ol className="mt-2 space-y-3">{data.review.items.map(item => <li key={item.id} className="space-y-1 border-l-2 pl-3"><p>{item.version}. {item.action === "decline" ? "不采纳" : "重新考虑"} · {item.actor_name}</p><p className="whitespace-pre-wrap break-words leading-5">{item.reason}</p><time className="text-muted-foreground" dateTime={item.created_at}>{new Date(item.created_at).toLocaleString("zh-CN")}</time></li>)}</ol>{data.review.items.length === 0 && <p className="mt-2 text-muted-foreground">尚无具名处置记录。</p>}{data.review.next_before_version !== null && <Button className="mt-2" size="sm" variant="outline" disabled={busy || mutationPending} onClick={() => void olderReviews(data.review!.next_before_version!)}>更早的处置记录</Button>}</details>
      </section>}
      {reviewPending && !busy && <div className="space-y-2"><p className="text-primary">本次处置结果尚未明确，将沿原请求核对；原因与原版本保持不变。</p><Button size="sm" onClick={() => void reviewSuggestion(reviewPending)}>沿原请求核对处置结果</Button></div>}
      {withdrawalReceipt && <div className="space-y-2 border-t pt-2"><p className="font-medium">{withdrawalReceipt.kind === "single" ? "单条撤回回执" : "本次运行撤销回执"}</p><p>办理人：{withdrawalReceipt.actor_name} · <time dateTime={withdrawalReceipt.created_at}>{new Date(withdrawalReceipt.created_at).toLocaleString("zh-CN")}</time></p><ul className="space-y-2">{withdrawalReceipt.items.map(item => <li key={item.application_id}><span className={item.status === "skipped" ? "text-primary" : ""}>{item.status === "withdrawn" ? "已撤回" : "已跳过"}：{item.reason}</span> <a className="text-primary underline" href={`/projects?project=${encodeURIComponent(projectId)}&tab=work-items&entity_id=${encodeURIComponent(item.issue_id)}`}>查看问题历史</a></li>)}</ul></div>}
      {withdrawPending && !busy && <div className="space-y-2"><p className="text-primary">撤回结果尚未明确，将沿原请求核对；不会另起一次撤回。</p><Button size="sm" onClick={() => void withdraw(withdrawPending)}>沿原请求核对撤回结果</Button></div>}
      {pending && !busy && <div className="space-y-2"><p className="text-primary">本次结果尚未明确，继续核对会保留原请求，不会另起一次办理。</p><Button size="sm" onClick={() => void apply(pending)}>沿原请求核对办理结果</Button></div>}
    </div>
  </details>;
}
