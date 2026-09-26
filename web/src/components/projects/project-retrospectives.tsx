"use client";

import { ProjectConversation } from "@/components/ai/project-conversation";

import { useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { MeetingPlanning } from "./meeting-planning";
import { MeetingPlanningOrigin } from "./meeting-planning-origin";
import { MeetingNotifications } from "./meeting-notifications";
import { MeetingConferenceRequests } from "./meeting-conference-requests";
import { MeetingRescheduling } from "./meeting-rescheduling";
import { MeetingPreparation } from "./meeting-preparation";
import { MeetingFollowup } from "./meeting-followup";
import { MeetingTranscripts } from "./meeting-transcripts";
import { MeetingMinutes } from "./meeting-minutes";
import { isRecord, responseBody } from "@/components/workspace-api";
import { SourcePicker, type SourceSelection } from "@/components/knowledge/source-picker";

const inputClass = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const meetingTypes: Record<string,string> = {weekly:"周会",material:"物料会",special:"专项会",technical_review:"技术评审",decision_checkpoint:"决策检查点",pilot_review:"试制复盘",project_retrospective:"项目复盘"};
const states = { scheduled: "已排程", in_progress: "进行中", completed: "已结束", cancelled: "已取消" };
function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("复盘记录不完整，请刷新核对");
  return value;
}
function id(value: unknown): string {
  const result = text(value);
  if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("复盘来源不完整");
  return result;
}
function version(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("复盘版本不完整");
  return value;
}
function refs(value: unknown) {
  if (!Array.isArray(value)) throw new Error("复盘依据不完整");
  return value.map(item => {
    if (!isRecord(item) || !["document", "specification", "evidence_snapshot"].includes(String(item.kind))) throw new Error("复盘依据不完整");
    return { kind: item.kind as SourceSelection["kind"], id: id(item.reference), title: text(item.title),
      expected_version: typeof item.version === "number" ? String(item.version) : text(item.digest) };
  });
}
function meeting(value: unknown) {
  if (!isRecord(value) || typeof value.status !== "string" || !Object.hasOwn(states, value.status)) throw new Error("会议记录不完整");
  if (typeof value.meeting_type !== "string" || !Object.hasOwn(meetingTypes,value.meeting_type)) throw new Error("会议类型不完整");
  return { kind:value.meeting_type, id: id(value.id), title: text(value.title), status: value.status as keyof typeof states,
    start: text(value.scheduled_start_at), end: text(value.scheduled_end_at),
    externalProvider: value.external_provider === null ? null : text(value.external_provider),
    archived: value.archived_at !== null, version: version(value.retrospective_version),
    conclusion: value.retrospective_conclusion === null ? "" : text(value.retrospective_conclusion),
    applicability: value.retrospective_applicability === null ? "" : text(value.retrospective_applicability),
    refs: refs(value.retrospective_source_refs) };
}
type Meeting = ReturnType<typeof meeting>;
function historyRecord(value: unknown) {
  if (!isRecord(value) || !isRecord(value.after_snapshot) || !isRecord(value.context)) throw new Error("复盘历史不完整");
  return { version: version(value.after_snapshot.retrospective_version), conclusion: text(value.after_snapshot.retrospective_conclusion),
    applicability: text(value.after_snapshot.retrospective_applicability), refs: refs(value.after_snapshot.retrospective_source_refs),
    reason: text(value.context.reason), name: text(value.confirmed_by), time: text(value.timestamp) };
}
type History = ReturnType<typeof historyRecord>;
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string"
    ? value.detail.message : "复盘办理暂不可用，请刷新核对处理结果");
  return value;
}
function time(value: string) { return new Date(value).toLocaleString("zh-CN"); }

function MeetingCard({ item, projectId, canManage, canUpload, refresh }: { item: Meeting; projectId: string; canManage: boolean; canUpload: boolean; refresh: () => Promise<void> }) {
  const [draft, setDraft] = useState<{ expected: number; conclusion: string; applicability: string; sources: SourceSelection[]; reason: string } | null>(null);
  const [history, setHistory] = useState<History[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const submitted = useRef<{ signature: string; id: string } | null>(null);
  const path = `/api/projects/${encodeURIComponent(projectId)}/meetings/${encodeURIComponent(item.id)}`;
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null); setNotice(null);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "办理未完成"); }
    finally { setBusy(false); }
  }
  async function status(next: string) {
    await request(`${path}/status`, { status: next, cancelled_reason: next === "cancelled" ? cancelReason : null });
    await refresh();
  }
  async function loadHistory() {
    const result = await request(`${path}/retrospective`);
    if (!isRecord(result) || !Array.isArray(result.items)) throw new Error("复盘历史不完整");
    setHistory(result.items.map(historyRecord));
  }
  async function confirm() {
    if (!draft) return;
    const body = { expected_version: draft.expected, conclusion: draft.conclusion, applicability: draft.applicability,
      reason: draft.reason, sources: draft.sources.map(({ kind, id, expected_version }) => ({ kind, id, expected_version })) };
    const signature = JSON.stringify(body);
    if (submitted.current?.signature !== signature) submitted.current = { signature, id: crypto.randomUUID() };
    const result = await request(`${path}/retrospective`, { ...body, request_id: submitted.current.id });
    if (!isRecord(result)) throw new Error("确认回执不完整，请刷新核对");
    const confirmed = version(result.confirmed_version);
    setDraft(null); setHistory(null); setNotice(`第 ${confirmed} 版结论已确认，经验整理记录已生成，知识仍需独立审核。`);
    await refresh();
  }
  return <article id={`retrospective-${item.id}`} className="space-y-3 rounded-lg border p-4">
    <div className="flex flex-wrap justify-between gap-2"><h3 className="font-medium">{item.title}</h3><span className="text-sm">{states[item.status]}{item.archived ? " · 已归档" : ""}</span></div>
    <p className="text-xs text-muted-foreground">{meetingTypes[item.kind]} · 计划时间：{time(item.start)} — {time(item.end)}</p>
    {item.version > 0 ? <div className="space-y-2 rounded-lg bg-muted/40 p-3"><p className="text-sm font-medium">当前已确认结论 · 第 {item.version} 版</p><p className="whitespace-pre-wrap text-sm">{item.conclusion}</p><p className="whitespace-pre-wrap text-sm">适用条件：{item.applicability}</p><ul className="space-y-1 text-xs">{item.refs.map(ref => <li key={`${ref.kind}:${ref.id}`}>{ref.title} · {ref.expected_version}</li>)}</ul>{item.refs.length === 0 && <p className="text-xs text-muted-foreground">未登记外部版本依据，知识审核时需核对。</p>}</div>
      : item.kind === "project_retrospective" ? <p className="text-sm text-muted-foreground">尚无已确认的复盘结论。</p> : null}
    {item.externalProvider && <p className="text-xs text-muted-foreground">已绑定 {item.externalProvider}，请在下方核对当前时间或取消是否已同步到外部会议。</p>}
    <MeetingRescheduling projectId={projectId} meetingId={item.id} onChanged={refresh}/>
    <MeetingConferenceRequests projectId={projectId} meetingId={item.id} onChanged={refresh}/>
    <MeetingPlanningOrigin projectId={projectId} meetingId={item.id}/>
    <MeetingNotifications projectId={projectId} meetingId={item.id}/>
    <MeetingFollowup projectId={projectId} meetingId={item.id} canManage={canManage && !busy} isAvailable={!item.archived && ["in_progress", "completed"].includes(item.status)} />
    <ProjectConversation projectId={projectId} meetingId={item.id} />
    <MeetingTranscripts projectId={projectId} meetingId={item.id} canUpload={canUpload && !busy} isActive={!item.archived} />
    <MeetingMinutes projectId={projectId} meetingId={item.id} canManage={canManage && !busy} isCompleted={!item.archived && item.status === "completed"} />
    <MeetingPreparation projectId={projectId} meetingId={item.id} canManage={canManage && !busy} isActive={!item.archived && ["scheduled", "in_progress"].includes(item.status)} onChanged={refresh} />
    {canManage && !item.archived && ["scheduled", "in_progress"].includes(item.status) && <div className="space-y-2"><div className="flex flex-wrap gap-2">
      {item.status === "scheduled" && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => status("in_progress"))}>记录会议开始</Button>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => status("completed"))}>记录会议已结束</Button>
    </div><label className="block text-xs">取消理由（仅取消时填写）<input maxLength={512} className={inputClass} value={cancelReason} onChange={event => setCancelReason(event.target.value)} /></label><Button size="sm" variant="outline" disabled={busy || !cancelReason.trim()} onClick={() => void act(() => status("cancelled"))}>取消会议</Button></div>}
    <div className="flex flex-wrap gap-2">
      {canManage && item.kind === "project_retrospective" && item.status === "completed" && !item.archived && !draft && <Button size="sm" disabled={busy} onClick={() => setDraft({ expected: item.version, conclusion: item.conclusion, applicability: item.applicability, sources: item.refs, reason: "" })}>{item.version ? "修订复盘结论" : "填写并确认复盘结论"}</Button>}
      {item.kind === "project_retrospective" && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(loadHistory)}>查看确认历史</Button>}
      {item.version > 0 && <a className="self-center text-sm text-primary underline" href={`/knowledge?project=${projectId}`}>查看经验整理与待审草稿</a>}
    </div>
    {draft && <form className="space-y-3 rounded-lg border p-3" onSubmit={event => { event.preventDefault(); void act(confirm); }}>
      <p className="text-xs text-muted-foreground">基于第 {draft.expected} 版修订。请记录实际判断及其范围；确认后生成新版本，旧版本保留历史，旧版派生经验暂停复用。</p>
      <label className="block text-sm">复盘结论<textarea required maxLength={15000} className={`${inputClass} min-h-36`} value={draft.conclusion} onChange={event => setDraft({ ...draft, conclusion: event.target.value })} /></label>
      <label className="block text-sm">适用条件与限制<textarea required maxLength={3000} className={inputClass} value={draft.applicability} onChange={event => setDraft({ ...draft, applicability: event.target.value })} /></label>
      <SourcePicker projectId={projectId} value={draft.sources} onChange={sources => setDraft({ ...draft, sources })} />
      <label className="block text-sm">确认或修订理由<textarea required maxLength={3000} className={inputClass} value={draft.reason} onChange={event => setDraft({ ...draft, reason: event.target.value })} /></label>
      <div className="flex gap-2"><Button size="sm" disabled={busy || !draft.conclusion.trim() || !draft.applicability.trim() || !draft.reason.trim()}>确认本版结论</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setDraft(null)}>取消编辑</Button></div>
    </form>}
    {history && <div className="space-y-2"><p className="text-xs text-muted-foreground">最近 100 个确认版本；历史结论不代表当前依据。</p>{history.length === 0 && <p className="text-sm">尚无确认历史。</p>}{history.map(record => <details key={record.version} className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">第 {record.version} 版 · {record.name} · {time(record.time)}</summary><p className="mt-2 whitespace-pre-wrap text-sm">{record.conclusion}</p><p className="mt-2 whitespace-pre-wrap text-sm">适用条件：{record.applicability}</p><p className="mt-2 whitespace-pre-wrap text-sm">确认理由：{record.reason}</p><ul className="mt-2 text-xs">{record.refs.map(ref => <li key={`${ref.kind}:${ref.id}`}>{ref.title} · {ref.expected_version}</li>)}</ul></details>)}</div>}
    {notice && <p role="status" className="text-sm">{notice}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </article>;
}

function subscribeMeetingLocation(update: () => void) {
  window.addEventListener("popstate",update);
  return () => window.removeEventListener("popstate",update);
}
function currentMeetingFocus() {
  const wanted=new URLSearchParams(window.location.search).get("meeting");
  return wanted && /^[0-9a-f-]{36}$/.test(wanted) ? wanted : null;
}

export function ProjectMeetings({ projectId, canManage, canUpload }: { projectId: string; canManage: boolean; canUpload: boolean }) {
  const focus=useSyncExternalStore(subscribeMeetingLocation,currentMeetingFocus,() => null);
  const [expanded,setExpanded]=useState<boolean|null>(null);
  const opened=expanded ?? Boolean(focus);
  const [items, setItems] = useState<Meeting[] | null>(null);
  const [kind,setKind] = useState("weekly");
  const [organizer,setOrganizer] = useState("");
  const [members,setMembers] = useState<{id:string;display_name:string}[]>([]);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const path = `/api/projects/${encodeURIComponent(projectId)}/meetings`;
  async function load() {
    const result = await request(path);
    if (!isRecord(result) || !Array.isArray(result.items)) throw new Error("复盘清单不完整");
    setItems(result.items.map(meeting));
    if(canManage) {
      const options = await request(`${path}/preparation/options`);
      if(!isRecord(options) || !Array.isArray(options.members)) throw new Error("会议成员选项不完整");
      setMembers(options.members.map(member => {if(!isRecord(member)) throw new Error("成员不完整");return {id:id(member.id),display_name:text(member.display_name)};}));
    }
  }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "复盘暂不可用"); }
    finally { setBusy(false); }
  }
  async function create() {
    if (new Date(end) <= new Date(start)) throw new Error("结束时间必须晚于开始时间");
    await request(path, { meeting_type: kind, organizer_user_id:organizer, title, scheduled_start_at: new Date(start).toISOString(), scheduled_end_at: new Date(end).toISOString() });
    setCreating(false); setTitle(""); setStart(""); setEnd(""); await load();
  }
  return <details open={opened} className="mt-6 rounded-lg border p-4" onToggle={event => { setExpanded(event.currentTarget.open); if (event.currentTarget.open && !items && !busy) void act(load); }}>
    <summary className="cursor-pointer font-semibold">会议准备与复盘</summary>
    <div className="mt-4 space-y-4"><p className="text-sm text-muted-foreground">登记会议、准备议程与参会名单，按实际情况记录开始和结束。项目复盘可继续确认结论并形成待审经验。</p>
      <div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新会议清单</Button>{canManage && <Button size="sm" disabled={busy} onClick={() => setCreating(!creating)}>登记会议</Button>}</div>
      {canManage && <MeetingPlanning projectId={projectId}/>}
      {creating && <form className="space-y-3 rounded-lg border p-3" onSubmit={event => { event.preventDefault(); void act(create); }}>
        <label className="block text-sm">会议类型<select className={inputClass} value={kind} onChange={event => setKind(event.target.value)}>{Object.entries(meetingTypes).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="block text-sm">组织者<select required className={inputClass} value={organizer} onChange={event => setOrganizer(event.target.value)}><option value="">选择当前项目成员</option>{members.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
        <label className="block text-sm">会议主题<input required maxLength={256} className={inputClass} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm">计划开始（本地时间）<input required type="datetime-local" className={inputClass} value={start} onChange={event => setStart(event.target.value)} /></label><label className="block text-sm">计划结束（本地时间）<input required type="datetime-local" className={inputClass} value={end} onChange={event => setEnd(event.target.value)} /></label></div>
        <Button size="sm" disabled={busy || !title.trim() || !start || !end || !organizer}>保存会议安排</Button>
      </form>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{busy && <p className="text-sm">正在办理…</p>}
      {items?.length === 0 && <p className="text-sm text-muted-foreground">当前没有已登记的会议。</p>}
      {items && [...items].sort((a,b)=>Number(b.id===focus)-Number(a.id===focus)).map(item => <MeetingCard key={item.id} item={item} projectId={projectId} canManage={canManage} canUpload={canUpload} refresh={load} />)}
    </div>
  </details>;
}
