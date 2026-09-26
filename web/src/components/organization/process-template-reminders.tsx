"use client";

import { Button } from "@/components/ui/button";

export type DuePolicy = { offsets: number[]; escalate_after_days: number | null };
export type ReminderPolicy = {
  task_due: DuePolicy;
  issue_due: DuePolicy;
  task_accept: boolean;
  issue_verification: boolean;
  issue_stalled_days: number | null;
};
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const when = (day: number) => day < 0 ? `提前 ${-day} 天` : day === 0 ? "到期当天" : `逾期 ${day} 天`;

export function ReminderPolicyEditor({ value, onChange }: {
  value: ReminderPolicy;
  onChange: (value: ReminderPolicy) => void;
}) {
  const due = (key: "task_due" | "issue_due", change: Partial<DuePolicy>) =>
    onChange({ ...value, [key]: { ...value[key], ...change } });
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">任务与问题的提醒节奏</summary>
      <p className="mt-2 text-xs text-muted-foreground">在创建项目时固定此版配置。提醒进入站内通知；外部投递沿用独立设置。在途项目保留原提醒规则。到期日期按 UTC 零点（北京时间08:00）计算。</p>
      <div className="mt-3 space-y-4">
        {([['task_due', '任务'], ['issue_due', '问题']] as const).map(([key, label]) => (
          <div key={key} className="space-y-3 rounded-md border p-3">
            <p className="text-sm font-medium">{label}到期提醒</p>
            <p className="text-xs text-muted-foreground">负数为提前天数，0为当天，正数为逾期天数；每项为 -90 至 90 的整数，最多12次，不能重复。</p>
            {value[key].offsets.map((day, index) => (
              <div key={index} className="flex items-center gap-2">
                <input aria-label={`${label}第${index + 1}次提醒天数`} type="number" min={-90} max={90} step={1}
                  className={`${field} w-28`} value={day}
                  onChange={event => due(key, { offsets: value[key].offsets.map((item, n) => n === index ? Number(event.target.value) : item) })} />
                <span className="text-xs">{when(day)}</span>
                <Button type="button" size="sm" variant="ghost"
                  onClick={() => due(key, { offsets: value[key].offsets.filter((_, n) => n !== index) })}>移除</Button>
              </div>
            ))}
            {value[key].offsets.length === 0 && <p className="text-sm">不向{label}负责人发送到期提醒。</p>}
            <Button type="button" size="sm" variant="outline" disabled={value[key].offsets.length >= 12}
              onClick={() => {
                let day = -7;
                while (value[key].offsets.includes(day)) day++;
                due(key, { offsets: [...value[key].offsets, day] });
              }}>增加一次到期提醒</Button>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={value[key].escalate_after_days !== null}
                onChange={event => due(key, { escalate_after_days: event.target.checked ? 3 : null })} />
              逾期后另提醒项目负责人（与经办人为同一人时不重复）
            </label>
            {value[key].escalate_after_days !== null && (
              <label className="block text-sm">逾期多少天升级提醒
                <input type="number" min={1} max={90} step={1} className={field} value={value[key].escalate_after_days}
                  onChange={event => due(key, { escalate_after_days: Number(event.target.value) })} />
              </label>
            )}
          </div>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={value.task_accept} onChange={event => onChange({ ...value, task_accept: event.target.checked })} />新任务待接单时提醒负责人
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={value.issue_verification} onChange={event => onChange({ ...value, issue_verification: event.target.checked })} />问题进入验证时提醒验证人
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={value.issue_stalled_days !== null}
            onChange={event => onChange({ ...value, issue_stalled_days: event.target.checked ? 7 : null })} />问题分析或行动阶段长时间未更新时提醒负责人
        </label>
        {value.issue_stalled_days !== null && (
          <label className="block text-sm">连续未更新天数
            <input type="number" min={1} max={90} step={1} className={field} value={value.issue_stalled_days}
              onChange={event => onChange({ ...value, issue_stalled_days: Number(event.target.value) })} />
          </label>
        )}
      </div>
    </details>
  );
}

export function reminderValue(key: string, value: unknown): string {
  if (key === "task_due" || key === "issue_due") {
    const item = value as DuePolicy;
    return `${item.offsets.map(when).join("、") || "无到期提醒"}；${item.escalate_after_days === null ? "不升级" : `逾期 ${item.escalate_after_days} 天另提醒项目负责人`}`;
  }
  if (key === "issue_stalled_days") return value === null ? "不提醒" : `连续 ${value} 天未更新时提醒`;
  return value ? "提醒" : "不提醒";
}
export const reminderLabels: Record<string, string> = { task_due: "任务到期", issue_due: "问题到期", task_accept: "任务待接单", issue_verification: "问题待验证", issue_stalled_days: "问题停滞" };
export function ReminderPolicySummary({ value }: { value: ReminderPolicy }) {
  return <details><summary className="cursor-pointer text-sm">创建时采用的提醒规则</summary><div className="mt-2 space-y-1 text-xs">{Object.entries(value).map(([key, item]) => <p key={key}>{reminderLabels[key]}：{reminderValue(key, item)}</p>)}</div></details>;
}
