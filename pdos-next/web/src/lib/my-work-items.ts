import {
  personalAttentionHref,
  type PersonalAttentionItem,
} from "./personal-attention";
import type { PersonalWorkItem } from "./personal-project-work";
import {
  originalTestStartTime,
  testStartWorkbenchHref,
  type PersonalTestStartPromise,
} from "./personal-test-start-promises";
import type { ActivityRun, MyOpenItem } from "./portfolio-reads";

export type WorkKind =
  | "decide"
  | "receive"
  | "verify"
  | "external"
  | "task"
  | "risk"
  | "pai"
  | "commitment"
  | "test";
export const workKindNames: Record<WorkKind, string> = {
  decide: "待决定",
  receive: "待接收",
  verify: "待验证",
  external: "等外部",
  task: "任务",
  risk: "风险",
  pai: "小Pai",
  commitment: "交付承诺",
  test: "开测承诺",
};
export type WorkRow = {
  id: string;
  title: string;
  project: string;
  kind: WorkKind;
  state: string;
  due: string | null;
  dateKind: string;
  facts: [string, string][];
  target:
    | { href: string }
    | { projectId: string; categoryId: string }
    | { runId: string; categoryId: string };
};
const stateNames: Record<string, string> = {
  proposed: "待分派",
  assigned: "待承接",
  accepted: "已承接",
  in_progress: "进行中",
  submitted: "待验收",
  completed: "已验收",
  in_review: "待审阅",
  open: "待办理",
  running: "进行中",
  offered: "已交样",
  scheduled: "已安排",
  executing: "执行中",
  authorized: "已授权",
  sent: "已登记发送",
  acknowledged: "已登记接收",
  reconciled: "已登记生效",
};
/** Date-only values keep their calendar meaning; instants use the fact's original zone when available. */
export function workDate(value: string | null, zone?: string): string | null {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const part = (type: string) =>
    parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}
export function responsibilityRows(
  attention: PersonalAttentionItem[],
  tasks: PersonalWorkItem[],
  legacy: MyOpenItem[],
  runs: ActivityRun[],
): WorkRow[] {
  // A task needing acceptance is one responsibility, even when two authorized projections include it.
  const attentionTasks = new Set(
    attention
      .filter(
        (item) =>
          item.kind === "task" || typeof item.details.task_id === "string",
      )
      .map((item) => String(item.details.task_id ?? item.source.id)),
  );
  const rows: WorkRow[] = attention.flatMap((item) => {
    const href = personalAttentionHref(item);
    return href
      ? [
          {
            id: `attention:${item.id}`,
            title: item.title,
            project: item.project?.name ?? item.category.name,
            kind: item.queue,
            state: stateNames[item.state] ?? "待办理",
            due: workDate(item.due_at),
            dateKind: "期限",
            facts: [
              ["办理事项", item.reason],
              ["本人责任", item.responsible.name ?? "本人"],
              ...(item.blocked
                ? [["当前限制", item.blocked.message] as [string, string]]
                : []),
              ...(item.due_at
                ? [["期限原值", item.due_at] as [string, string]]
                : []),
              ...(item.valid_until
                ? [["授权有效至", item.valid_until] as [string, string]]
                : []),
            ],
            target: { href },
          } as WorkRow,
        ]
      : [];
  });
  for (const item of tasks) {
    if (item.task.state === "completed" || attentionTasks.has(item.task.id))
      continue;
    rows.push(taskRow(item));
  }
  for (const item of legacy) {
    if (
      tasks.some((task) => task.task.id === item.id) ||
      attentionTasks.has(item.id)
    )
      continue;
    rows.push({
      id: `plan:${item.id}`,
      title: item.title,
      project: item.projectName,
      kind: item.kind === "task" ? "task" : "risk",
      state: item.kind === "task" ? "计划安排" : "待处置",
      due: workDate(item.due_date),
      dateKind: "安排日期",
      facts: [
        [
          "来源",
          item.kind === "task"
            ? "项目计划安排；不代表个人承诺"
            : "本人负责的项目待办",
        ],
      ],
      target: { categoryId: item.categoryId, projectId: item.projectId },
    });
  }
  for (const run of runs.filter((item) => item.status === "waiting_input"))
    rows.push({
      id: `run:${run.run_id}`,
      title: run.goal.split(/\n|【当前页面/)[0],
      project: run.categoryName || "个人对话",
      kind: "pai",
      state: "需查看",
      due: null,
      dateKind: "",
      facts: [["待处理", "查看对话中的缺项、配置或执行结果。"]],
      target: { runId: run.run_id, categoryId: run.categoryId },
    });
  return sortWorkRows(rows);
}
export function taskRow(item: PersonalWorkItem): WorkRow {
  return {
    id: `task:${item.id}`,
    title: item.task.title,
    project: item.project.name,
    kind: "task",
    state: stateNames[item.task.state],
    due: null,
    dateKind: "",
    facts: [
      ["任务执行人", item.assignee?.name ?? "尚未指定"],
      ["成果接收人", item.recipient?.name ?? "尚未指定"],
      ["任务版本", `v${item.task.revision}`],
    ],
    target: { categoryId: item.category.id, projectId: item.project.id },
  };
}
export function commitmentRows(
  tasks: PersonalWorkItem[],
  starts: PersonalTestStartPromise[],
): WorkRow[] {
  const rows: WorkRow[] = tasks.flatMap((item) => {
    const c = item.commitment;
    if (!c) return [];
    return [
      {
        id: `commitment:${c.id}`,
        title: item.task.title,
        project: item.project.name,
        kind: "commitment",
        state:
          item.timing === "overdue"
            ? "期限已过"
            : item.timing === "pending"
              ? "尚未到期"
              : "日期未知",
        due: workDate(c.promised_at, c.original_timezone),
        dateKind: "承诺",
        facts: [
          ["接收人", item.recipient?.name ?? "尚未记录"],
          ["成果范围", c.outcome_keys.join("、")],
          ["承诺原值", `${c.promised_at ?? "未知"} · ${c.original_timezone}`],
          ["任务进展", stateNames[item.task.state]],
          [
            "履行结论",
            "请进入项目核对；任务验收和期限状态不代替承诺履行结论。",
          ],
        ],
        target: { categoryId: item.category.id, projectId: item.project.id },
      } as WorkRow,
    ];
  });
  for (const item of starts)
    rows.push({
      id: `test:${item.id}`,
      title: `${item.build.name} · 开始测试`,
      project: item.project.name,
      kind: "test",
      state: {
        awaiting_start: "尚未登记开测",
        past_due_no_start_record: "期限已过，未登记开测",
        started_on_or_before: "按时开测",
        started_late: "晚于承诺开测",
      }[item.timing],
      due: workDate(item.promise.occurred_at, item.promise.original_timezone),
      dateKind: "承诺",
      facts: [
        ["承诺开测", originalTestStartTime(item.promise)],
        [
          "实际开测",
          item.actual_start
            ? originalTestStartTime(item.actual_start)
            : "尚未登记",
        ],
        ["接收人", "尚未记录"],
        [
          "测试范围",
          `样件 ${item.coverage.sample_count} · 测试项 ${item.coverage.item_count} · 配对 ${item.coverage.pair_count}`,
        ],
        [
          "原测试",
          `Build ${item.build.id} · 请求 ${item.request.id} · Run ${item.run.id}`,
        ],
        ["办理", "进入后选择上述 Build、请求与 Run。"],
      ],
      target: { href: testStartWorkbenchHref(item) },
    });
  return sortWorkRows(rows);
}
export function sortWorkRows(rows: WorkRow[]) {
  return rows.sort(
    (a, b) =>
      (a.due ?? "9999").localeCompare(b.due ?? "9999") ||
      a.title.localeCompare(b.title, "zh-CN") ||
      a.id.localeCompare(b.id),
  );
}
