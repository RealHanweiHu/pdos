"use client";

import { useRef, useState } from "react";
import { ProjectSourceActualCorrections } from "./project-source-actual-corrections";
import { ProjectCertificationExecution } from "./project-certification-execution";
import { ProjectScheduleMilestones } from "./project-schedule-milestones";
import { ProjectCrossDependencies } from "./project-cross-dependencies";
import { ProjectScheduleScenarios } from "./project-schedule-scenarios";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

export const nodeKinds: Record<string, string> = { task: "任务", gate: "阶段评审", build: "试制批次", test_run: "测试轮次", certification: "认证", tooling: "工装轮次", milestone: "独立里程碑" };
const sourceStates: Record<string, string> = { todo: "未开始", in_progress: "进行中", blocked: "受阻", done: "已完成", skipped: "已跳过", pending_approval: "待批准", preparing: "准备中", reviewing: "评审中", approved: "已批准", conditional: "有条件通过", hold: "暂缓", rejected: "未通过", planned: "已计划", completed: "已完成", cancelled: "已取消", passed: "通过", failed: "失败", aborted: "已中止", draft: "草稿", valid: "有效", expired: "已过期", revoked: "已撤销", checkpoint: "完成检查点" };
type Observation = { actual_correction?: { version: number }; correction_conflict?: string; id: string; node_id: string; version: number; source_status: string; started_at: string | null; finished_at: string | null; successful: boolean | null; note: string | null; audit_row_id: number; event_row_id: number | null; observed_at: string };
type Node = { actual: Observation | null; id: string; node_kind: string; title: string; source_status: string; source_id: string | null; calendar_version_id: string; completion_criteria: string | null; reservable: boolean };
type Source = { id: string; node_kind: string; title: string; status: string; source_digest: string };
type Calendar = { id: string; name: string; version: number; definition: { calendar: { timezone: string } } };
type State = { actual_history: Observation[]; has_more_actual_history: boolean; items: Node[]; sources: Source[]; calendars: Calendar[]; can_register: boolean; truncated_source_kinds: string[] };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function ProjectScheduleNodes({ projectId, onRegistered }: { projectId: string; onRegistered: () => void }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<State | null>(null);
  const [kind, setKind] = useState("gate"); const [sourceId, setSourceId] = useState(""); const [calendar, setCalendar] = useState("");
  const [title, setTitle] = useState(""); const [criteria, setCriteria] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null); const requests = useRef(new Map<string, string>());
  const path = `projects/${projectId}/execution/nodes`;
  async function refresh() {
    setBusy(true); setError(null);
    try { setData(await caseLinkRequest<State>(path)); setSourceId(""); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "排程节点读取失败"); }
    finally { setBusy(false); }
  }
  async function register() {
    const source = data?.sources.find((item) => item.node_kind === kind && item.id === sourceId);
    if (busy || (kind !== "milestone" && !source)) return;
    const body = { node_kind: kind, calendar_version_id: calendar, ...(kind === "milestone" ? { title, completion_criteria: criteria } : { source_id: source!.id, expected_source_digest: source!.source_digest }) };
    const key = JSON.stringify({ projectId, body }); let requestId = requests.current.get(key);
    if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    setBusy(true); setError(null); setNotice(null);
    try {
      await caseLinkRequest(path, { ...body, request_id: requestId });
      setNotice("节点已登记，日历版本已固定。可执行的业务节点现在可用于资源预约。");
      setData(await caseLinkRequest<State>(path)); setSourceId(""); setTitle(""); setCriteria(""); onRegistered();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "节点登记未完成"); }
    finally { setBusy(false); }
  }
  return <div className="space-y-3 rounded-md border p-3">
    <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起排程对象" : "管理任务、评审、试制、测试、认证与工装节点"}</Button>
    {open && <>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <p className="text-xs text-muted-foreground">选择项目中的真实业务对象并固定执行日历。每个对象只有一个节点，业务状态在原入口办理。节点登记后还需纳入获批计划，才会形成基线和承诺。</p>
      {data?.can_register && <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); void register(); }}>
        <label className="block text-sm">对象类型<select className={field} value={kind} disabled={busy} onChange={(event) => { setKind(event.target.value); setSourceId(""); }}>{Object.entries(nodeKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {kind === "milestone" ? <><label className="block text-sm">里程碑名称<input className={field} required disabled={busy} maxLength={2048} value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="block text-sm">完成判据<textarea className={field} required disabled={busy} maxLength={2048} value={criteria} onChange={(event) => setCriteria(event.target.value)} /></label><p className="text-xs text-muted-foreground">里程碑作为独立完成检查点，不直接占用资源。</p></> : <label className="block text-sm">实际业务对象<select className={field} required disabled={busy} value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">选择尚未登记的对象</option>{data.sources.filter((item) => item.node_kind === kind).map((item) => <option key={item.id} value={item.id}>{item.title} · {sourceStates[item.status] ?? item.status}</option>)}</select></label>}
        <label className="block text-sm">执行日历版本<select className={field} required disabled={busy} value={calendar} onChange={(event) => setCalendar(event.target.value)}><option value="">选择已发布日历</option>{data.calendars.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version} · {item.definition.calendar.timezone}</option>)}</select></label>
        {!data.calendars.length && <p className="text-xs">请先在计划日历入口发布日历版本。</p>}
        <Button size="sm" disabled={busy || !calendar || (kind === "milestone" ? !title.trim() || !criteria.trim() : !sourceId)}>登记排程节点</Button>
      </form>}
      {data?.items.map((item) => <article className="space-y-1 border-t pt-2 text-xs" key={item.id}><p className="font-medium">{nodeKinds[item.node_kind]} · {item.title}</p><p>来源状态：{sourceStates[item.source_status] ?? item.source_status} · 日历：{data.calendars.find((entry) => entry.id === item.calendar_version_id)?.name ?? "固定版本"} v{data.calendars.find((entry) => entry.id === item.calendar_version_id)?.version ?? "—"}</p>{item.completion_criteria && <p>完成判据：{item.completion_criteria}</p>}{item.actual && <div className="space-y-1">{item.actual.actual_correction && <p>当前时间采用更正 v{item.actual.actual_correction.version}</p>}{item.actual.correction_conflict && <p className="text-destructive">{item.actual.correction_conflict}</p>}<p>实际开工：{item.actual.started_at ? new Date(item.actual.started_at).toLocaleString() : "未知"} · 实际结束：{item.actual.finished_at ? new Date(item.actual.finished_at).toLocaleString() : "未知"}</p><p>业务结果：{item.actual.successful === true ? "已成功完成 / 有效" : item.actual.successful === false ? "未成功完成 / 已失效" : "尚未形成结论"}</p>{item.actual.note && <p className="text-muted-foreground">{item.actual.note}</p>}<details><summary className="cursor-pointer">实际办理依据与历史</summary>{data.actual_history.filter((entry) => entry.node_id === item.id).map((entry) => <div className="my-2 border-l pl-2" key={entry.id}><p>观察 v{entry.version} · {sourceStates[entry.source_status] ?? entry.source_status} · 记录于 {new Date(entry.observed_at).toLocaleString()}</p><p>开工 {entry.started_at ? new Date(entry.started_at).toLocaleString() : "未知"} / 结束 {entry.finished_at ? new Date(entry.finished_at).toLocaleString() : "未知"}</p><p>审计 #{entry.audit_row_id}{entry.event_row_id && <> · <a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${entry.event_row_id}`}>来源事件</a></>}</p>{entry.note && <p>{entry.note}</p>}</div>)}</details></div>}</article>)}
      {data?.has_more_actual_history && <p className="text-xs text-muted-foreground">显示最近 500 条实际观察，更早依据保留在审计记录中。</p>}
      {!!data?.truncated_source_kinds.length && <p className="text-xs text-muted-foreground">各类来源最多列出最近 1000 项；更多历史记录保留在原业务入口。</p>}
      <ProjectSourceActualCorrections projectId={projectId} onChanged={() => { void refresh(); onRegistered(); }} />
      <ProjectCertificationExecution projectId={projectId} onChanged={() => { void refresh(); onRegistered(); }} />
      <ProjectScheduleMilestones projectId={projectId} onCompleted={() => { void refresh(); onRegistered(); }} />
      <ProjectScheduleScenarios projectId={projectId} />
      <ProjectCrossDependencies projectId={projectId} />
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新排程对象</Button>
    </>}
  </div>;
}
