import Link from "next/link";
import type { Metadata } from "next";
import { parsePlanProgress, planStatusLabels, planStatusOrder, type PlanItem, type PlanItemStatus, type PlanProgress } from "@/lib/plan-progress";
import { PlanItemsTable } from "@/components/plan/plan-items-table";
import { readPlanSource } from "@/lib/plan-source";
import { parseCurrentProgress } from "@/lib/current-progress";
import { CurrentMilestones } from "@/components/plan/current-milestones";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "计划执行进度 · PDOS" };

function StatusDot({ status }: { status: PlanItemStatus }) { return <span className="plan-dot" data-status={status} aria-hidden="true" />; }

function statusCountsOf(items: PlanItem[]): { status: PlanItemStatus; count: number }[] {
  return planStatusOrder.map((status) => ({ status, count: items.filter((item) => item.status === status).length })).filter((entry) => entry.count > 0);
}

function GroupBars({ plan }: { plan: PlanProgress }) {
  return <section className="panel" aria-label="分组进度">
    <h2 className="font-semibold">分组进度</h2>
    <p className="subtle mt-1 mb-5">按原条目所属分组统计勾选状态；部分完成表示已有实现或分项证据，不等于整项验收。</p>
    <div className="space-y-4">
      {plan.groups.map((group) => {
        const counts = statusCountsOf(group.items);
        const done = group.items.filter((item) => item.status === "done").length;
        return <div key={group.id}>
          <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <p className="text-[13px] font-medium"><span className="plan-id mr-2">{group.id}</span>{group.label}</p>
            <p className="subtle">{group.items.length} 项 · 全部完成 {done} · {counts.map((entry) => `${planStatusLabels[entry.status]} ${entry.count}`).join(" · ")}</p>
          </div>
          <div className="plan-bar" role="img" aria-label={`${group.id} ${group.items.length} 项状态分布：${counts.map((entry) => `${planStatusLabels[entry.status]} ${entry.count}`).join("，")}`}>
            {counts.map((entry) => <i key={entry.status} data-status={entry.status} style={{ flexGrow: entry.count }} />)}
          </div>
        </div>;
      })}
    </div>
  </section>;
}

function NextQueue({ plan }: { plan: PlanProgress }) {
  return <section className="panel" aria-label="当前队列">
    <h2 className="font-semibold">当前主交付 · PDOS Next</h2>
    <p className="mt-1 text-[13px]">{plan.notes.focus}</p>
    {plan.steps.length > 0 && <ol className="mt-5 space-y-3">
      {plan.steps.map((step) => <li key={step.order} className="flex gap-3 border-t border-border pt-3">
        <span className="plan-badge shrink-0" aria-hidden="true">步骤 {step.order}</span>
        <div className="min-w-0">
          <p className="text-[13px]">{step.action}</p>
          <p className="subtle mt-1">必须留下：{step.result}</p>
        </div>
      </li>)}
    </ol>}
    <div className="mt-6 grid gap-3 lg:grid-cols-2">
      {plan.nextAreas.map((area) => <div key={area.label} className="rounded-lg border border-border p-4">
        <h3 className="text-[13px] font-semibold">{area.label}</h3>
        <p className="mt-2 text-[13px]">{area.ready}</p>
        <p className="subtle mt-2">必要缺口：{area.gaps}</p>
      </div>)}
    </div>
    {plan.notes.candidate && <p className="subtle mt-5">最新已登记候选：{plan.notes.candidate}</p>}
  </section>;
}

function IssueList({ plan }: { plan: PlanProgress }) {
  const pending = plan.items.filter((item) => item.status === "todo");
  const blocked = plan.items.filter((item) => item.status === "blocked");
  return <section aria-label="问题清单" className="space-y-3">
    <h2 className="font-semibold">问题清单</h2>
    {plan.notes.blocker && <div className="panel border-destructive">
      <h3 className="text-[13px] font-semibold">当前阻塞与恢复条件</h3>
      <p className="mt-2 text-[13px] leading-relaxed">{plan.notes.blocker}</p>
    </div>}
    {plan.notes.incident && <div className="panel">
      <h3 className="text-[13px] font-semibold">数据库与事故边界</h3>
      <p className="mt-2 text-[13px] leading-relaxed">{plan.notes.incident}</p>
    </div>}
    {blocked.length > 0 && <div className="panel">
      <h3 className="text-[13px] font-semibold">外部阻塞条目 · {blocked.length}</h3>
      <ul className="mt-3 space-y-2">{blocked.map((item) => <li key={item.id} className="flex items-baseline gap-2 text-[13px]"><StatusDot status={item.status} /><span className="plan-id">{item.id}</span><span>{item.title}</span></li>)}</ul>
    </div>}
    <div className="panel">
      <h3 className="text-[13px] font-semibold">待完成条目 · {pending.length}</h3>
      <p className="subtle mt-1 mb-3">尚未全部验收不等于未开发：大量能力已有实现或分项证据，具体覆盖见唯一清单原条目。</p>
      <ul className="space-y-2">
        {pending.map((item) => <li key={item.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px]">
          <StatusDot status={item.status} /><span className="plan-id">{item.id}</span><span className="min-w-0 flex-1">{item.title}</span><span className="subtle">{item.group} · {item.groupLabel}</span>
        </li>)}
      </ul>
    </div>
  </section>;
}

function Loops({ plan }: { plan: PlanProgress }) {
  return <section className="panel" aria-label="功能闭环">
    <h2 className="font-semibold">功能闭环</h2>
    <p className="subtle mt-1 mb-5">未完成工作按业务闭环推进；每项只归属一个主闭环，完成一个切片不等于关闭整个条目。</p>
    <div className="grid gap-3 lg:grid-cols-2">
      {plan.loops.map((loop) => {
        const counts = statusCountsOf(loop.items);
        return <div key={loop.anchor} className="rounded-lg border border-border p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h3 className="text-[13px] font-semibold">{loop.title}</h3>
            <p className="subtle">{loop.items.length} 项 · {counts.map((entry) => `${planStatusLabels[entry.status]} ${entry.count}`).join(" · ") || "无归属条目"}</p>
          </div>
          <p className="subtle mt-2">{loop.note}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {loop.items.map((item) => <span key={item.id} className="plan-chip" title={item.title}><StatusDot status={item.status} />{item.id}</span>)}
          </div>
        </div>;
      })}
    </div>
  </section>;
}

export default async function PlanPage() {
  const source = await readPlanSource();
  if ("failure" in source) {
    return <>
      <header className="workspace-public-header"><span className="font-semibold">PDOS</span><span className="subtle">计划执行进度</span></header>
      <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-8">
        <section className="panel" role="alert"><h1 className="text-lg font-semibold">清单暂不可读</h1><p className="mt-3 text-[13px]">{source.failure}</p></section>
      </main>
    </>;
  }
  const plan = parsePlanProgress(source.markdown);
  const current = parseCurrentProgress(source.markdown);
  const updated = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "America/Los_Angeles" }).format(source.updated);
  const kpis: { label: string; value: number; status: PlanItemStatus | null }[] = [
    { label: "原条目总数", value: plan.counts.total, status: null },
    ...planStatusOrder.map((status) => ({ label: planStatusLabels[status], value: plan.counts[status], status })),
  ];
  return <>
    <header className="workspace-public-header"><span className="font-semibold">PDOS</span><span className="subtle">计划执行进度</span><Link className="plan-back" href="/">返回工作区</Link></header>
    <main className="mx-auto w-full max-w-[1080px] px-4 pb-16 pt-8 sm:px-8">
      <div className="workspace-page-heading">
        <div className="min-w-0">
          <h1>计划执行进度</h1>
          <p>清单 v{plan.version} · 更新 {updated}（洛杉矶时间）。本页直接读取当前队列；历史 N/P/Q 条目归档展示，不计入当前工程进度。</p>
        </div>
      </div>
      {process.env.PDOS_NEXT_LOCAL_SESSION && <Link className="mb-6 inline-block text-primary hover:underline" href="/preview">打开本地预览导览 →</Link>}
      <CurrentMilestones progress={current}/>
      <details className="mt-8 rounded-lg border border-border p-4">
        <summary className="cursor-pointer font-semibold">原工程历史底账（已归档）</summary>
        <p className="subtle my-4">以下内容仅用于追溯，旧“当前/下一步”和勾选状态不代表 pdos-next 的当前任务或验收结果。</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5" aria-label="历史状态总览">
        {kpis.map((kpi) => <div key={kpi.label} className="panel flex items-center gap-3 py-4">
          {kpi.status ? <StatusDot status={kpi.status} /> : <span className="plan-dot" aria-hidden="true" />}
          <div className="min-w-0"><p className="text-xl font-semibold">{kpi.value}</p><p className="subtle">{kpi.label}</p></div>
        </div>)}
      </div>
      <div className="mt-6 space-y-6">
        <GroupBars plan={plan} />
        <NextQueue plan={plan} />
        <IssueList plan={plan} />
        <Loops plan={plan} />
        <section className="panel" aria-label="条目明细">
          <h2 className="font-semibold">条目明细 · {plan.counts.total}</h2>
          <p className="subtle mt-1 mb-4">状态、摘要、依赖与责任取自清单原条目；[x] 表示本条全部判据有证据，[~] 部分完成，[ ] 待完成。</p>
          <PlanItemsTable items={plan.items} />
        </section>
      </div>
      </details>
      <p className="subtle mt-8">真实资格、人工出口与生产启用以原批准与授权为准；本页展示不授予任何权限。</p>
    </main>
  </>;
}
