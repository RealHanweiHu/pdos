"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CalendarBlank, CheckCircle, Plus, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { blankProjectDraft, buildSchedule, disciplineNames, durationText, forecastReasonNames, forecastWarningNames, utcText, weekdayNames, type ApplyPlanPayload, type PlanForecast, type PlanProposal, type PreparedProject, type Project, type ProjectApi, type ProjectCommand, type ProjectDraft, type ProjectList, type ProposePlanPayload, type ScheduleInput, type SourceRead, type TaskDraft, type WaitingProject } from "@/lib/project-plan-view";
import { globalHref } from "@/lib/global-navigation";
import { planningStorageKey, projectCreationMoved, restorePlanningDraft } from "./project-planning-state";

type Props = { product: { id: string; name: string; purpose: string; revision: number }; categoryId?: string; projectId?: string; principalId: string; api: ProjectApi; onSaved: () => void | Promise<void> };
type Receipt = { id: string; subject_type: string; subject_id: string };
type PlanOperation = Exclude<ProjectCommand["operation"], "project.create">;
const receiptTypes: Record<PlanOperation, string> = { "work.plan.propose": "plan_proposal", "work.plan.apply": "plan_revision" };
const successMessages: Record<PlanOperation, string> = {
  "work.plan.propose": "首版计划候选已保存，可以核对预测并确认应用。尚未建立正式任务。",
  "work.plan.apply": "首版计划已应用，工程与 NPI 工作包、任务和依赖已建立。批准基线、个人承诺与实绩仍未记录。",
};

function CalendarSnapshot({ value }: { value: ScheduleInput }) {
  const minuteText = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  return <section className="min-w-0 rounded-lg border border-border p-3 text-sm" aria-label="候选实际工作日历"><h4 className="font-medium">此候选固定的工作日历</h4><dl className="mt-2 space-y-2"><div><dt className="subtle">UTC 起点</dt><dd className="break-words">{utcText(value.start)}</dd></div><div><dt className="subtle">本地日历时区与版本</dt><dd className="break-words">{value.calendar.timezone} · {value.calendar.version}</dd></div><div><dt className="subtle">每周工作日</dt><dd className="break-words">{value.calendar.working_weekdays.map(day => `周${weekdayNames[day]}`).join("、")}</dd></div><div><dt className="subtle">每日工作时段（本地时刻）</dt><dd className="break-words">{value.calendar.intervals.map(interval => `${minuteText(interval.start_minute)}–${minuteText(interval.end_minute)}`).join("；")}</dd></div><div><dt className="subtle">额外休息日期（本地日期）</dt><dd className="break-words">{value.calendar.holidays.join("、") || "未声明额外休息日期"}</dd></div></dl><p className="subtle mt-3">这是本次人工声明的日历，尚未核验为工厂日历。同一项目需调整时段或休息日期时，请明确填写新日历版本。</p></section>;
}

function Forecast({ value }: { value: PlanForecast }) {
  const names = new Map(value.tasks.map(task => [task.key, task.title]));
  return <div className="min-w-0 space-y-4">
    <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm"><p className="font-medium">全部任务预测完成区间</p><p className="mt-1 break-words">{utcText(value.earliest_finish)} ～ {utcText(value.latest_finish)}</p><p className="subtle mt-2 break-words">工作日历：{value.calendar_ref.timezone} · {value.calendar_ref.version}。区间上界来自最高工时估计，不代表承诺日期；未考虑资源预约。</p></div>
    {value.warnings.length > 0 && <ul className="subtle list-inside list-disc">{value.warnings.map(warning => <li key={warning}>{forecastWarningNames[warning] ?? "预测条件需要重核"}</li>)}</ul>}
    <div className="min-w-0 space-y-3">{value.tasks.map(task => <article key={task.key} className="min-w-0 rounded-lg border border-border p-3">
      <p className="break-words font-medium">{task.title}</p><p className="subtle mt-1">{disciplineNames[task.discipline]} · {durationText(task.duration_min_minutes, task.duration_max_minutes)}</p>
      <dl className="mt-3 grid min-w-0 gap-x-3 gap-y-1 text-sm sm:grid-cols-[auto_minmax(0,1fr)]"><dt className="subtle">最低估时下的开始 / 完成</dt><dd className="break-words">{utcText(task.earliest_start)} / {utcText(task.earliest_finish)}</dd><dt className="subtle">最高估时下的开始 / 完成</dt><dd className="break-words">{utcText(task.latest_start)} / {utcText(task.latest_finish)}</dd><dt className="subtle">估计依据</dt><dd className="whitespace-pre-wrap break-words">{task.estimate_source ?? "尚未记录"}</dd><dt className="subtle">前置任务</dt><dd className="break-words">{task.depends_on.map(key => names.get(key) ?? key).join("；") || "无"}</dd></dl>
      {task.unknown_reasons.length > 0 && <p className="mt-3 break-words rounded-lg bg-muted p-2 text-sm">暂不可精确预测：{task.unknown_reasons.map(reason => forecastReasonNames[reason] ?? "预测条件待确认").join("；")}{task.blocked_by.length > 0 ? `。受前置任务影响：${task.blocked_by.map(key => names.get(key) ?? key).join("；")}` : ""}</p>}
    </article>)}</div>
  </div>;
}

function TimelineFacts() {
  return <dl className="grid gap-2 text-sm sm:grid-cols-3"><div><dt className="subtle">批准基线</dt><dd>尚未批准</dd></div><div><dt className="subtle">个人承诺</dt><dd>尚未记录</dd></div><div><dt className="subtle">实绩</dt><dd>尚未记录</dd></div></dl>;
}

export function ProjectPlanning(props: Props) {
  return <ProjectPanel key={`${props.principalId}:${props.product.id}:${props.projectId ?? ""}`} {...props}/>;
}

function ProjectPanel({ product, categoryId = "", projectId = "", principalId, api, onSaved }: Props) {
  const storageKey = planningStorageKey(principalId, product.id, projectId);
  const [draft, setDraft] = useState(() => ({ ...blankProjectDraft(product.purpose), projectId }));
  const [projects, setProjects] = useState<Project[]>([]);
  const [pending, setPending] = useState<WaitingProject | null>(null);
  const [preview, setPreview] = useState<PreparedProject | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [hidden, setHidden] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [rejected, setRejected] = useState(false);
  const alive = useRef(true);
  const lock = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const project = projects.find(item => item.id === draft.projectId);
  const editable = ready && !busy && !pending && !preview;
  const owner = project?.owner_id === principalId;

  const refresh = useCallback(async () => {
    setLoading(true); setProjects([]); setHidden(0); setHasMore(false);
    try {
      const planned = await api<ProjectList>(`v1/products/${product.id}/projects${projectId ? `/${projectId}` : ""}`);
      if (projectId && (planned.items.length !== 1 || planned.items[0].id !== projectId)) throw new Error("当前项目资料未完整取得，请核对范围后刷新。");
      if (!alive.current) return;
      setProjects(planned.items); setHidden(planned.unavailable_count); setHasMore(planned.has_more);
    } catch (failure) { if (alive.current) setProjects([]); throw failure; }
    finally { if (alive.current) setLoading(false); }
  }, [api, product.id, projectId]);

  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => { if (alive.current) return refresh(); }).catch(failure => { if (alive.current) setError(failure.message); });
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        const saved = localStorage.getItem(storageKey);
        const local = restorePlanningDraft(JSON.parse(saved ?? (projectId ? localStorage.getItem(planningStorageKey(principalId, product.id)) : null) ?? "null"), product.id, projectId);
        if (local) {
          setDraft(local.draft); setPending(local.pending);
          if (local.retiredCreation) {
            setNotice(projectCreationMoved);
          }
          if (local.retiredCreation || (projectId && !saved)) localStorage.setItem(storageKey, JSON.stringify({ draft: local.draft, pending: local.pending }));
        }
      } catch { /* Optional local storage does not alter server authority. */ }
      setReady(true);
    });
    return () => { alive.current = false; };
  }, [refresh, storageKey, product.id, projectId, principalId]);
  useEffect(() => { if (preview) dialog.current?.showModal(); }, [preview]);

  function remember(next: ProjectDraft, waiting: WaitingProject | null) {
    try { localStorage.setItem(storageKey, JSON.stringify({ draft: next, pending: waiting })); } catch { /* Online actions remain available. */ }
  }
  function edit(next: ProjectDraft) { setDraft(next); remember(next, pending); }
  function waitFor(value: WaitingProject | null) { setPending(value); remember(draft, value); }
  function closePreview() { dialog.current?.close(); setPreview(null); trigger.current?.focus(); }
  function command(operation: PlanOperation, payload: ProposePlanPayload | ApplyPlanPayload, sources: SourceRead[]): ProjectCommand {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation, product_id: product.id, expected_revision: product.revision, source_read_set: sources.map(read => ({ ...read })), payload };
  }
  async function run(waiting: WaitingProject, element?: HTMLElement) {
    if (lock.current) return;
    const request = waiting.command;
    if (request.operation === "project.create") { waitFor(null); closePreview(); setNotice(projectCreationMoved); return; }
    if (projectId && (!("project_id" in request.payload) || request.payload.project_id !== projectId)) { setError("此请求属于其他项目，不能在当前项目执行；原请求仍保留。"); return; }
    lock.current = true; setBusy(true); setError(""); setNotice(""); setRejected(false);
    if (element) trigger.current = element;
    waitFor(waiting);
    let committed = false;
    try {
      if (waiting.stage === "preview") {
        const value = await api<PreparedProject>("v1/commands/preview", request);
        if (!value.command || value.command.product_id !== product.id || value.command.operation !== request.operation || value.command.command_id !== request.command_id || value.command.idempotency_key !== request.idempotency_key || !("project_id" in value.command.payload) || !("project_id" in request.payload) || value.command.payload.project_id !== request.payload.project_id || !value.confirmation_token || value.review?.operation !== request.operation || !value.review.effect || !value.review.name || !value.review.forecast || !value.review.input_snapshot) throw new Error("核对结果不完整；请保留输入，按原请求重新核对。");
        if (!alive.current) return;
        waitFor(null); setPreview(value);
      } else {
        const receipt = await api<Receipt>("v1/commands", request);
        if (!receipt.id || receipt.subject_type !== receiptTypes[request.operation] || !receipt.subject_id) throw new Error("保存结果尚未确认，请按原请求重试。");
        committed = true;
        if (!alive.current) return;
        waitFor(null); closePreview();
        setNotice(successMessages[request.operation]);
        await refresh(); await onSaved();
      }
    } catch (failure) {
      if (!alive.current) return;
      const failed = failure as Error & { status?: number };
      if (!committed) setRejected([400, 401, 403, 404, 409, 422].includes(failed.status ?? 0));
      if (!committed && waiting.stage === "execute") closePreview();
      if (failed.status === 401 || failed.status === 403) setProjects([]);
      setError(committed ? `保存已完成；最新结果读取失败，可刷新。${failed.message}` : failed.message);
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function proposePlan() {
    if (!project || !owner || project.plan) { setError("请先选择本人负责且尚未应用首版计划的项目。"); return; }
    if (project.source_status !== "current") { setError("固定型号定义的来源需要重核，请先处理来源。"); return; }
    try {
      if (draft.reason.trim().length < 3 || draft.reason.length > 2000) throw new Error("请填写 3–2000 字的计划候选说明。");
      const payload: ProposePlanPayload = { project_id: project.id, expected_project_revision: project.revision, schedule: buildSchedule(draft), reason: draft.reason.trim() };
      void run({ stage: "execute", command: command("work.plan.propose", payload, project.required_source_read_set) });
    } catch (failure) { setError((failure as Error).message); }
  }
  function applyPlan(target: Project, proposal: PlanProposal, element: HTMLElement) {
    const payload: ApplyPlanPayload = { project_id: target.id, proposal_id: proposal.id, expected_project_revision: target.revision };
    void run({ stage: "preview", command: command("work.plan.apply", payload, target.required_source_read_set) }, element);
  }
  function changeTask(key: string, patch: Partial<TaskDraft>) { edit({ ...draft, tasks: draft.tasks.map(task => task.key === key ? { ...task, ...patch } : task) }); }
  function addTask() {
    let number = draft.tasks.length + 1;
    while (draft.tasks.some(task => task.key === `task-${number}`)) number += 1;
    edit({ ...draft, tasks: [...draft.tasks, { key: `task-${number}`, title: "", discipline: "engineering", depends_on: [], minimum: "", maximum: "", basis: "" }] });
  }

  const showEditor = !!pending || (editorOpen ?? (!loading && !error && (projectId ? !!project && !project.plan : projects.length === 0)));
  return <section className="min-w-0 space-y-5" aria-label="项目与首版计划">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><p className="subtle">固定型号定义，组织真实研发工作</p><h2 className="mt-1 text-lg font-semibold">项目与首版计划</h2></div><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || !!pending || !!preview} aria-expanded={showEditor} aria-controls={`project-editor-pane-${product.id}`} onClick={() => setEditorOpen(!showEditor)}><CalendarBlank/>{showEditor ? "收起编排" : "编排首版计划"}</Button><Button variant="outline" disabled={busy || !!preview} onClick={() => { setError(""); void refresh().catch(failure => setError(failure.message)); }}><ArrowClockwise/>刷新项目</Button></div></header>
    <p className="subtle">项目由立项提案的 G0 决定生成；在此查看项目并编排首版计划。{projectId && "当前只办理所选项目。"}</p>
    {projectId && categoryId && <Button asChild variant="outline"><a href={globalHref({ area: "cockpit", categoryId, projectId })}>返回项目驾驶舱</a></Button>}
    {error && <p role="alert" className="break-words rounded-lg border border-destructive p-3 text-destructive">{error}</p>}
    {notice && <p role="status" className="break-words rounded-lg border border-border p-3">{notice}</p>}
    {pending && <div className="min-w-0 rounded-lg border border-primary p-4"><p className="font-medium">{pending.stage === "preview" ? "本次范围核对需要重试" : "本次保存结果仍待确认"}</p><p className="subtle my-2">输入及原请求已保留。重试核对同一次请求，核对原计划保存结果。</p><div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void run(pending)}>按原请求重试</Button>{(pending.stage === "preview" || rejected) && <Button disabled={busy} variant="outline" onClick={() => { waitFor(null); setRejected(false); closePreview(); setNotice("输入已保留，可修改后重新核对范围。"); }}>保留输入，返回编辑</Button>}</div></div>}
    {loading && <p role="status" className="subtle">正在读取当前授权范围内的项目…</p>}
    {hidden > 0 && <p className="subtle">{hidden} 个项目的来源权限需要重核，项目派生内容暂时隐藏。</p>}
    {hasMore && <p className="subtle">当前显示最近 100 个可见项目。</p>}
    <div className={showEditor ? "grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]" : "min-w-0 max-w-5xl"}>
      <div id={`project-editor-pane-${product.id}`} hidden={!showEditor} className="min-w-0 space-y-5">
        <section className="panel" aria-label="首版计划输入"><h3 className="font-semibold">准备首版计划候选</h3><p className="subtle mt-2 mb-4">本机输入按当前用户、型号{projectId ? "及项目" : ""}保留。读取或刷新项目不会覆盖或删除输入。</p><form noValidate onSubmit={event => { event.preventDefault(); proposePlan(); }}><fieldset disabled={!editable || loading} className="min-w-0">
          <label>研发项目<select disabled={!!projectId} value={draft.projectId} onChange={event => edit({ ...draft, projectId: event.target.value })}><option value="">选择真实项目</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name}{item.owner_id !== principalId ? " · 仅查看" : ""}{item.plan ? " · 已有首版计划" : ""}</option>)}</select></label>
          {draft.projectId && !project && !loading && <p className="mb-3 text-sm">原选项目目前不可见；已保留输入，请重核权限后刷新。</p>}
          {project && <div className="mb-4 rounded-lg border border-border p-3 text-sm"><p className="break-words">固定定义：{project.definition.title} · v{project.definition.revision} · 尚未正式发布</p><p className="mt-2 whitespace-pre-wrap break-words">范围：{project.scope}</p>{!owner && <p className="mt-2">当前项目由其他负责人管理，你可以查看已保存计划。</p>}{project.plan && <p className="mt-2">首版计划已经应用。后续修订入口暂未开放。</p>}</div>}
          <fieldset disabled={!project || !owner || !!project.plan || project.source_status !== "current"} className="min-w-0">
            <label>计划起点（UTC）<input type="datetime-local" step={60} value={draft.startUtc} onChange={event => edit({ ...draft, startUtc: event.target.value })}/></label>
            <details className="mb-5 rounded-lg border border-border p-3" open><summary className="cursor-pointer font-medium">声明本次工作日历</summary><div className="mt-3"><p className="subtle mb-3">默认工作日及 09–12 / 13–17 时段是可编辑的初始输入，尚未核验为工厂日历。全部时段和休息日期按下方时区解释。同一项目调整日历时，请明确填写新版本。</p><label>工作日历时区（IANA）<input maxLength={100} value={draft.timezone} onChange={event => edit({ ...draft, timezone: event.target.value })} placeholder="例如 Asia/Shanghai"/></label><label>日历版本<input maxLength={80} value={draft.calendarVersion} onChange={event => edit({ ...draft, calendarVersion: event.target.value })}/></label><fieldset className="mb-3"><legend className="mb-2 text-sm font-medium">每周工作日</legend><div className="flex flex-wrap gap-2">{weekdayNames.map((name, index) => <label key={index} className="!mb-0 flex items-center gap-1.5 rounded-lg border border-border px-2 py-1.5"><input type="checkbox" className="!m-0 !w-auto" checked={draft.weekdays.includes(index)} onChange={event => edit({ ...draft, weekdays: event.target.checked ? [...draft.weekdays, index].sort() : draft.weekdays.filter(day => day !== index) })}/><span>周{name}</span></label>)}</div></fieldset><label>每日工作时段（每行一段，本地时刻）<textarea maxLength={500} value={draft.intervals} onChange={event => edit({ ...draft, intervals: event.target.value })} placeholder={"09:00-12:00\n13:00-17:00"}/></label><label>额外休息日期（YYYY-MM-DD，每行一天）<textarea maxLength={44000} value={draft.holidays} onChange={event => edit({ ...draft, holidays: event.target.value })} placeholder="未确认的节假日不会自动补入"/></label></div></details>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">工程 / NPI 任务</h4><Button type="button" variant="outline" disabled={draft.tasks.length >= 500} onClick={addTask}><Plus/>新增任务</Button></div><p className="subtle mb-4">工时单位为整数分钟。最低、最高工时可分别留空表示未知；未知会传播到依赖任务，不会自动补造估计。无依赖的任务可并行开始。</p>
            <div className="min-w-0 space-y-4">{draft.tasks.map((task, index) => {
              const inUse = draft.tasks.some(item => item.depends_on.includes(task.key));
              return <article key={task.key} className="min-w-0 rounded-lg border border-border p-3"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><p className="subtle">任务 {index + 1} · {task.key}</p><Button type="button" variant="ghost" size="sm" disabled={draft.tasks.length === 1 || inUse} onClick={() => edit({ ...draft, tasks: draft.tasks.filter(item => item.key !== task.key) })}><Trash/>删除任务</Button></div>{inUse && <p className="subtle mb-3">被其他任务依赖；删除前请先解除对应依赖。</p>}<label>任务标题<input maxLength={200} value={task.title} onChange={event => changeTask(task.key, { title: event.target.value })}/></label><label>工作包<select value={task.discipline} onChange={event => changeTask(task.key, { discipline: event.target.value as TaskDraft["discipline"] })}><option value="engineering">工程</option><option value="npi">NPI / 制造导入</option></select></label><div className="grid min-w-0 gap-x-3 sm:grid-cols-2"><label>最低工时（分钟）<input type="number" inputMode="numeric" min={0} max={525600} step={1} value={task.minimum} onChange={event => changeTask(task.key, { minimum: event.target.value })} placeholder="留空 = 未知"/></label><label>最高工时（分钟）<input type="number" inputMode="numeric" min={0} max={525600} step={1} value={task.maximum} onChange={event => changeTask(task.key, { maximum: event.target.value })} placeholder="留空 = 未知"/></label></div><label>工时估计依据<textarea maxLength={2000} value={task.basis} onChange={event => changeTask(task.key, { basis: event.target.value })} placeholder="填写真实估计来源；填写工时后必填"/></label><fieldset className="min-w-0"><legend className="mb-2 text-sm font-medium">前置任务（完成后才能开始）</legend>{draft.tasks.length === 1 ? <p className="subtle">暂无其他任务；可新增并明确依赖。</p> : <div className="space-y-2">{draft.tasks.filter(item => item.key !== task.key).map(item => <label key={item.key} className="!mb-0 flex min-w-0 items-start gap-2"><input type="checkbox" className="!m-0 !mt-1 !w-auto shrink-0" checked={task.depends_on.includes(item.key)} onChange={event => changeTask(task.key, { depends_on: event.target.checked ? [...task.depends_on, item.key] : task.depends_on.filter(key => key !== item.key) })}/><span className="min-w-0 break-words">{item.title || "未命名任务"} · {item.key}</span></label>)}</div>}</fieldset></article>;
            })}</div><label className="mt-5">本次计划候选说明<textarea maxLength={2000} value={draft.reason} onChange={event => edit({ ...draft, reason: event.target.value })} placeholder="说明当前计划的范围、估计依据及未确定事项"/></label><Button type="submit"><CalendarBlank/>保存候选并计算预测</Button>
          </fieldset>
        </fieldset></form></section>
      </div>
      <section className="min-w-0 space-y-4" aria-label="已保存项目与计划"><h3 className="font-semibold">已保存项目</h3>{!loading && !error && hidden === 0 && projects.length === 0 && <div className="panel"><p className="subtle">当前范围尚无可见项目。请在品类的立项提案中完成 G0，通过后查看生成的项目。</p></div>}{projects.map(item => <article key={item.id} className="panel space-y-4"><div><div className="flex flex-wrap items-start justify-between gap-2"><h4 className="break-words font-semibold">{item.name}</h4><span className="subtle">{item.owner_id === principalId ? "本人负责" : "仅查看"} · {item.visibility === "private" ? "仅本人" : item.visibility === "audience" ? "指定评审人" : "品类授权成员"}</span></div><p className="mt-2 whitespace-pre-wrap break-words text-sm">{item.purpose}</p><p className="subtle mt-2 break-words">固定定义 v{item.definition.revision} · {item.definition.title} · 尚未正式发布</p><details className="mt-2 text-sm"><summary className="cursor-pointer">查看固定研发范围</summary><p className="mt-2 whitespace-pre-wrap break-words">{item.scope}</p></details>{item.source_status !== "current" && <p className="mt-2 text-sm">固定定义的来源需要重核，当前不可继续应用计划。</p>}</div><TimelineFacts/>
        {item.plan ? <section className="min-w-0 space-y-3"><p className="flex items-center gap-2 font-medium"><CheckCircle className="text-primary"/>首版计划 v{item.plan.revision} 已应用</p><p className="subtle">已建立工程与 NPI 工作包及 {item.tasks.length} 个任务。后续修订入口暂未开放。</p><Forecast value={item.plan.forecast}/></section> : <><p className="subtle">首版计划尚未应用，任务尚未正式建立。</p>{item.owner_id === principalId && <Button disabled={!editable} variant="outline" onClick={() => { setEditorOpen(true); edit({ ...draft, projectId: item.id }); setNotice("已选此项目；原有任务与日历输入保留，请核对后保存候选。"); }}>为此项目准备首版计划</Button>}<div className="min-w-0 space-y-3">{item.proposals.map(proposal => <details key={proposal.id} className="min-w-0 rounded-lg border border-border p-3"><summary className="cursor-pointer break-words font-medium">计划候选 v{proposal.revision}{proposal.project_revision !== item.revision ? " · 项目版本已变化" : ""}</summary><div className="mt-3 min-w-0 space-y-3"><p className="whitespace-pre-wrap break-words text-sm">{proposal.reason}</p><CalendarSnapshot value={proposal.input_snapshot}/><Forecast value={proposal.forecast}/>{item.owner_id === principalId && <Button disabled={!editable || proposal.project_revision !== item.revision || item.source_status !== "current"} onClick={event => applyPlan(item, proposal, event.currentTarget)}>核对并应用此首版计划</Button>}</div></details>)}</div></>}
      </article>)}</section>
    </div>
    <dialog ref={dialog} className="!w-[min(720px,calc(100vw-32px))] max-h-[90vh] overflow-auto" aria-labelledby={`project-review-${product.id}`} onCancel={event => { event.preventDefault(); if (!busy && !pending) closePreview(); }}>
      {preview && <div className="min-w-0 space-y-4"><h2 id={`project-review-${product.id}`} className="text-lg font-semibold">确认应用首版计划</h2><p className="break-words">{preview.review.effect}</p><p className="break-words font-medium">{preview.review.name}</p>{preview.review.definition && <p className="break-words text-sm">固定定义：{preview.review.definition.title} · v{preview.review.definition.revision} · 尚未正式发布</p>}{preview.review.purpose && <div><p className="subtle">用途</p><p className="whitespace-pre-wrap break-words">{preview.review.purpose}</p></div>}{preview.review.scope && <div><p className="subtle">固定研发范围</p><p className="whitespace-pre-wrap break-words">{preview.review.scope}</p></div>}{preview.review.visibility && <p>可见范围：{preview.review.visibility === "private" ? "仅本人" : preview.review.visibility === "audience" ? "指定评审人" : "品类授权成员"}。负责人为当前本人。</p>}{preview.review.reason && <div><p className="subtle">候选说明</p><p className="whitespace-pre-wrap break-words">{preview.review.reason}</p></div>}{preview.review.input_snapshot && <CalendarSnapshot value={preview.review.input_snapshot}/>}{preview.review.forecast && <><Forecast value={preview.review.forecast}/><TimelineFacts/></>}<p className="subtle">请核对此次范围与预测。确认只应用首版计划，不代替定义发布、批准基线、个人承诺或实绩登记。</p><div className="flex flex-wrap justify-end gap-2"><Button disabled={busy || !!pending} variant="outline" onClick={closePreview}>返回编辑</Button><Button disabled={busy || !!pending} onClick={() => void run({ stage: "execute", command: preview.command })}>确认应用此首版计划</Button></div></div>}
    </dialog>
  </section>;
}
