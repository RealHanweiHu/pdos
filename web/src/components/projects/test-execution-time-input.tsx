"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export function TestExecutionTimeInput({ runIds, busy, onSave }: { runIds: string[]; busy: boolean; onSave: (items: object[]) => Promise<void> }) {
  const [precision, setPrecision] = useState("day"), [value, setValue] = useState(""), [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  return <div className="space-y-3 rounded-md border bg-muted/30 p-3 text-xs">
    <p className="font-medium">为选中的 {runIds.length} 条记录补录同一实际测试日期或时间</p>
    <p>仅选择确实在同一日期或时刻执行的记录。补录后仍需单独核对并确认正式结果；原报告值及修改依据会保留。</p>
    <div className="grid gap-3 sm:grid-cols-2"><label>精度<select className="mt-1 w-full rounded-md border bg-background p-2" value={precision} disabled={busy} onChange={e => { setPrecision(e.target.value); setValue(""); }}><option value="day">只知道日期</option><option value="instant">知道准确时间（当前设备时区）</option></select></label>
      <label>实际测试{precision === "day" ? "日期" : "时间"}<input className="mt-1 w-full rounded-md border bg-background p-2" type={precision === "day" ? "date" : "datetime-local"} value={value} disabled={busy} onChange={e => setValue(e.target.value)} /></label></div>
    <label className="block">补录依据及修改原因<textarea className="mt-1 w-full rounded-md border bg-background p-2" maxLength={2000} value={reason} disabled={busy} onChange={e => setReason(e.target.value)} placeholder="例如：原报告第2页测试日期，或执行人员确认的实际日期" /></label>
    <Button type="button" size="sm" variant="outline" disabled={busy || !runIds.length || !value || !reason.trim()} onClick={async () => {
      setError(null);
      try {
        const time = precision === "day" ? { executed_date: value } : { executed_at: new Date(value).toISOString() };
        await onSave(runIds.map(run_id => ({ run_id, ...time, reason: reason.trim() })));
        setValue(""); setReason("");
      } catch (e) { setError(e instanceof Error ? e.message : "补录未完成"); }
    }}>保存所选记录的测试时间</Button>
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
