"use client";

import { ChangeDiscussionContinuation } from "./change-discussion-continuation";
import { ChangeToolReceipts } from "@/components/ai/change-tool-receipts";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody, requestIdentity } from "@/components/workspace-api";
import { MeetingPlanning, type MeetingPlanningSelection } from "@/components/projects/meeting-planning";
import { ConversationMeetingPlanResult } from "./conversation-meeting-plan";
import { MeetingTranscripts } from "@/components/projects/meeting-transcripts";
import { cancelAgentRun } from "./ai-api";
import { ConversationFiles, AttachmentDetail, attachmentRequest, parseAttachment, type ConversationAttachment } from "./conversation-files";
import { ConversationIntakeAi } from "./conversation-intake-ai";
import { ConversationIssueIntake } from "./conversation-issue-intake";
import { ConversationPdfIntake } from "@/components/ai/conversation-pdf-intake";
import { ConversationDecisionIntake } from "./conversation-decision-intake";
import { ConversationReportImports } from "./conversation-report-imports";
import { ConversationChangeSource, type ConversationChangeSourceValue } from "./conversation-change-source";
import { ConversationQualitySource, type ConversationQualitySourceValue } from "./conversation-quality-source";
import { AgentRunProgressPanel } from "./agent-run-progress";
import { WorkFocusSummary, parseWorkFocus, type WorkFocus } from "./conversation-work-focus";
import { ConversationFindingGroup } from "./conversation-finding-group";

function text(v: unknown): string { if (typeof v !== "string") throw new Error("会话资料不完整"); return v; }
function list(v: unknown): unknown[] { if (!Array.isArray(v)) throw new Error("会话清单不完整"); return v; }
function record(v: unknown): Record<string, unknown> { if (!isRecord(v)) throw new Error("会话记录不完整"); return v; }
function parse(v: unknown) { const value = record(v), scope = record(value.conversation); return { id: text(scope.id), projectId: text(scope.project_id), meetingId: typeof scope.meeting_id === "string" ? scope.meeting_id : null, creatorId: text(scope.created_by_user_id), visibility: scope.visibility === "project" ? "project" : "private", version: Number(scope.context_version), archived: scope.archived_at !== null, next: typeof value.next_before === "number" ? value.next_before : null, items: list(value.items).map(entry => { const row = record(entry); return { id: text(row.id), authorUserId: text(row.author_user_id), body: text(row.body), action: text(row.action), sequence: Number(row.sequence), time: text(row.created_at), attachmentIds: Array.isArray(row.attachment_ids) ? row.attachment_ids.filter((id): id is string => typeof id === "string") : [], receipt: record(row.receipt), objectFocus: isRecord(row.object_focus) ? row.object_focus : null, changeSource: isRecord(row.change_source) ? row.change_source : null, qualitySource: isRecord(row.quality_source) ? row.quality_source : null, meetingPlanningSource: isRecord(row.meeting_planning_source) ? row.meeting_planning_source : null }; }) }; }
type Data = ReturnType<typeof parse>;
const modes: Record<string, string> = { meeting_planning: "起草临时会议", quality_work_package: "准备品质调查与整改建议", change_work_package: "准备工程变更影响建议", note: "保存补充说明", project_query: "询问项目事实", meeting_reading: "核对会议内容", minutes: "准备纪要待审稿", actions: "准备行动待审稿", decisions: "准备决策待审稿", business: "准备问题、风险和变更" };
async function request(path: string, body?: object): Promise<unknown> { const r = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); const value: unknown = await responseBody(r).catch(() => null); if (!r.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "会话暂不可用，请刷新查看已保存消息"); return value; }

export function ProjectConversation({ presentation = "standard", projectId, meetingId = null, initialConversationId, defaultOpen = false, onDraftDirtyChange, initialAttachmentId, initialFragment, initialWorkFocus, shared = false, onConversationReady, onDelegateRequest }: { presentation?: "standard" | "assistant"; onDelegateRequest?: (goal: string) => void; shared?: boolean; onConversationReady?: (id: string) => void; initialWorkFocus?: WorkFocus; projectId: string; meetingId?: string | null; initialConversationId?: string; defaultOpen?: boolean; onDraftDirtyChange?: (dirty: boolean) => void; initialAttachmentId?: string; initialFragment?: number }) {
  const assistant = presentation === "assistant";
  const Root = assistant ? "section" : "details";
  const [data, setData] = useState<Data | null>(null);
  const [sessions, setSessions] = useState<{ id: string; time: string; archived: boolean }[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [canUpload, setCanUpload] = useState(false);
  const [actingUserId, setActingUserId] = useState("");
  const [body, setBody] = useState("");
  const [mode, setMode] = useState(meetingId ? "note" : "project_query");
  const [requestBusy, setBusy] = useState(defaultOpen || !!initialConversationId);
  const [filesBusy, setFilesBusy] = useState(false);
  const [operationBusy, setOperationBusy] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<ConversationAttachment[]>([]);
  const busy = requestBusy || filesBusy;
  const draftBusy = busy || operationBusy;
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<{ id: string; time: string }[]>([]);
  const [meetingTitle, setMeetingTitle] = useState<string | null>(null);
  const [planningDirty, setPlanningDirty] = useState(false);
  const [planningSource, setPlanningSource] = useState<MeetingPlanningSelection | null>(null);
  const [qualitySource, setQualitySource] = useState<ConversationQualitySourceValue | null>(null);
  const [changeSource, setChangeSource] = useState<ConversationChangeSourceValue | null>(null);
  const [workFocus, setWorkFocus] = useState<WorkFocus | undefined>(initialWorkFocus);
  const [focusSource, setFocusSource] = useState<Record<string, unknown> | null>(null);
  const [source, setSource] = useState<{ id: string; digest: string; reading: Record<string, unknown> } | null>(null);
  const pending = useRef<{ signature: string; requestId: string; messageId?: string } | null>(null);
  const creation = useRef<string | null>(null);
  const hasDraft = !!body.trim() || !!selectedFiles.length || !!planningSource || planningDirty;
  const scopeQuery = `project_id=${projectId}${meetingId ? `&meeting_id=${meetingId}` : ""}`;
  async function load(id: string, older = false) { const next = parse(await request(`/api/conversations/${id}${older && data?.next ? `?before_sequence=${data.next}` : ""}`)); if (next.projectId !== projectId || next.meetingId !== meetingId) throw new Error("所选会话范围与此入口不同，请从完整会话链接打开"); onConversationReady?.(next.id); setData(older && data ? { ...next, items: [...next.items, ...data.items.filter(row => !next.items.some(n => n.id === row.id))] } : next); }
  async function readWorkFocus(target = workFocus) {
    setFocusSource(null);
    if (!target) return;
    const value = record(await request(`/api/conversations/work-context/${projectId}/${target.kind}/${target.id}`));
    if (value.kind !== target.kind || value.id !== target.id || typeof value.digest !== "string") throw new Error("工作对象资料不完整，请刷新后继续");
    setFocusSource(value);
  }
  async function loadSources() { if (!meetingId) return; const base = `/api/projects/${projectId}/meetings/${meetingId}`; const [detail, raw] = await Promise.all([request(base), request(`${base}/transcripts`)]); setMeetingTitle(text(record(detail).title)); const v = record(raw); setTranscripts(list(v.items).map(r => { const row = record(r); return { id: text(row.id), time: text(row.uploaded_at) }; })); }
  async function initialize() { const values = record(await request(`/api/conversations?${scopeQuery}`)); const entries = list(values.items).filter(r => assistant ? record(r).visibility === (shared ? "project" : "private") : !shared || record(r).visibility === "project").map(r => { const row = record(r); return { id: text(row.id), time: text(row.updated_at), archived: row.archived_at !== null }; }); setSessions(entries); const identity = await requestIdentity(); if (!identity) throw new Error("请重新登录后打开会话"); setActingUserId(identity.user.id); setCanUpload(["owner", "admin", "project_manager", "engineer", "quality"].includes(identity.user.role)); const selected = data?.id ?? initialConversationId ?? entries[0]?.id; if (selected) await load(selected); await loadSources(); await readWorkFocus(); setLoaded(true); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "会话办理未完成"); } finally { setBusy(false); } }
  const openInitially = useEffectEvent(async () => { try { await initialize(); } catch (e) { setError(e instanceof Error ? e.message : "会话暂不可用"); } finally { setBusy(false); } });
  useEffect(() => { if (!defaultOpen && !initialConversationId) return; const handle = window.setTimeout(() => { void openInitially(); }, 0); return () => window.clearTimeout(handle); }, [defaultOpen, initialConversationId]);
  useEffect(() => { onDraftDirtyChange?.(hasDraft || draftBusy); }, [hasDraft, draftBusy, onDraftDirtyChange]);
  const followPageFocus = useEffectEvent(() => {
    if ((!shared && !assistant) || hasDraft || draftBusy) return;
    const target = initialWorkFocus;
    if (target?.id === workFocus?.id && target?.kind === workFocus?.kind) return;
    setWorkFocus(target);
    if (!target) setFocusSource(null);
    else void readWorkFocus(target).catch(e => setError(e instanceof Error ? e.message : "当前对象无法读取"));
  });
  useEffect(() => { const timer = window.setTimeout(() => followPageFocus(), 0); return () => window.clearTimeout(timer); }, [initialWorkFocus?.id, initialWorkFocus?.kind, hasDraft, draftBusy]);
  async function create() { creation.current ??= crypto.randomUUID(); const row = record(await request("/api/conversations", { project_id: projectId, meeting_id: meetingId, request_id: creation.current, visibility: shared ? "project" : "private" })); await load(text(row.id)); creation.current = null; setSessions(previous => [{ id: text(row.id), time: text(row.updated_at), archived: false }, ...previous.filter(s => s.id !== row.id)]); return text(row.id); }
  async function chooseSource(id: string) { setSource(null); if (!id || !meetingId) return; const base = `/api/projects/${projectId}/meetings/${meetingId}/transcripts/${id}`; const snapshot = record(await request(base)); if (snapshot.source_complete !== true || snapshot.superseded === true) throw new Error("此转写尚不完整或已被替代，请先核对原文"); setSource({ id, digest: text(snapshot.digest), reading: record(await request(`${base}/reading`)) }); }
  const sourceMode = !["note", "project_query", "change_work_package", "quality_work_package", "meeting_planning"].includes(mode);
  const rolloutField: Record<string, string> = { meeting_reading: "rollout", minutes: "minutes_rollout", actions: "actions_rollout", decisions: "decisions_rollout", business: "business_rollout" };
  const filesReady = !selectedFiles.length || mode === "note" || (mode === "project_query" && selectedFiles.every(f => f.status === "extracted" && f.classification === "internal" && !f.revoked_at));
  const available = (!workFocus || (!!focusSource && !selectedFiles.length && ["note", "project_query"].includes(mode) && !meetingId)) && filesReady && (mode !== "meeting_planning" || (planningSource?.ready === true && !selectedFiles.length && !meetingId)) && (mode !== "quality_work_package" || qualitySource?.ready === true) && (mode !== "change_work_package" || changeSource?.ready === true) && (!sourceMode || (source && source.reading.rollout === "live" && source.reading[rolloutField[mode]] === "live" && (mode !== "minutes" || source.reading.minutes_version !== null)));
  async function send(action = mode) {
    if (action !== "note" && (shared || assistant) && onDelegateRequest && /^(?:请|帮我|小Pai[，,：: ]*)?(?:持续跟进|盯着|跟进这个项目|帮我盯)/.test(body.trim())) {
      onDelegateRequest(body.trim());
      setNotice("已整理持续委托，请在下方核对工作日历并开始跟进；尚未启动后台任务。");
      return;
    }
    const conversationId = data?.id ?? await create();
    const payload = { ...(workFocus && focusSource ? { object_focus: { kind: workFocus.kind, id: workFocus.id, digest: focusSource.digest } } : {}), expected_context_version: data?.version ?? 1, body: action === "meeting_planning" ? planningSource?.label ?? "" : body.trim(), action, ...(action === "meeting_planning" && planningSource ? { meeting_planning_brief_id: planningSource.briefId, expected_digest: planningSource.digest } : {}), attachment_ids: selectedFiles.map(f => f.id), ...(action === "quality_work_package" && qualitySource ? { ncr_id: qualitySource.ncrId, quality_selections: qualitySource.selections, expected_digest: qualitySource.digest } : {}), ...(action === "change_work_package" && changeSource ? { ecr_id: changeSource.ecrId, impact_depth: changeSource.depth, expected_digest: changeSource.digest, allow_discussion: changeSource.allowDiscussion, include_supplier_notices: changeSource.includeSupplierNotices } : {}), ...(sourceMode && source ? { transcript_id: source.id, expected_digest: source.digest, expected_minutes_version: action === "minutes" ? source.reading.minutes_version : null } : {}) };
    const signature = JSON.stringify([conversationId, payload]); if (pending.current?.signature !== signature) pending.current = { signature, requestId: crypto.randomUUID() };
    const saved = record(await request(`/api/conversations/${conversationId}/messages`, { ...payload, request_id: pending.current.requestId })); pending.current.messageId = text(saved.id); setNotice("消息已保存，可刷新恢复；业务结果以运行和应用回执为准。");
    if (action !== "note") await runMessage(conversationId, text(saved.id));
    else await load(conversationId);
    pending.current = null; if (action !== "meeting_planning") setBody(""); setPlanningSource(null); setSelectedFiles([]);
  }
  async function runMessage(conversationId: string, messageId: string) {
    setOperationBusy(true); setBusy(false);
    try {
      await load(conversationId);
      await request(`/api/conversations/${conversationId}/messages/${messageId}/run`, {});
    } finally {
      try { await load(conversationId); } finally { setOperationBusy(false); }
    }
  }
  const operations = data?.items.some(m => ["queued", "running"].includes(String(m.receipt.status)) || m.receipt.convened_discussion != null);
  return <Root className={assistant ? "space-y-4" : "rounded-lg border bg-card p-4"} open={assistant ? undefined : defaultOpen || !!initialConversationId} onToggle={e => { if (e.currentTarget.open && !defaultOpen && !initialConversationId && !loaded && !busy) void act(initialize); }}>
    {!assistant && <summary className="cursor-pointer font-semibold">{shared ? "对话与项目记忆" : meetingId ? "在同一会话核对会议与办理" : "连续项目会话"}</summary>}
    <div className={assistant ? "space-y-4" : "mt-4 space-y-4"}>
      <p className="text-xs text-muted-foreground">{(data ? data.visibility === "project" : shared) ? "项目成员可见：本会话的消息、附件与办理结果共享。小Pai会保留补充和纠正的原文依据。" : assistant ? "个人对话 · 仅你可见" : <>会话仅本人可见，范围固定在当前{meetingId ? "项目和会议" : "项目"}；业务对象仍按项目权限共享。补充说明会保存为新消息，不自动批准任何候选。</>}</p>
      {meetingId && <p className="text-sm font-medium">当前会议：{meetingTitle ?? "正在读取会议名称…"}</p>}
      <details open={!assistant}><summary className="cursor-pointer text-xs text-muted-foreground">对话记录与操作</summary><div className="mt-2 flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(initialize)}>刷新会话</Button><Button size="sm" variant="outline" disabled={draftBusy || hasDraft} onClick={() => void act(async () => { await create(); setSource(null); setChangeSource(null); setQualitySource(null); setPlanningSource(null); setMode(meetingId ? "note" : "project_query"); setSelectedFiles([]); })}>新会话</Button>{sessions.length > 0 && <select aria-label={shared ? "选择项目共享会话" : "选择本人会话"} className="rounded-md border bg-background p-2 text-xs" disabled={draftBusy || hasDraft} value={data?.id ?? ""} onChange={e => void act(async () => { await load(e.target.value); setSource(null); setChangeSource(null); setQualitySource(null); setPlanningSource(null); setMode(meetingId ? "note" : "project_query"); setSelectedFiles([]); })}>{sessions.map(s => <option key={s.id} value={s.id}>{new Date(s.time).toLocaleString("zh-CN")}{s.archived ? " · 已归档" : ""}</option>)}</select>}{data && <a className="text-xs text-primary underline" href={`/ask?project=${projectId}${meetingId ? `&meeting=${meetingId}` : ""}&conversation=${data.id}${workFocus ? `&focus_kind=${workFocus.kind}&focus_id=${workFocus.id}` : ""}`}>在完整会话页继续</a>}</div></details>
      {workFocus && <div className="space-y-2">
        {focusSource ? <WorkFocusSummary value={focusSource}/> : <p className="text-sm">正在读取工作对象；读取成功后才能保存本条消息。</p>}
        <div className="flex gap-2"><Button size="sm" variant="outline" disabled={draftBusy} onClick={() => void act(() => readWorkFocus())}>重新读取当前对象</Button><Button size="sm" variant="ghost" disabled={draftBusy || !!body.trim()} onClick={() => { setWorkFocus(undefined); setFocusSource(null); }}>清除对象范围</Button></div>
      </div>}
      {data?.archived && <p className="text-xs">此会话已归档，历史与业务回执保留。</p>}
      {data?.next && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(data.id, true))}>查看更早消息</Button>}
      {assistant && !data?.items.length && <div className="py-10"><p className="text-lg font-medium">一起处理眼前的工作</p><p className="mt-2 text-sm leading-6 text-muted-foreground">直接告诉我你的目标。我已带入当前项目{workFocus ? "和工作对象" : ""}，会按你的权限查证。</p></div>}
      <div className="space-y-4" aria-live="polite">{data?.items.map(message => { const result = isRecord(message.receipt.result) ? message.receipt.result : null; const findingIds = message.action === "meeting_planning" ? [] : [typeof message.receipt.finding_id === "string" ? message.receipt.finding_id : null, ...(Array.isArray(message.receipt.finding_ids) ? message.receipt.finding_ids.filter((v): v is string => typeof v === "string") : [])].filter((v): v is string => !!v); return <article key={message.id} className={assistant ? "space-y-3 border-b pb-5" : "space-y-3 rounded-lg border p-3"}><p className="text-xs text-muted-foreground">{new Date(message.time).toLocaleString("zh-CN")} · {modes[message.action]}</p><p className="whitespace-pre-wrap text-sm">{message.body}</p><p className="text-xs">{({ pending: "消息已保存，尚待运行", saved: "补充说明已保存", queued: "等待查证", running: "正在办理", succeeded: "本次整理已完成", degraded: "本次运行未完成", failed: "本次运行失败", cancelled: "本次运行已停止" } as Record<string, string>)[String(message.receipt.status)] ?? String(message.receipt.status)}</p>{message.receipt.current === false && <p className="text-xs text-destructive">此运行来源已变化，请重新核对。</p>}
        {message.objectFocus && <><WorkFocusSummary value={message.objectFocus} historical/>{message.objectFocus.available !== false && <Button size="sm" variant="outline" disabled={draftBusy || hasDraft} onClick={() => void act(async () => { const target = parseWorkFocus(String(message.objectFocus?.kind), String(message.objectFocus?.id)); if (!target) throw new Error("原对象范围不完整"); setWorkFocus(target); setMode("project_query"); await readWorkFocus(target); })}>读取此对象当前资料继续问</Button>}</>}
        {message.qualitySource && <p className="text-xs">本条使用原 NCR 与 {String(message.qualitySource.selection_count)} 项选定证据。<a className="ml-2 text-primary underline" href={`/projects?project=${projectId}&tab=quality&ncr=${String(message.qualitySource.ncr_id)}`}>打开原质量记录</a></p>}
        {typeof message.receipt.run_id === "string" && message.action === "quality_work_package" && <AgentRunProgressPanel projectId={projectId} runId={message.receipt.run_id}/>}
        {message.changeSource && <p className="text-xs">本条使用 {String(message.changeSource.depth)} 层原变更资料{message.changeSource.include_supplier_notices === true ? "，包含厂商通告及人审核对" : ""}{message.changeSource.allow_discussion === true ? "，已允许专业讨论及后续分析" : ""}。<a className="ml-2 text-primary underline" href={`/projects?project=${projectId}&tab=engineering&change_ecr_id=${String(message.changeSource.ecr_id)}#ecr-${String(message.changeSource.ecr_id)}`}>打开原工程变更</a></p>}
        {message.changeSource && <ChangeDiscussionContinuation projectId={projectId} ecrId={String(message.changeSource.ecr_id)} sourceDigest={String(message.changeSource.source_digest)} value={message.receipt} disabled={busy || data.archived} onRefresh={() => load(data.id)}/>}
        {message.receipt.source_unavailable === true && <p className="text-xs">原通告读取权限或来源已失效，原分析内容暂不可展示；历史请求仍保留。</p>}
        {["change_work_package", "quality_work_package"].includes(message.action) && message.receipt.disposition === "insufficient_evidence" && <p className="text-xs">资料不足，尚未形成待审建议。</p>}
        {["change_work_package", "quality_work_package"].includes(message.action) && <ChangeToolReceipts value={message.receipt.tool_receipts}/>}
        {["change_work_package", "quality_work_package"].includes(message.action) && Array.isArray(message.receipt.missing) && message.receipt.missing.length > 0 && <ul className="list-disc pl-4 text-xs">{message.receipt.missing.map((item, i)=><li key={i}>{String(item)}</li>)}</ul>}
        {result && typeof result.answer === "string" && <p className="whitespace-pre-wrap text-sm">{result.answer}</p>}{result && Array.isArray(result.citations) && <ul className="space-y-1 text-xs">{result.citations.filter(isRecord).map((citation, i) => <li key={i}>{typeof citation.href === "string" && (citation.href.startsWith("/projects?") || citation.href.startsWith("/ask?")) ? <a className="text-primary underline" href={citation.href}>{String(citation.label ?? "核对来源")}</a> : <span>{String(citation.label ?? "来源")}</span>}</li>)}</ul>}
        {result && Array.isArray(result.claims) && result.claims.filter(isRecord).map((claim, i) => <div key={i} className="space-y-1 text-sm"><p>{String(claim.text ?? "")}</p>{Array.isArray(claim.citations) && claim.citations.filter(isRecord).map((q, j) => <blockquote key={j} className="whitespace-pre-wrap border-l-2 pl-3 text-xs">{String(q.exact_quote ?? "")}</blockquote>)}</div>)}
        {result && Array.isArray(result.open_questions) && <ul className="list-disc pl-4 text-xs">{result.open_questions.map((q, i) => <li key={i}>{String(q)}</li>)}</ul>}
        {(message.receipt.status !== "cancelled" && (message.receipt.error_code || result?.status === "unavailable")) && <p className="text-xs text-destructive">当前模型、来源或运行条件不满足；请刷新回执或补充新消息后继续。</p>}
        {typeof message.receipt.run_id === "string" && ["queued", "running"].includes(String(message.receipt.status)) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await cancelAgentRun(String(message.receipt.run_id)); await load(data.id); })}>停止本次运行</Button>}
        {message.attachmentIds.length > 0 && <div className="space-y-2"><p className="text-xs font-medium">本条消息的附件</p>{message.attachmentIds.map(id => <AttachmentDetail key={id} conversationId={data.id} attachmentId={id} />)}{!data.archived && <Button size="sm" variant="outline" disabled={draftBusy || hasDraft} onClick={() => void act(async () => { const rows = await Promise.all(message.attachmentIds.map(id => attachmentRequest(`/api/conversations/${data.id}/attachments/${id}`))); setSelectedFiles(rows.map(parseAttachment)); })}>在下一条消息继续使用这些附件</Button>}</div>}
        {message.attachmentIds.length > 0 && <ConversationReportImports projectId={projectId} conversationId={data.id} messageId={message.id} attachmentIds={message.attachmentIds} archived={data.archived} />}
        {message.attachmentIds.length > 0 && <ConversationIntakeAi conversationId={data.id} messageId={message.id} archived={data.archived} />}
        {message.attachmentIds.length > 0 && <ConversationIssueIntake conversationId={data.id} messageId={message.id} archived={data.archived} />}
        {message.attachmentIds.length > 0 && <ConversationDecisionIntake conversationId={data.id} messageId={message.id} archived={data.archived} />}
        {message.attachmentIds.length > 0 && <ConversationPdfIntake conversationId={data.id} messageId={message.id} archived={data.archived} />}
        {message.attachmentIds.length > 0 && <ConversationPdfIntake sourceKind="email" conversationId={data.id} messageId={message.id} archived={data.archived} />}
        {findingIds.length > 0 && message.receipt.convened_discussion != null && <p className="text-sm font-medium">讨论前的原分析候选</p>}
        {message.meetingPlanningSource && <ConversationMeetingPlanResult projectId={projectId} source={message.meetingPlanningSource} receipt={message.receipt}/>}
        {<ConversationFindingGroup findingIds={findingIds}/>}
        {(!shared || message.authorUserId === actingUserId) && !["note"].includes(message.action) && (["pending", "degraded", "failed"].includes(String(message.receipt.status)) || message.receipt.status === "running" && message.action === "quality_work_package") && !data.archived && <Button size="sm" variant="outline" disabled={draftBusy || message.objectFocus?.current === false} onClick={() => void act(() => runMessage(data.id, message.id))}>查询或继续原请求</Button>}
      </article>; })}</div>
      {operationBusy && <p role="status" className="text-xs">正在办理，仍可刷新会话查看进度或停止本次运行。</p>}
      {operations && <Button size="sm" variant="outline" disabled={busy} onClick={() => data && void act(() => load(data.id))}>查看最新运行结果</Button>}
      {meetingId && <><MeetingTranscripts projectId={projectId} meetingId={meetingId} canUpload={canUpload && !data?.archived} isActive={!data?.archived} /><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await loadSources(); if (source) await chooseSource(source.id); })}>刷新转写与当前版本</Button><select aria-label="本次使用的转写" disabled={busy} className="rounded-md border bg-background p-2 text-xs" value={source?.id ?? ""} onChange={e => void act(() => chooseSource(e.target.value))}><option value="">选择已核对的转写</option>{transcripts.map(t => <option key={t.id} value={t.id}>{new Date(t.time).toLocaleString("zh-CN")}</option>)}</select></div></>}
      {!workFocus && <details open={(!shared && !assistant) || selectedFiles.length > 0 || !!initialAttachmentId}><summary className="cursor-pointer text-sm text-muted-foreground">{shared ? "添加资料（项目成员可见）" : "本条消息的附件"}</summary><ConversationFiles shared={data ? data.visibility === "project" : shared} conversationId={data?.id} ensureConversation={create} selected={selectedFiles} onSelectionChange={setSelectedFiles} onBusyChange={setFilesBusy} disabled={draftBusy || !!data?.archived} initialAttachmentId={initialAttachmentId} initialFragment={initialFragment} /></details>}
      {!data?.archived && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(() => send()); }}>{!shared && !assistant && <label className="block text-xs">本次办理<select className="ml-2 rounded-md border bg-background p-2" value={mode} disabled={draftBusy || planningDirty} onChange={e => { setMode(e.target.value); setPlanningDirty(false); setChangeSource(null); setQualitySource(null); setPlanningSource(null); }}>{Object.entries(modes).filter(([key]) => shared ? ["note", "project_query"].includes(key) : workFocus ? ["note", "project_query"].includes(key) : meetingId ? key !== "meeting_planning" : ["note", "project_query", "change_work_package", "quality_work_package", "meeting_planning"].includes(key)).map(([key, label]) => <option key={key} value={key}>{workFocus && key === "project_query" ? "询问所选工作对象" : label}</option>)}</select></label>}{mode === "meeting_planning" && <fieldset disabled={draftBusy}><MeetingPlanning projectId={projectId} showRuns={false} initialQuestion={body} onSelected={setPlanningSource} onDraftDirtyChange={setPlanningDirty}/>{planningSource && <p className="text-xs">本条起草请求：{planningSource.label}</p>}<p className="text-xs text-muted-foreground">完整问题和产出在上方要求中编辑、预览并保存；历史消息与本条附件不加入模型资料。补充新要求请修订资料后重新选择。原说明草稿保留在其他办理方式中。</p></fieldset>}{mode === "quality_work_package" && <ConversationQualitySource projectId={projectId} disabled={draftBusy} onChange={setQualitySource}/>} {mode === "change_work_package" && <ConversationChangeSource projectId={projectId} disabled={draftBusy} onChange={setChangeSource}/>}{mode !== "meeting_planning" && <textarea aria-label="会话消息" className="min-h-24 w-full rounded-lg border bg-background p-3 text-sm" maxLength={2000} value={body} disabled={draftBusy} onChange={e => setBody(e.target.value)} placeholder={assistant ? "和小Pai说说你想做什么…" : "说明本次目标，或补充、纠正上一轮信息…"} />}<Button disabled={draftBusy || (mode !== "meeting_planning" && !body.trim()) || !available}>{draftBusy ? "正在保存或办理…" : (shared || assistant) ? "发送" : "保存并继续"}</Button>{shared && <Button type="button" variant="ghost" disabled={draftBusy || !body.trim()} onClick={() => void act(() => send("note"))}>仅保存为项目说明</Button>}{!available && <p className="text-xs text-muted-foreground">{workFocus ? "请先读取当前对象资料；对象问答只使用本次选定字段。" : mode === "meeting_planning" ? "请选择已核对的最新会议要求并移出本条附件；AI 能力通过阶段评测后才能发起，要求仍可先保存。" : mode === "quality_work_package" ? "请先选择原 NCR 并核对资料；能力通过阶段评测且有办理权限后才能生成。品质准备使用原质量证据，请移出本条私人附件。" : mode === "change_work_package" ? "工程建议须先核对原变更资料，能力通过阶段评测且具有办理权限后才能生成；本项使用原业务来源，请移出本条附件。未开放时可先保存补充说明。" : "所选附件须抽取完成且为内部资料才能问答；会议候选使用已核对转写且能力已就绪。未满足时可先保存补充说明，或调整本条附件选择。"}</p>}</form>}
      {data && (!shared || data.creatorId === actingUserId) && <Button size="sm" variant="ghost" disabled={draftBusy || hasDraft} onClick={() => void act(async () => { await request(`/api/conversations/${data.id}/archive`, { archived: !data.archived }); await load(data.id); })}>{data.archived ? "恢复会话" : "归档此会话"}</Button>}
      {notice && <p role="status" className="text-xs">{notice}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </Root>;
}
