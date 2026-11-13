"use client";
// D47 system forecast recompute (P66): no model, no undo, not a 小Pai action. It
// shows forecast next to plan and commitments and never changes either (I08, P58).
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowsClockwise, Path } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { ProjectApi } from "@/lib/project-plan-view";
import { checkView, floatText, impactNames, issueNames, originNames, refreshCommand, shiftText, windowText, type ForecastView, type RefreshCommand } from "@/lib/project-forecast";

type Props = { api: ProjectApi; product: { id: string; revision: number }; projectId: string; titles: Record<string, string> };
type Receipt = { id: string; subject_type: string };

export function ProjectForecastRefresh({ api, product, projectId, titles }: Props) {
  const [view, setView] = useState<ForecastView | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [pending, setPending] = useState<RefreshCommand | null>(null);
  const alive = useRef(true), lock = useRef(false);
  const refresh = useCallback(async () => {
    const value = await api<ForecastView>(`v1/products/${product.id}/projects/${projectId}/forecast`);
    checkView(value, projectId);
    if (alive.current) setView(value);
  }, [api, product.id, projectId]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => { if (alive.current) return refresh(); }).catch(failure => { if (alive.current) setError((failure as Error).message); }); return () => { alive.current = false; }; }, [refresh]);

  async function run(command: RefreshCommand) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); setPending(command);
    try {
      const receipt = await api<Receipt>("v1/commands", command);
      if (!receipt.id || receipt.subject_type !== "forecast_refresh") throw new Error("本次重算回执尚未确认，请按原请求重试。");
      if (!alive.current) return;
      setPending(null); setNotice(view?.inputs?.changed === false ? "输入没有变化，沿用今天已算出的预测。" : "预测已重算；计划、基线和承诺都没有改变。");
      await refresh();
    } catch (failure) {
      if (!alive.current) return;
      const failed = failure as Error & { status?: number };
      if ([400, 401, 403, 404, 409, 422].includes(failed.status ?? 0)) setPending(null);
      setError(failed.status === 409 ? `${failed.message} 已重新读取最新输入。` : failed.message);
      if (failed.status === 409) void refresh().catch(() => undefined);
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  const result = view?.current?.result ?? null;
  const zone = result?.calendar.timezone ?? "Asia/Shanghai";
  const format = (value: string) => { try { return new Intl.DateTimeFormat("zh-CN", { timeZone: zone, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); } catch { return value; } };
  return <section className="min-w-0 space-y-3 rounded-lg border border-border p-3" aria-label="系统重算的预测">
    <header className="flex flex-wrap items-start justify-between gap-2">
      <div><h4 className="flex items-center gap-2 font-medium"><Path aria-hidden size={16}/>预测（系统重算）</h4><p className="subtle mt-1 text-xs">按当前计划与任务实际开始、提交时间重算；不改计划、基线和承诺，也不算作小Pai 的动作。</p></div>
      <Button size="sm" variant="outline" disabled={busy || !view?.inputs} onClick={() => { setError(""); try { void run(pending ?? refreshCommand(view!, product)); } catch (failure) { setError((failure as Error).message); } }}><ArrowsClockwise aria-hidden/>{pending ? "按原请求重试" : "重算预测"}</Button>
    </header>
    {error && <p role="alert" className="rounded-lg border border-destructive p-2 text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {view?.inputs && <p className="subtle text-xs">{view.inputs.changed ? "输入已变化，可重算。" : "输入与上次重算相同。"} 预测日 {view.inputs.as_of_day}</p>}
    {!view && !error && <p role="status" className="subtle text-sm">正在读取预测…</p>}
    {view && !result && <p className="subtle text-sm">{view.unavailable === "no_applied_plan" ? "尚未应用计划。" : "尚未重算过预测。"}</p>}
    {result && <div className="space-y-3 text-sm">
      <dl className="grid gap-2 sm:grid-cols-3">
        <div><dt className="subtle">预测完工</dt><dd>{windowText(result.project_finish, format)}</dd></div>
        <div><dt className="subtle">计划完工（计划 v{result.plan.revision}）</dt><dd>{result.planned_finish ? format(result.planned_finish) : "未知"}</dd></div>
        <div><dt className="subtle">关键路径</dt><dd>{result.float_status === "calculated" ? result.critical_path.map(key => titles[key] ?? key).join(" → ") || "无" : "数据不全，未计算浮时"}</dd></div>
      </dl>
      {result.calendar.label && <p className="subtle text-xs">日历 {result.calendar.timezone} · {result.calendar.version}：{result.calendar.label}</p>}
      <div className="overflow-x-auto"><table className="w-full min-w-[560px]"><thead><tr className="subtle text-left"><th className="py-1 pr-2 font-medium">任务</th><th className="py-1 pr-2 font-medium">预测完成</th><th className="py-1 pr-2 font-medium">与计划比</th><th className="py-1 font-medium">浮时</th></tr></thead><tbody>
        {result.tasks.map(task => <tr key={task.key} className="border-t border-border align-top"><td className="py-1 pr-2">{titles[task.key] ?? task.key}<span className="subtle block text-xs">{originNames[task.origin]}{task.issues.length ? ` · ${task.issues.map(code => issueNames[code] ?? code).join("、")}` : ""}</span></td><td className="py-1 pr-2">{windowText(task.finish, format)}</td><td className="py-1 pr-2">{shiftText(task.shift_minutes)}</td><td className="py-1">{floatText(task)}</td></tr>)}
      </tbody></table></div>
      {result.commitments.length > 0 && <div><p className="font-medium">承诺对照（承诺不变）</p><ul className="mt-1 space-y-1">{result.commitments.map(item => <li key={item.commitment_id} className={item.impact === "later" ? "text-primary" : ""}>{item.key ? titles[item.key] ?? item.key : "未关联计划任务"} · 承诺 {item.promised_at ? format(item.promised_at) : "日期待定"} · {impactNames[item.impact]}</li>)}</ul></div>}
      {view!.history.length > 1 && <details className="text-xs"><summary className="cursor-pointer subtle">重算记录 {view!.history.length} 次</summary><ol className="mt-1 space-y-1">{view!.history.map(row => <li key={row.id}>第 {row.revision} 次 · {format(row.created_at)} · 完工 {row.project_finish ? windowText(row.project_finish, format) : "未知"}</li>)}</ol></details>}
    </div>}
  </section>;
}
