"use client";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { reminderLabels, type ReminderPolicy } from "./process-template-reminders";

type Recipient = "owner" | "verifier" | "project_owner";
type Expected = { policy_key: string; recipient: Recipient; fire_at: string };
export type ReminderCase = {
  name: string;
  entity: "task" | "issue";
  status: string;
  as_of: string;
  due_date: string | null;
  updated_at: string | null;
  owner_present: boolean;
  verifier_present: boolean;
  project_owner_present: boolean;
  project_owner_same_as_owner: boolean;
  expected: Expected[];
};
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const recipients = { owner: "负责人", verifier: "验证人", project_owner: "项目负责人" };
const statuses = {
  task: { todo: "待接单", in_progress: "进行中", blocked: "受阻", pending_approval: "待批准", done: "已完成", skipped: "已跳过" },
  issue: { open: "新建", analysis: "分析中", action: "行动中", verification: "待验证", closed: "已关闭" },
};
const utcInput = (value: string | null) => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toISOString().slice(0, 16) : "";
const utcValue = (value: string) => value ? `${value}:00Z` : "";
const when = (value: unknown) => value && !Number.isNaN(Date.parse(String(value))) ? `${new Date(String(value)).toISOString().replace("T", " ").replace(".000Z", " UTC")}` : "未填写";
function tag(day: number) {
  return ({ "-3": "t3", "-1": "t1", "0": "due", "1": "overdue1", "3": "overdue3" } as Record<string, string>)[String(day)] ?? `${day < 0 ? "before" : "after"}${Math.abs(day)}`;
}
function ruleLabel(key: string): string {
  if (key === "task_accept") return "任务待接单";
  if (key === "issue_verify") return "问题待验证";
  if (key === "issue_stalled") return "问题停滞";
  const match = /^(task|issue)_due_(.+)$/.exec(key);
  if (!match) return key;
  const phase = ({ t3: "提前3天", t1: "提前1天", due: "到期当天", overdue1: "逾期1天", overdue3: "逾期3天", escalation: "逾期升级" } as Record<string, string>)[match[2]] ?? match[2].replace("before", "提前").replace("after", "逾期") + "天";
  return `${match[1] === "task" ? "任务" : "问题"}${phase}`;
}
function keys(entity: "task" | "issue", policy: ReminderPolicy) {
  return [...policy[`${entity}_due`].offsets.map(day => `${entity}_due_${tag(day)}`), `${entity}_due_escalation`, ...(entity === "task" ? ["task_accept"] : ["issue_verify", "issue_stalled"])];
}

export function ReminderRehearsalEditor({ value, policy, onChange }: {
  value: ReminderCase[];
  policy: ReminderPolicy;
  onChange: (value: ReminderCase[]) => void;
}) {
  const edit = (index: number, change: Partial<ReminderCase>) => onChange(value.map((item, n) => n === index ? { ...item, ...change } : item));
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">提醒时间与接收人演练</summary>
      <p className="mt-2 text-xs text-muted-foreground">使用虚构对象和联系人。预期清单须包含全部提醒，包括尚未到时的提醒；完成或关闭的场景应为空。修改输入不会自动修改预期，请独立核对。所有时间均为 UTC（北京时间减8小时）。示例供编辑，不代表验收通过。</p>
      <div className="mt-3 space-y-3">
        {value.map((item, index) => (
          <details key={index} className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm">{item.name || `场景 ${index + 1}`}</summary>
            <div className="mt-3 space-y-3">
              <label className="block text-sm">场景名称<input className={field} value={item.name} maxLength={200} onChange={event => edit(index, { name: event.target.value })} /></label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">对象<select className={field} value={item.entity} onChange={event => edit(index, { entity: event.target.value as ReminderCase["entity"], status: event.target.value === "task" ? "todo" : "open" })}><option value="task">任务</option><option value="issue">问题</option></select></label>
                <label className="text-sm">状态<select className={field} value={item.status} onChange={event => edit(index, { status: event.target.value })}>{Object.entries(statuses[item.entity]).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
                <label className="text-sm">模拟扫描时间（UTC）<input type="datetime-local" className={field} value={utcInput(item.as_of)} onChange={event => edit(index, { as_of: utcValue(event.target.value) })} /></label>
                <label className="text-sm">到期日期（可留空）<input type="date" className={field} value={item.due_date ?? ""} onChange={event => edit(index, { due_date: event.target.value || null })} /></label>
                <label className="text-sm">最后更新（UTC，可留空）<input type="datetime-local" className={field} value={utcInput(item.updated_at)} onChange={event => edit(index, { updated_at: utcValue(event.target.value) || null })} /></label>
              </div>
              <div className="flex flex-wrap gap-3">
                {([['owner_present', '有负责人'], ['verifier_present', '有验证人'], ['project_owner_present', '有项目负责人'], ['project_owner_same_as_owner', '项目负责人与经办人为同一人']] as const).map(([key, label]) => (
                  <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={item[key]} onChange={event => edit(index, { [key]: event.target.checked })} />{label}</label>
                ))}
              </div>
              <p className="text-sm font-medium">预期全部提醒</p>
              {item.expected.length === 0 && <p className="text-sm text-muted-foreground">预期没有提醒。</p>}
              {item.expected.map((expected, n) => {
                const update = (change: Partial<Expected>) => edit(index, { expected: item.expected.map((row, j) => j === n ? { ...row, ...change } : row) });
                return (
                  <div key={n} className="grid gap-2 rounded-md border p-2 sm:grid-cols-3">
                    <label className="text-xs">提醒事项<select className={field} value={expected.policy_key} onChange={event => update({ policy_key: event.target.value })}>{[...new Set([...keys(item.entity, policy), expected.policy_key])].map(key => <option key={key} value={key}>{ruleLabel(key)}</option>)}</select></label>
                    <label className="text-xs">接收人<select className={field} value={expected.recipient} onChange={event => update({ recipient: event.target.value as Recipient })}>{Object.entries(recipients).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
                    <label className="text-xs">提醒时间（UTC）<input type="datetime-local" className={field} value={utcInput(expected.fire_at)} onChange={event => update({ fire_at: utcValue(event.target.value) })} /></label>
                    <Button type="button" size="sm" variant="ghost" onClick={() => edit(index, { expected: item.expected.filter((_, j) => j !== n) })}>移除此预期</Button>
                  </div>
                );
              })}
              <div className="flex gap-2">
                <Button type="button" size="sm" variant="outline" disabled={item.expected.length >= 30} onClick={() => edit(index, { expected: [...item.expected, { policy_key: keys(item.entity, policy)[0], recipient: "owner", fire_at: item.as_of }] })}>增加一条预期</Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => onChange(value.filter((_, n) => n !== index))}>移除此场景</Button>
              </div>
            </div>
          </details>
        ))}
        <Button type="button" size="sm" variant="outline" disabled={value.length >= 20} onClick={() => onChange([...value, {
          name: "新提醒场景", entity: "task", status: "todo", as_of: "2026-01-10T12:00:00Z", due_date: "2026-01-10", updated_at: null,
          owner_present: true, verifier_present: true, project_owner_present: true, project_owner_same_as_owner: false, expected: [],
        }])}>增加提醒场景</Button>
      </div>
    </details>
  );
}

export function ReminderRehearsalResults({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  const rows = (input: unknown) => Array.isArray(input) ? input.filter(isRecord) : [];
  const schedule = (input: unknown) => rows(input).length ? rows(input).map((item, index) => <p key={index} className="text-xs">{ruleLabel(String(item.policy_key))} · {recipients[item.recipient as Recipient]} · {when(item.fire_at)}{typeof item.due === "boolean" ? item.due ? " · 已到时" : " · 尚未到时" : ""}</p>) : <p className="text-xs">无提醒</p>;
  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <p className="font-medium">提醒演练：{value.passed ? "预期相符" : "预期不符或覆盖不全"}</p>
      <p className="text-xs text-muted-foreground">{String(value.scope ?? "")}</p>
      {rows(value.coverage).map(item => <p key={String(item.key)} className="text-xs">{reminderLabels[String(item.key)]}：办理中{item.active ? "已覆盖" : "缺失"}；完成/关闭{item.terminal ? "已覆盖" : "缺失"}</p>)}
      {rows(value.cases).map((item, index) => (
        <details key={index}><summary className="cursor-pointer">{String(item.name)} · {item.passed ? "相符" : "不符"}</summary>
          <div className="mt-2 grid gap-3 sm:grid-cols-2"><div><p>人工预期</p>{schedule(item.expected)}</div><div><p>按配置计算</p>{schedule(item.actual)}</div></div>
        </details>
      ))}
    </div>
  );
}
