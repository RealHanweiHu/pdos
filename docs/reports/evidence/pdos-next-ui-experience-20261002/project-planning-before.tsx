"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CalendarBlank, CheckCircle, Plus, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { DefinitionList, DefinitionRevision } from "@/lib/product-view";
import { blankProjectDraft, buildSchedule, definitionReadSet, disciplineNames, durationText, forecastReasonNames, forecastWarningNames, restoreProjectDraft, utcText, weekdayNames, type ApplyPlanPayload, type CreateProjectPayload, type PlanForecast, type PlanProposal, type PreparedProject, type Project, type ProjectApi, type ProjectCommand, type ProjectDraft, type ProjectList, type ProposePlanPayload, type ScheduleInput, type SourceRead, type TaskDraft, type WaitingProject } from "@/lib/project-plan-view";

type Props = { product: { id: string; name: string; purpose: string; revision: number }; principalId: string; api: ProjectApi; onSaved: () => void | Promise<void> };
type Receipt = { id: string; subject_type: string; subject_id: string };
const receiptTypes: Record<ProjectCommand["operation"], string> = { "project.create": "project", "work.plan.propose": "plan_proposal", "work.plan.apply": "plan_revision" };
const successMessages: Record<ProjectCommand["operation"], string> = {
  "project.create": "真实研发项目已建立，产品定义和范围已固定；定义草稿尚未正式发布。",
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
  return <ProjectPanel key={`${props.principalId}:${props.product.id}`} {...props}/>;
}

function ProjectPanel({ product, principalId, api, onSaved }: Props) {
  const storageKey = `pdos-next:project-plan:${principalId}:${product.id}`;
  const [draft, setDraft] = useState(() => blankProjectDraft(product.purpose));
  const [projects, setProjects] = useState<Project[]>([]);
  const [definitions, setDefinitions] = useState<DefinitionRevision[]>([]);
  const [pending, setPending] = useState<WaitingProject | null>(null);
  const [preview, setPreview] = useState<PreparedProject | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [hidden, setHidden] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [rejected, setRejected] = useState(false);
  const alive = useRef(true);
  const lock = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const definition = definitions.find(item => item.id === draft.definitionId);
  const project = projects.find(item => item.id === draft.projectId);
  const editable = ready && !busy && !pending && !preview;
  const owner = project?.owner_id === principalId;

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([api<DefinitionList>(`v1/products/${product.id}/definitions`), api<ProjectList>(`v1/products/${product.id}/projects`)]);
    if (!alive.current) return;
    const failures: string[] = [];
    const defined = results[0];
    if (defined.status === "fulfilled") setDefinitions(defined.value.items);
    else { setDefinitions([]); failures.push(defined.reason?.message ?? "产品定义暂时无法读取。"); }
    const planned = results[1];
    if (planned.status === "fulfilled") { setProjects(planned.value.items); setHidden(planned.value.unavailable_count); setHasMore(planned.value.has_more); }
    else { setProjects([]); failures.push(planned.reason?.message ?? "项目暂时无法读取。"); }
    setLoading(false);
    if (failures.length) throw new Error(failures.join(" "));
  }, [api, product.id]);

  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => { if (alive.current) return refresh(); }).catch(failure => { if (alive.current) setError(failure.message); });
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        const local = restoreProjectDraft(JSON.parse(localStorage.getItem(storageKey) ?? "null"), product.id);
        if (local) { setDraft(local.draft); setPending(local.pending); }
      } catch { /* Optional local storage does not alter server authority. */ }
      setReady(true);
    });
    return () => { alive.current = false; };
  }, [refresh, storageKey, product.id]);
  useEffect(() => { if (preview) dialog.current?.showModal(); }, [preview]);

  function remember(next: ProjectDraft, waiting: WaitingProject | null) {
    try { localStorage.setItem(storageKey, JSON.stringify({ draft: next, pending: waiting })); } catch { /* Online actions remain available. */ }
  }
  function edit(next: ProjectDraft) { setDraft(next); remember(next, pending); }
  function waitFor(value: WaitingProject | null) { setPending(value); remember(draft, value); }
  function closePreview() { dialog.current?.close(); setPreview(null); trigger.current?.focus(); }
  function command(operation: ProjectCommand["operation"], payload: ProjectCommand["payload"], sources: SourceRead[]): ProjectCommand {
    return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation, product_id: product.id, expected_revision: product.revision, source_read_set: sources.map(read => ({ ...read })), payload };
  }
  async function run(waiting: WaitingProject, element?: HTMLElement) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); setRejected(false);
    if (element) trigger.current = element;
    waitFor(waiting);
    let committed = false;
    try {
      const request = waiting.command;
      if (waiting.stage === "preview") {
        const value = await api<PreparedProject>("v1/commands/preview", request);
        if (!value.command || value.command.product_id !== product.id || value.command.operation !== request.operation || value.command.command_id !== request.command_id || value.command.idempotency_key !== request.idempotency_key || !value.confirmation_token || value.review?.operation !== request.operation || !value.review.effect || !value.review.name || (request.operation === "project.create" ? !value.review.definition : !value.review.forecast || !value.review.input_snapshot)) throw new Error("核对结果不完整；请保留输入，按原请求重新核对。");
        if (!alive.current) return;
        waitFor(null); setPreview(value);
      } else {
        const receipt = await api<Receipt>("v1/commands", request);
        if (!receipt.id || receipt.subject_type !== receiptTypes[request.operation] || !receipt.subject_id) throw new Error("保存结果尚未确认，请按原请求重试。");
        committed = true;
        if (!alive.current) return;
        waitFor(null); closePreview();
        // Keep every user-entered field. Selecting the saved result does not load or replace its input.
        if (request.operation === "project.create") {
          const next = { ...draft, projectId: receipt.subject_id };
          setDraft(next); remember(next, null);
        }
        setNotice(successMessages[request.operation]);
        await refresh(); await onSaved();
      }
    } catch (failure) {
      if (!alive.current) return;
      const failed = failure as Error & { status?: number };
      if (!committed) setRejected([400, 401, 403, 404, 409, 422].includes(failed.status ?? 0));
      if (!committed && waiting.stage === "execute") closePreview();
      if (failed.status === 401 || failed.status === 403) { setProjects([]); setDefinitions([]); }
      setError(committed ? `保存已完成；最新结果读取失败，可刷新。${failed.message}` : failed.message);
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function createProject(element: HTMLElement) {
    if (!definition) { setError("请先选择一个真实可见的产品定义草稿。"); return; }
    if (draft.name.trim().length < 2 || draft.purpose.trim().length < 3 || draft.scope.trim().length < 3) { setError("请填写项目名称、用途与至少 3 字的项目范围。"); return; }
    if (definition.source_status !== "current") { setError("所选定义的来源需要重核，请先处理产品定义。"); return; }
    if (draft.visibility === "product" && definition.visibility !== "product") { setError("私人产品定义只能建立私人项目。"); return; }
    const payload: CreateProjectPayload = { name: draft.name.trim(), purpose: draft.purpose.trim(), scope: draft.scope.trim(), definition_id: definition.id, expected_definition_revision: definition.revision, visibility: draft.visibility };
    void run({ stage: "preview", command: command("project.create", payload, definitionReadSet(definition)) }, element);
  }
  function proposePlan() {
    if (!project || !owner || project.plan) { setError("请先选择本人负责且尚未应用首版计划的项目。"); return; }
    if (project.source_status !== "current") { setError("固定产品定义的来源需要重核，请先处理来源。"); return; }
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

  return <section className="min-w-0 space-y-5" aria-label="项目与首版计划">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><p className="subtle">固定产品定义，组织真实研发工作</p><h2 className="mt-1 text-lg font-semibold">项目与首版计划</h2></div><Button variant="outline" disabled={busy || !!preview} onClick={() => { setError(""); void refresh().catch(failure => setError(failure.message)); }}><ArrowClockwise/>刷新项目</Button></header>
    {error && <p role="alert" className="break-words rounded-lg border border-destructive p-3 text-destructive">{error}</p>}
    {notice && <p role="status" className="break-words rounded-lg border border-border p-3">{notice}</p>}
    {pending && <div className="min-w-0 rounded-lg border border-primary p-4"><p className="font-medium">{pending.stage === "preview" ? "本次范围核对需要重试" : "本次保存结果仍待确认"}</p><p className="subtle my-2">输入及原请求已保留。重试核对同一次请求，不重复建立项目或计划。</p><div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void run(pending)}>按原请求重试</Button>{(pending.stage === "preview" || rejected) && <Button disabled={busy} variant="outline" onClick={() => { waitFor(null); setRejected(false); closePreview(); setNotice("输入已保留，可修改后重新核对范围。"); }}>保留输入，返回编辑</Button>}</div></div>}
    {loading && <p role="status" className="subtle">正在读取当前授权范围内的项目与定义…</p>}
    {hidden > 0 && <p className="subtle">{hidden} 个项目的来源权限需要重核，项目派生内容暂时隐藏。</p>}
    {hasMore && <p className="subtle">当前显示最近 100 个可见项目。</p>}
    <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="min-w-0 space-y-5">
        <details className="panel" open={projects.length === 0}><summary className="cursor-pointer font-semibold">建立真实研发项目</summary><form className="mt-4 min-w-0" noValidate onSubmit={event => { event.preventDefault(); createProject(event.currentTarget.querySelector<HTMLButtonElement>('button[type="submit"]') ?? event.currentTarget); }}><fieldset disabled={!editable || loading} className="min-w-0">
          <label>固定产品定义<select value={draft.definitionId} onChange={event => edit({ ...draft, definitionId: event.target.value })}><option value="">选择已保存定义草稿</option>{definitions.map(item => <option key={item.id} value={item.id} disabled={item.source_status !== "current"}>{item.title} · v{item.revision} · 尚未正式发布{item.source_status !== "current" ? " · 来源待重核" : ""}</option>)}</select></label>
          {!loading && !definitions.length && <p className="subtle mb-3">请先保存产品定义，再建立项目。</p>}
          {definition && <p className="mb-4 break-words rounded-lg border border-border p-3 text-sm">本项目固定所选定义 v{definition.revision}，后续定义更新不会自动改写项目。此定义仍是草稿，尚未正式发布。</p>}
          <label>项目名称<input maxLength={160} value={draft.name} onChange={event => edit({ ...draft, name: event.target.value })}/></label>
          <label>项目用途<textarea maxLength={2000} value={draft.purpose} onChange={event => edit({ ...draft, purpose: event.target.value })}/></label>
          <label>本项目研发范围<textarea maxLength={2000} value={draft.scope} onChange={event => edit({ ...draft, scope: event.target.value })} placeholder="明确本轮要完成的工作和范围边界"/></label>
          <label>可见范围<select value={draft.visibility} onChange={event => edit({ ...draft, visibility: event.target.value as ProjectDraft["visibility"] })}><option value="private">仅本人</option><option value="product" disabled={definition?.visibility !== "product"}>产品授权成员</option></select></label>
          <p className="subtle mb-3">建立者成为项目负责人。首版计划仅由负责人编辑和应用。</p><Button type="submit" disabled={!definition}>核对范围并建立项目</Button>
        </fieldset></form></details>
        <section className="panel" aria-label="首版计划输入"><h3 className="font-semibold">准备首版计划候选</h3><p className="subtle mt-2 mb-4">本机输入按当前用户、当前产品保留。读取或刷新项目不会自动载入、覆盖或删除输入。</p><form noValidate onSubmit={event => { event.preventDefault(); proposePlan(); }}><fieldset disabled={!editable || loading} className="min-w-0">
          <label>研发项目<select value={draft.projectId} onChange={event => edit({ ...draft, projectId: event.target.value })}><option value="">选择真实项目</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name}{item.owner_id !== principalId ? " · 仅查看" : ""}{item.plan ? " · 已有首版计划" : ""}</option>)}</select></label>
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
      <section className="min-w-0 space-y-4" aria-label="已保存项目与计划"><h3 className="font-semibold">已保存项目</h3>{!loading && projects.length === 0 && <div className="panel"><p className="subtle">当前范围尚无可见项目。保存产品定义后，可以建立真实研发项目。</p></div>}{projects.map(item => <article key={item.id} className="panel space-y-4"><div><div className="flex flex-wrap items-start justify-between gap-2"><h4 className="break-words font-semibold">{item.name}</h4><span className="subtle">{item.owner_id === principalId ? "本人负责" : "仅查看"} · {item.visibility === "private" ? "仅本人" : "产品共享"}</span></div><p className="mt-2 whitespace-pre-wrap break-words text-sm">{item.purpose}</p><p className="subtle mt-2 break-words">固定定义 v{item.definition.revision} · {item.definition.title} · 尚未正式发布</p><details className="mt-2 text-sm"><summary className="cursor-pointer">查看固定研发范围</summary><p className="mt-2 whitespace-pre-wrap break-words">{item.scope}</p></details>{item.source_status !== "current" && <p className="mt-2 text-sm">固定定义的来源需要重核，当前不可继续应用计划。</p>}</div><TimelineFacts/>
        {item.plan ? <section className="min-w-0 space-y-3"><p className="flex items-center gap-2 font-medium"><CheckCircle className="text-primary"/>首版计划 v{item.plan.revision} 已应用</p><p className="subtle">已建立工程与 NPI 工作包及 {item.tasks.length} 个任务。后续修订入口暂未开放。</p><Forecast value={item.plan.forecast}/></section> : <><p className="subtle">首版计划尚未应用，任务尚未正式建立。</p>{item.owner_id === principalId && <Button disabled={!editable} variant="outline" onClick={() => { edit({ ...draft, projectId: item.id }); setNotice("已选此项目；原有任务与日历输入保留，请核对后保存候选。"); }}>为此项目准备首版计划</Button>}<div className="min-w-0 space-y-3">{item.proposals.map(proposal => <details key={proposal.id} className="min-w-0 rounded-lg border border-border p-3"><summary className="cursor-pointer break-words font-medium">计划候选 v{proposal.revision}{proposal.project_revision !== item.revision ? " · 项目版本已变化" : ""}</summary><div className="mt-3 min-w-0 space-y-3"><p className="whitespace-pre-wrap break-words text-sm">{proposal.reason}</p><CalendarSnapshot value={proposal.input_snapshot}/><Forecast value={proposal.forecast}/>{item.owner_id === principalId && <Button disabled={!editable || proposal.project_revision !== item.revision || item.source_status !== "current"} onClick={event => applyPlan(item, proposal, event.currentTarget)}>核对并应用此首版计划</Button>}</div></details>)}</div></>}
      </article>)}</section>
    </div>
    <dialog ref={dialog} className="!w-[min(720px,calc(100vw-32px))] max-h-[90vh] overflow-auto" aria-labelledby={`project-review-${product.id}`} onCancel={event => { event.preventDefault(); if (!busy && !pending) closePreview(); }}>
      {preview && <div className="min-w-0 space-y-4"><h2 id={`project-review-${product.id}`} className="text-lg font-semibold">{preview.command.operation === "project.create" ? "确认建立项目的范围" : "确认应用首版计划"}</h2><p className="break-words">{preview.review.effect}</p><p className="break-words font-medium">{preview.review.name}</p>{preview.review.definition && <p className="break-words text-sm">固定定义：{preview.review.definition.title} · v{preview.review.definition.revision} · 尚未正式发布</p>}{preview.review.purpose && <div><p className="subtle">用途</p><p className="whitespace-pre-wrap break-words">{preview.review.purpose}</p></div>}{preview.review.scope && <div><p className="subtle">固定研发范围</p><p className="whitespace-pre-wrap break-words">{preview.review.scope}</p></div>}{preview.review.visibility && <p>可见范围：{preview.review.visibility === "private" ? "仅本人" : "产品授权成员"}。负责人为当前本人。</p>}{preview.review.reason && <div><p className="subtle">候选说明</p><p className="whitespace-pre-wrap break-words">{preview.review.reason}</p></div>}{preview.review.input_snapshot && <CalendarSnapshot value={preview.review.input_snapshot}/>}{preview.review.forecast && <><Forecast value={preview.review.forecast}/><TimelineFacts/></>}<p className="subtle">请核对此次范围与预测。确认只建立项目或应用首版计划，不代替定义发布、批准基线、个人承诺或实绩登记。</p><div className="flex flex-wrap justify-end gap-2"><Button disabled={busy || !!pending} variant="outline" onClick={closePreview}>返回编辑</Button><Button disabled={busy || !!pending} onClick={() => void run({ stage: "execute", command: preview.command })}>{preview.command.operation === "project.create" ? "确认建立此项目" : "确认应用此首版计划"}</Button></div></div>}
    </dialog>
  </section>;
}
