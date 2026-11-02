import type { CurrentProgress } from "@/lib/current-progress";

export function CurrentMilestones({ progress }: { progress: CurrentProgress }) {
  return <section aria-labelledby="current-progress-heading" className="space-y-4">
    <div><h2 id="current-progress-heading" className="text-lg font-semibold">当前功能进展</h2><p className="subtle mt-1">直接读取唯一活动清单。已有实现、演示通过和阶段验收分别记录，不折算完成百分比。</p></div>
    {progress.highlights.filter(item => item.title.startsWith("S1")).map(item => <details key={item.title} className="panel border-primary"><summary className="cursor-pointer font-medium text-primary">{item.title}</summary><p className="mt-3 text-sm leading-relaxed">{item.text}</p></details>)}
    {progress.milestones.length ? <div className="divide-y divide-border rounded-lg border border-border bg-[var(--surface)]">
      {progress.milestones.map(item => <details key={item.id} className="px-4 py-4 sm:px-5"><summary className="cursor-pointer"><span className="ml-1 font-mono text-xs text-[var(--text-subtle)]">{item.id}</span><span className="ml-3 font-semibold">{item.title}</span><span className="mt-2 block pl-5 text-sm leading-relaxed text-[var(--text-subtle)]">{item.status}</span></summary><p className="mt-4 whitespace-pre-wrap break-words border-t border-border pt-4 text-sm leading-7">{item.detail}</p></details>)}
    </div> : <p role="status" className="panel">尚未取得当前里程碑，不能用历史勾选代替当前进展。</p>}
  </section>;
}
