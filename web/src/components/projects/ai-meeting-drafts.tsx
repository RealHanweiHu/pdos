"use client";

import { useRef, useState } from "react";
import { RobotIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { MeetingActionProposalView, actionProposalReady } from "@/components/ai/meeting-action-proposal";
import { MeetingDecisionProposalView, decisionProposalReady } from "@/components/ai/meeting-decision-proposal";

type Kind = "minutes" | "actions" | "decisions";
function StructuredContent({ kind, projectId, payload, onChange }: { kind: Kind; projectId: string; payload: Record<string, unknown>; onChange?: (value: Record<string, unknown>) => void }) {
  return kind === "actions" ? <MeetingActionProposalView draftOwned projectId={projectId} payload={payload} onChange={onChange} /> : <MeetingDecisionProposalView draftOwned projectId={projectId} payload={payload} onChange={onChange} />;
}

type Draft = {
  current_payload: Record<string, unknown>; published_entity_id: string | null;
  id: string; run_id: string; finding_id: string; revision: number;
  state: "pending_confirmation" | "active" | "withdrawn" | "published";
  writer_name: string; created_at: string; body: string; unresolved_points: string;
  capture_mode: "trial" | "direct"; review_required: boolean;
  write_receipt: { route: "direct" | "confirm"; reason_label?: string } | null;
  automatic_stop_reason: string | null;
  source_current: boolean; human_edited: boolean;
  payload: Record<string, unknown> & { body: string; unresolved_points: string; citations: { segment_id: string; exact_quote: string }[] };
  history_next_before: number | null;
  history: { payload: Record<string, unknown> | null; revision: number; action: string; actor_name: string; created_at: string; reason: string; body: string; unresolved_points: string }[];
};
type Data = {
  current_user_id: string;
  items: Draft[]; next_before: string | null; notice: string; policy_ready: boolean;
  scope: { enabled: boolean; revision: number }; can_manage_scope: boolean; can_manage: boolean;
};
type Command = { url: string; body: string };
const labels = { pending_confirmation: "待确认草稿", active: "可继续修订", withdrawn: "已撤回", published: "已正式发布" };
const actions: Record<string, string> = { confirm: "确认采用", edit: "人工修订", withdraw: "撤回草稿", publish: "正式发布", withdraw_run: "撤回本次生成" };
function actionLabel(item: Draft, action: string) { return action === "confirm" && item.capture_mode === "direct" ? "抽检确认" : actions[action] ?? action; }
const field = "mt-1 w-full rounded-md border bg-background p-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring";

class DraftError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
async function read<T>(url: string, body?: string): Promise<T> {
  const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin",
    ...(body ? { headers: { "Content-Type": "application/json" }, body } : {}) });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new DraftError(response.status >= 500 ? "暂时无法读取办理结果，请稍后重试。" : data?.detail?.message ?? "当前无法办理，请刷新资料。", response.status);
  }
  return await response.json() as T;
}

export function AiMeetingDrafts({ projectId, meetingId, onPublished, kind = "minutes" }: { projectId: string; meetingId: string; kind?: Kind; onPublished: () => Promise<void> }) {
  const noun = { minutes: "纪要", actions: "行动项", decisions: "决策" }[kind];
  const publishLabel = { minutes: "正式发布纪要", actions: "下达正式行动", decisions: "本人批准决策" }[kind];
  async function request<T>(url: string, body?: string): Promise<T> {
    return read<T>(`${url}${url.includes("?") ? "&" : "?"}kind=${kind}`, body);
  }
  const [editedPayload, setEditedPayload] = useState<Record<string, unknown> | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [edit, setEdit] = useState<{ id: string; body: string; unresolved: string } | null>(null);
  const [reviewAction, setReviewAction] = useState<{ draft: Draft; action: string } | null>(null);
  const [pending, setPending] = useState<Command | null>(null);
  const flight = useRef(false);
  const base = `/api/projects/${projectId}/meetings/${meetingId}/ai-minutes-drafts`;
  async function load(older = false) {
    const next = await request<Data>(`${base}${older && data?.next_before ? `?before=${data.next_before}` : ""}`);
    setData(previous => older && previous ? { ...next, items: [...previous.items, ...next.items] } : next);
  }
  async function refresh(older = false) {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError(null);
    try { await load(older); }
    catch (failure) {
      setError(failure instanceof Error ? failure.message : "草稿暂不可用。");
      if (failure instanceof DraftError && [401, 403].includes(failure.status)) setData(null);
    } finally { flight.current = false; setBusy(false); }
  }
  async function olderHistory(item: Draft) {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError(null);
    try {
      const result = await request<{ items: Draft["history"]; next_before: number | null }>(`${base}/${item.id}/history?before=${item.history_next_before}`);
      setData(previous => previous ? { ...previous, items: previous.items.map(draft => draft.id === item.id ? { ...draft, history: [...draft.history, ...result.items], history_next_before: result.next_before } : draft) } : previous);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "历史读取失败。");
      if (failure instanceof DraftError && [401, 403].includes(failure.status)) setData(null);
    } finally { flight.current = false; setBusy(false); }
  }
  async function execute(command: Command) {
    if (flight.current) return;
    flight.current = true; setBusy(true); setError(null); setNotice(null); setPending(command);
    try {
      const result = await request<{ items?: { result: string; reason: string }[] }>(command.url, command.body);
      setPending(null); setEdit(null); setEditedPayload(null); setReviewAction(null); setReason("");
      setNotice(result.items ? `本次${noun}生成撤回完成：${result.items.filter(item => item.result === "withdrawn").length} 条已撤回；${result.items.filter(item => item.result === "skipped").map(item => item.reason).join("、") || "没有跳过项"}。原历史保留。` : "办理回执已保存。AI原稿和具名修改历史均已保留。");
      await load(); await onPublished();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "结果尚未确认，请重试原请求。");
      if (failure instanceof DraftError && failure.status < 500) {
        setPending(null);
        if ([401, 403].includes(failure.status)) setData(null);
      }
    } finally { flight.current = false; setBusy(false); }
  }
  function submit() {
    if (!reviewAction) return;
    if (reviewAction.action === "withdraw_run") {
      void execute({ url: `${base}/runs/${reviewAction.draft.run_id}/withdraw`, body: JSON.stringify({ request_id: crypto.randomUUID(), reason: reason.trim() }) });
      return;
    }
    void execute({ url: `${base}/${reviewAction.draft.id}/actions`, body: JSON.stringify({
      request_id: crypto.randomUUID(), expected_revision: reviewAction.draft.revision,
      action: reviewAction.action, reason: reason.trim(),
      ...(reviewAction.action === "edit" ? kind === "minutes" && edit ? { body: edit.body, unresolved_points: edit.unresolved } : { payload: editedPayload } : {}),
    }) });
  }
  const locked = busy || pending !== null;
  return <details className="rounded-lg border bg-card p-2 sm:p-3" onToggle={event => {
    if (event.currentTarget.open && !data && !flight.current) void refresh();
  }}>
    <summary className="cursor-pointer text-sm font-medium"><RobotIcon className="mr-1.5 inline text-primary" size={16} aria-hidden="true" />AI {noun}草稿</summary>
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-xs leading-5 text-muted-foreground">{data?.notice ?? "根据会议原文生成草稿，按当前写入政策直接保存或确认采用；人工修订和正式办理分别留痕。"}</p>
        <Button size="sm" variant="outline" disabled={locked || !!reviewAction} onClick={() => void refresh()}>刷新草稿</Button>
      </div>
      {data && <div className="rounded-md bg-muted/30 px-3 py-2 text-xs leading-5">
        <p>本项目 AI 起草范围：{data.scope.enabled ? "已授权" : "未授权"} · 租户分级偏好：{data.policy_ready ? "已设置" : "尚未启用"}</p>
        <p className="text-muted-foreground">范围授权只允许 AI 起草本类内容，不授予正式下达或批准权限。能力评测完成后，后续生成才会进入此处。</p>
        {data.can_manage_scope && <details className="mt-2"><summary className="cursor-pointer text-primary">调整本项目起草范围</summary>
          <label className="mt-2 block">调整原因<input className={field} value={reason} maxLength={1000} disabled={locked || !!reviewAction} onChange={event => setReason(event.target.value)} /></label>
          <Button className="mt-2" size="sm" variant="outline" disabled={locked || !!reviewAction || !reason.trim()} onClick={() => void execute({ url: `${base}/scope`, body: JSON.stringify({ request_id: crypto.randomUUID(), expected_revision: data.scope.revision, enabled: !data.scope.enabled, reason: reason.trim() }) })}>{data.scope.enabled ? "暂停本项目 AI 起草" : "允许本项目 AI 起草"}</Button>
          {!data.policy_ready && <a className="ml-3 text-primary underline" href="/governance/ai">前往 AI 治理设置</a>}
        </details>}
      </div>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {notice && <p role="status" className="text-xs text-success">{notice}</p>}
      {pending && <div className="flex flex-wrap items-center gap-2 text-xs"><p>保存结果尚未确认，请复用原请求找回回执。</p><Button size="sm" disabled={busy} onClick={() => void execute(pending)}>重试原请求</Button></div>}
      {data?.items.length === 0 && <p className="py-2 text-xs text-muted-foreground">尚无分级写入草稿。已生成的旧候选仍可从原入口回查。</p>}
      {data?.items.map(item => <article key={item.id} className="rounded-lg border p-2 sm:p-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs"><p className="font-semibold">{item.writer_name} · {item.state === "published" ? kind === "actions" ? "已下达行动" : kind === "decisions" ? "已批准决策" : "已正式发布" : item.capture_mode === "direct" && item.state === "active" ? "AI已写入草稿" : labels[item.state]}</p><span className="text-muted-foreground">{new Date(item.created_at).toLocaleString("zh-CN")}</span></div>
        {item.capture_mode === "direct" && item.review_required && <p className="mt-2 rounded-md bg-primary/5 px-2 py-1.5 text-xs leading-5 text-primary">抽检待核对 · 请核对正文与原文依据，再确认抽检结果；需要调整时可直接修订。</p>}
        {item.write_receipt?.route === "confirm" && item.write_receipt.reason_label && <p className="mt-2 text-xs leading-5 text-primary">{item.write_receipt.reason_label}</p>}
        {item.automatic_stop_reason && <p className="mt-2 text-xs leading-5 text-primary">{item.automatic_stop_reason}</p>}
        {!item.source_current && item.state !== "published" && <p className="mt-2 text-xs text-destructive">原转录、说话人或正式来源已变化，请重新核对并生成。</p>}
        {kind === "decisions" && item.state === "active" && item.current_payload.approver_id && item.current_payload.approver_id !== data.current_user_id ? <p className="mt-2 text-xs text-muted-foreground">等待草稿中指定的批准人本人办理。</p> : null}
        {item.human_edited && <p className="mt-2 text-xs text-muted-foreground">已有人工修订，AI 停止覆盖，撤回保留人工内容。</p>}
        {kind !== "minutes" ? <StructuredContent kind={kind} projectId={projectId} payload={item.current_payload} /> : <>        <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <section className="min-w-0"><h4 className="mb-1 text-xs font-medium">纪要正文</h4><p className="whitespace-pre-wrap break-words text-sm leading-6">{item.body}</p></section>
          <section className="min-w-0 rounded-md bg-muted/30 p-3"><h4 className="mb-1 text-xs font-medium">未决事项</h4><p className="whitespace-pre-wrap break-words text-xs leading-5">{item.unresolved_points}</p></section>
        </div></>}
        {item.published_entity_id && <a className="mt-2 inline-block text-xs text-primary underline" href={`/projects?project=${projectId}&tab=${kind === "actions" ? "work-items" : "decisions"}&entity_id=${item.published_entity_id}&meeting=${meetingId}${kind === "minutes" ? `&minutes=${item.published_entity_id}` : ""}`}>打开正式{noun}记录</a>}
        <details className="mt-3 text-xs"><summary className="cursor-pointer text-muted-foreground">查看原文引用与办理历史</summary>
          <div className="mt-2 space-y-2">{item.payload.citations.map((quote, index) => <blockquote className="whitespace-pre-wrap break-words border-l-2 border-primary/30 pl-3 leading-5" key={`${quote.segment_id}:${index}`}>{quote.exact_quote}</blockquote>)}
          <details className="rounded-md border p-2"><summary className="cursor-pointer">AI 原稿 · 原始正文</summary>{kind === "minutes" ? <><p className="mt-2 whitespace-pre-wrap break-words leading-5">{item.payload.body}</p><p className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">未决事项：{item.payload.unresolved_points}</p></> : <StructuredContent kind={kind} projectId={projectId} payload={item.payload} />}<a className="text-primary underline" href={`/ai-review?finding=${item.finding_id}`}>查看原候选和生成依据</a></details>
          {data.can_manage && <Button size="sm" variant="outline" disabled={locked || !!reviewAction} onClick={() => { setReason(""); setReviewAction({ draft: item, action: "withdraw_run" }); }}>撤回本次生成</Button>}
          {item.history.map(entry => <details key={entry.revision} className="rounded-md border p-2"><summary className="cursor-pointer">第 {entry.revision} 次 · {actionLabel(item, entry.action)} · {entry.actor_name} · {new Date(entry.created_at).toLocaleString("zh-CN")}</summary><p className="mt-2 text-muted-foreground">{entry.reason}</p>{kind !== "minutes" && entry.payload ? <StructuredContent kind={kind} projectId={projectId} payload={entry.payload} /> : <><p className="mt-2 whitespace-pre-wrap break-words leading-5">{entry.body}</p><p className="mt-2 whitespace-pre-wrap break-words leading-5">未决事项：{entry.unresolved_points}</p></>}</details>)}{item.history_next_before && <Button size="sm" variant="outline" disabled={locked || !!reviewAction} onClick={() => void olderHistory(item)}>更早的办理历史</Button>}</div>
        </details>
        {data.can_manage && !['published', 'withdrawn'].includes(item.state) && <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
          {(item.state === "pending_confirmation" || item.review_required) && <Button size="sm" disabled={locked || !!reviewAction || !item.source_current} onClick={() => { setReason(""); setReviewAction({ draft: item, action: "confirm" }); }}>{item.capture_mode === "direct" ? "确认抽检结果" : "确认采用此草稿"}</Button>}
          {item.state === "active" && <><Button size="sm" variant="outline" disabled={locked || !!reviewAction || !item.source_current} onClick={() => { setReason(""); setEdit(kind === "minutes" ? { id: item.id, body: item.body, unresolved: item.unresolved_points } : null); setEditedPayload(item.current_payload); setReviewAction({ draft: item, action: "edit" }); }}>人工修订</Button><Button size="sm" disabled={locked || !!reviewAction || !item.source_current || (kind === "actions" && !actionProposalReady(item.current_payload)) || (kind === "decisions" && (!decisionProposalReady(item.current_payload) || item.current_payload.approver_id !== data.current_user_id))} onClick={() => { setReason(""); setReviewAction({ draft: item, action: "publish" }); }}>{publishLabel}</Button></>}
          <Button size="sm" variant="outline" disabled={locked || !!reviewAction || item.human_edited} onClick={() => { setReason(""); setReviewAction({ draft: item, action: "withdraw" }); }}>撤回 AI 草稿</Button>
        </div>}
        {reviewAction?.draft.id === item.id && <div className="mt-3 space-y-3 rounded-md border border-primary/30 bg-primary/5 p-3">
          <p className="text-xs font-medium">{actionLabel(item, reviewAction.action)}{reviewAction.action === "publish" ? "：以你的身份正式办理，原业务权限与批准规则保持。" : reviewAction.action === "withdraw" ? "：原稿与历史保留，新增撤回回执。" : "：本次操作将保留具名回执。"}</p>
          {edit?.id === item.id && <><label className="block text-xs">修订正文<textarea className={`${field} min-h-40`} maxLength={20000} disabled={locked} value={edit.body} onChange={event => setEdit({ ...edit, body: event.target.value })} /></label><label className="block text-xs">未决事项<textarea className={`${field} min-h-20`} maxLength={5000} disabled={locked} value={edit.unresolved} onChange={event => setEdit({ ...edit, unresolved: event.target.value })} /></label></>}
          {reviewAction.action === "edit" && kind !== "minutes" && editedPayload && <fieldset disabled={locked}><StructuredContent kind={kind} projectId={projectId} payload={editedPayload} onChange={setEditedPayload} /></fieldset>}
          <label className="block text-xs">办理依据<input className={field} maxLength={1000} value={reason} disabled={locked} onChange={event => setReason(event.target.value)} /></label>
          <div className="flex gap-2"><Button size="sm" disabled={locked || !reason.trim() || (edit !== null && (!edit.body.trim() || !edit.unresolved.trim()))} onClick={submit}>{reviewAction.action === "confirm" && item.capture_mode === "direct" ? "保存抽检确认" : `确认${actions[reviewAction.action]}`}</Button><Button size="sm" variant="outline" disabled={locked} onClick={() => { setReviewAction(null); setEdit(null); setEditedPayload(null); setReason(""); }}>取消</Button></div>
        </div>}
      </article>)}
      {data?.next_before && <Button size="sm" variant="outline" disabled={locked || !!reviewAction} onClick={() => void refresh(true)}>更早的草稿</Button>}
    </div>
  </details>;
}
