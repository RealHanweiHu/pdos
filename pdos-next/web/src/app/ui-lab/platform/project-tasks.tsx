"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowUpRight,
  CaretDown,
  CheckCircle,
  Circle,
  MagnifyingGlass,
  Plus,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { projects, roles, type Role } from "./design-data";
import s from "./platform.module.css";
import t from "./project-tasks.module.css";

import {
  statuses,
  priorities,
  taskProfiles,
  seedProjectTasks,
  type TaskStatus,
  type ProjectTask,
  type NpiTaskTemplate,
} from "./project-task-data";

export function useProjectTasks(catalog: NpiTaskTemplate[]) {
  const [tasks, setTasks] = useState(() => seedProjectTasks(catalog));
  const [draft, setDraft] = useState<ProjectTask | null>(null);
  const [notice, setNotice] = useState<{
    project: string;
    text: string;
  } | null>(null);
  const sequence = useRef(200);
  function create(
    project: string,
    person: string,
    phase = taskProfiles[project].currentPhase,
  ) {
    setNotice(null);
    setDraft({
      id: "",
      project,
      title: "",
      owner: person,
      status: "待开始",
      priority: "中",
      due: "",
      description: "",
      origin: "extra",
      phase,
    });
  }
  function save() {
    if (!draft?.title.trim()) return;
    const saved = {
      ...draft,
      id: draft.id || `${draft.project}-X${++sequence.current}`,
      title: draft.title.trim(),
    };
    setTasks((current) =>
      draft.id
        ? current.map((task) => (task.id === draft.id ? saved : task))
        : [...current, saved],
    );
    setNotice({
      project: saved.project,
      text: `已保存“${saved.title}”（预览）`,
    });
    setDraft(null);
  }
  return { tasks, draft, setDraft, notice, create, save };
}
export type TaskController = ReturnType<typeof useProjectTasks>;
const dateLabel = (date: string) =>
  date ? `${Number(date.slice(5, 7))}月${Number(date.slice(8))}日` : "未设日期";
export function TaskRows({
  tasks,
  controller,
  showProject = false,
}: {
  tasks: ProjectTask[];
  controller: TaskController;
  showProject?: boolean;
}) {
  return (
    <div className={`${s.tableWrap} ${t.taskTable}`}>
      <table className={t.table} data-projects={showProject}>
        <thead>
          <tr>
            <th>任务</th>
            <th>来源</th>
            <th>阶段</th>
            <th>状态</th>
            <th>负责人</th>
            <th>截止日期</th>
            {showProject && <th>项目</th>}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id}>
              <td>
                <button onClick={() => controller.setDraft({ ...task })}>
                  <span className={t.taskIcon}>
                    {task.status === "已完成" ? (
                      <CheckCircle size={16} />
                    ) : (
                      <Circle size={16} />
                    )}
                  </span>
                  <small>{task.id}</small>
                  <strong title={task.title}>{task.title}</strong>
                </button>
              </td>
              <td>{task.origin === "npi" ? "NPI" : "额外"}</td>
              <td title={task.phase}>{task.phase}</td>
              <td>
                <span
                  className={s.status}
                  data-tone={
                    task.status === "受阻"
                      ? "warning"
                      : task.status === "已完成"
                        ? "success"
                        : "neutral"
                  }
                >
                  {task.status}
                </span>
              </td>
              <td title={task.owner}>{task.owner}</td>
              <td>{dateLabel(task.due)}</td>
              {showProject && (
                <td>{projects.find((p) => p.id === task.project)?.name}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function TaskFilter({
  label,
  value,
  onChange,
  children,
  className = "",
  active = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  className?: string;
  active?: boolean;
}) {
  return (
    <div className={`${t.filter} ${className}`} data-active={active}>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
      <CaretDown size={12} aria-hidden="true" />
    </div>
  );
}

export function ProjectTasks({
  controller: c,
  project,
  person,
  disabled,
  empty,
}: {
  controller: TaskController;
  project: string;
  person: string;
  disabled: boolean;
  empty: boolean;
}) {
  const [view, setView] = useState("列表");
  const [query, setQuery] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("全部状态");
  const [owner, setOwner] = useState("所有负责人");
  const [origin, setOrigin] = useState("全部来源");
  const [phase, setPhase] = useState(taskProfiles[project].currentPhase);
  const projectTasks = c.tasks.filter((task) => task.project === project);
  const phases = [...new Set(projectTasks.map((task) => task.phase))];
  const shown = empty
    ? []
    : projectTasks.filter(
        (task) =>
          `${task.title}${task.id}`
            .toLowerCase()
            .includes(query.trim().toLowerCase()) &&
          (status === "全部状态" || task.status === status) &&
          (owner === "所有负责人" || task.owner === owner) &&
          (origin === "全部来源" || task.origin === origin) &&
          (phase === "全部阶段" || task.phase === phase),
      );
  return (
    <div className={`${s.page} ${t.taskPage}`}>
      <h1 className={t.screenReaderOnly}>项目任务</h1>
      <div className={t.toolbar}>
        <div className={t.views} aria-label="任务视图">
          {["列表", "看板"].map((value) => (
            <button
              key={value}
              aria-pressed={view === value}
              onClick={() => setView(value)}
            >
              {value}
            </button>
          ))}
        </div>
        <div className={t.filters} aria-label="任务筛选">
          <TaskFilter
            label="筛选任务阶段"
            value={phase}
            onChange={setPhase}
            className={t.phaseFilter}
          >
            <option>全部阶段</option>
            {phases.map((value) => (
              <option key={value} value={value}>
                {value}
                {value === taskProfiles[project].currentPhase ? " · 当前" : ""}
              </option>
            ))}
          </TaskFilter>
          <TaskFilter
            label="筛选任务来源"
            value={origin}
            onChange={setOrigin}
            active={origin !== "全部来源"}
          >
            <option>全部来源</option>
            <option value="npi">NPI 任务</option>
            <option value="extra">额外任务</option>
          </TaskFilter>
          <TaskFilter
            label="筛选任务状态"
            value={status}
            onChange={setStatus}
            active={status !== "全部状态"}
          >
            <option>全部状态</option>
            {statuses.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </TaskFilter>
          <TaskFilter
            label="筛选任务负责人"
            value={owner}
            onChange={setOwner}
            className={t.ownerFilter}
            active={owner !== "所有负责人"}
          >
            <option>所有负责人</option>
            {[
              ...new Set([...projectTasks.map((task) => task.owner), person]),
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </TaskFilter>
        </div>
        <div className={t.actions}>
          <div className={t.search} role="search" aria-label="项目任务搜索">
            <MagnifyingGlass size={14} aria-hidden="true" />
            <input
              ref={searchInput}
              aria-label="搜索项目任务"
              placeholder="搜索任务"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setQuery("");
                  e.stopPropagation();
                }
              }}
            />
            {query && (
              <button
                aria-label="清除任务搜索"
                onClick={() => {
                  setQuery("");
                  searchInput.current?.focus();
                }}
              >
                <X size={12} />
              </button>
            )}
          </div>
          <span className={t.count} role="status" aria-live="polite">
            {shown.length} 项
          </span>
          <Button
            className={t.create}
            disabled={disabled}
            onClick={() => {
              setQuery("");
              setOrigin("全部来源");
              setOwner("所有负责人");
              setStatus("全部状态");
              c.create(
                project,
                person,
                phase === "全部阶段"
                  ? taskProfiles[project].currentPhase
                  : phase,
              );
            }}
          >
            <Plus size={14} />
            新建任务
          </Button>
        </div>
      </div>
      {c.notice?.project === project && (
        <p className={t.notice} role="status">
          {c.notice.text}
        </p>
      )}
      {!shown.length ? (
        <div className={t.empty}>
          <h2>
            {projectTasks.length && !empty
              ? "没有匹配的任务"
              : "还没有项目任务"}
          </h2>
          <p>
            {projectTasks.length && !empty
              ? "调整搜索或筛选条件。"
              : "从一个明确的任务开始，分配负责人和截止日期。"}
          </p>
          {(query ||
            status !== "全部状态" ||
            owner !== "所有负责人" ||
            origin !== "全部来源" ||
            phase !== "全部阶段") && (
            <Button
              variant="outline"
              onClick={() => {
                setQuery("");
                setStatus("全部状态");
                setOwner("所有负责人");
                setOrigin("全部来源");
                setPhase("全部阶段");
              }}
            >
              清除筛选
            </Button>
          )}
        </div>
      ) : view === "列表" ? (
        <TaskRows tasks={shown} controller={c} />
      ) : (
        <div className={t.board}>
          {statuses.map((value) => (
            <section key={value}>
              <h2>
                {value}
                <span>
                  {shown.filter((task) => task.status === value).length}
                </span>
              </h2>
              {shown
                .filter((task) => task.status === value)
                .map((task) => (
                  <button key={task.id} onClick={() => c.setDraft({ ...task })}>
                    <small>
                      {task.id} · {task.origin === "npi" ? "NPI" : "额外"}
                    </small>
                    <strong>{task.title}</strong>
                    {phase === "全部阶段" && (
                      <p className={t.cardPhase}>{task.phase}</p>
                    )}
                    <div>
                      <span>{task.owner}</span>
                      <span>{dateLabel(task.due)}</span>
                    </div>
                  </button>
                ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
export function ProjectTaskDialog({
  controller: c,
  person,
  role,
  disabled,
  onRelated,
  completed,
}: {
  controller: TaskController;
  person: string;
  role: Role;
  disabled: boolean;
  onRelated: (id: string) => void;
  completed: string[];
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const open = !!c.draft;
  useEffect(() => {
    if (open) {
      ref.current?.showModal();
      nameInput.current?.focus();
      body.current?.scrollTo({ top: 0 });
    } else ref.current?.close();
  }, [open]);
  const original = c.tasks.find((task) => task.id === c.draft?.id);
  const editable =
    !disabled &&
    role !== "external" &&
    !!c.draft &&
    (!c.draft.id ||
      original?.owner === person ||
      ["lead", "management"].includes(role));
  const patch = (value: Partial<ProjectTask>) =>
    c.setDraft((current) => (current ? { ...current, ...value } : null));
  return (
    <dialog
      ref={ref}
      className={s.inspector}
      aria-labelledby="task-title"
      onCancel={() => c.setDraft(null)}
    >
      <header>
        <span>{c.draft?.id || "新任务"}</span>
        <button aria-label="关闭任务详情" onClick={() => c.setDraft(null)}>
          <X size={19} />
        </button>
      </header>
      {c.draft && (
        <div ref={body} className={`${s.inspectorBody} ${t.editor}`}>
          <h1 id="task-title">{c.draft.id ? "任务详情" : "新建额外任务"}</h1>
          <p>
            {projects.find((p) => p.id === c.draft?.project)?.name} ·{" "}
            {c.draft.origin === "npi" ? "NPI 流程任务" : "额外任务"}
          </p>
          {c.draft.template && (
            <section className={t.templateInfo}>
              <h2>{c.draft.phase}</h2>
              <p>应交付：{c.draft.template.deliverables.join("、")}</p>
              <details>
                <summary>查看任务要求</summary>
                <ul>
                  {c.draft.template.requirements.map((requirement) => (
                    <li key={requirement}>{requirement}</li>
                  ))}
                </ul>
                <p>NPI 模板任务：{c.draft.template.originalTitle}</p>
              </details>
            </section>
          )}
          <fieldset disabled={!editable}>
            <label>
              任务名称
              <input
                ref={nameInput}
                value={c.draft.title}
                onChange={(e) => patch({ title: e.target.value })}
                placeholder="例如：完成接口差异核对"
              />
            </label>
            <label>
              说明
              <textarea
                value={c.draft.description}
                onChange={(e) => patch({ description: e.target.value })}
                placeholder="补充范围、完成要求或相关依据…"
              />
            </label>
            <div className={t.fields}>
              <label>
                所属阶段
                <select
                  value={c.draft.phase}
                  disabled={c.draft.origin === "npi"}
                  onChange={(e) => patch({ phase: e.target.value })}
                >
                  {[
                    ...new Set(
                      c.tasks
                        .filter((task) => task.project === c.draft?.project)
                        .map((task) => task.phase),
                    ),
                  ].map((phase) => (
                    <option key={phase}>{phase}</option>
                  ))}
                </select>
              </label>
              <label>
                状态
                <select
                  value={c.draft.status}
                  onChange={(e) =>
                    patch({ status: e.target.value as TaskStatus })
                  }
                >
                  {statuses.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label>
                优先级
                <select
                  value={c.draft.priority}
                  onChange={(e) =>
                    patch({
                      priority: e.target.value as ProjectTask["priority"],
                    })
                  }
                >
                  {priorities.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label>
                负责人
                <select
                  value={c.draft.owner}
                  onChange={(e) => patch({ owner: e.target.value })}
                >
                  <option>待分配</option>
                  {roles
                    .filter((r) => r.id !== "external")
                    .map((r) => (
                      <option key={r.id}>{r.person}</option>
                    ))}
                </select>
              </label>
              <label>
                截止日期
                <input
                  type="date"
                  value={c.draft.due}
                  onInput={(e) => patch({ due: e.currentTarget.value })}
                  onChange={(e) => patch({ due: e.target.value })}
                />
              </label>
            </div>
          </fieldset>
          {c.draft.related && (
            <section>
              <h2>关联办理</h2>
              <button
                className={s.textLink}
                onClick={() => {
                  const id = c.draft?.related;
                  ref.current?.close();
                  c.setDraft(null);
                  if (id) onRelated(id);
                }}
              >
                {c.draft.related} ·{" "}
                {completed.includes(c.draft.related)
                  ? "回看办理结果"
                  : "查看事项与依据"}
                <ArrowUpRight size={14} />
              </button>
            </section>
          )}
          <p>
            任务完成表示执行进展；接收、专业结论与正式发布仍在对应事项中办理。
          </p>
          {!editable && (
            <p role="status">
              {disabled
                ? "当前预览状态不可修改，仍可查看任务。"
                : "由任务负责人或项目管理人员维护，当前身份只读。"}
            </p>
          )}
          <div className={s.inspectorActions}>
            <Button
              disabled={!editable || !c.draft.title.trim()}
              onClick={c.save}
            >
              保存任务
            </Button>
            <Button variant="ghost" onClick={() => c.setDraft(null)}>
              取消
            </Button>
          </div>
        </div>
      )}
    </dialog>
  );
}
