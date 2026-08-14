import { PauseCircleIcon, SparkleIcon } from "@phosphor-icons/react/ssr";
import Link from "next/link";

import { Button } from "@/components/ui/button";

import type { AiBrief } from "./ai-types";

export type AiBriefLoadState = "loading" | "ready" | "error" | "restricted";

function elapsedLabel(value: string | null) {
  if (!value) return "没有历史简报";
  const elapsedHours = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 3_600_000));
  if (elapsedHours < 1) return "最近 1 小时内";
  if (elapsedHours < 24) return `${elapsedHours} 小时前`;
  return `${Math.floor(elapsedHours / 24)} 天前`;
}

export function AiBriefCard({
  brief,
  onRetry,
  state,
}: {
  brief: AiBrief | null;
  onRetry: () => void;
  state: AiBriefLoadState;
}) {
  return (
    <section aria-label="AI 简报" className="min-w-0 overflow-hidden rounded-lg border bg-card xl:col-span-2">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2"><SparkleIcon aria-hidden="true" className="text-primary" /><h2 className="font-semibold">AI 简报</h2></div>
        {brief?.latest_finding_at ? <span className="font-mono text-[10px] text-muted-foreground">更新于 {elapsedLabel(brief.latest_finding_at)}</span> : null}
      </div>
      {state === "loading" ? (
        <div aria-busy="true" className="grid gap-3 p-4 sm:grid-cols-2">
          {[0, 1, 2].map((item) => <div className="h-14 animate-pulse rounded-lg bg-muted" key={item} />)}
        </div>
      ) : null}
      {state === "restricted" ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">外部成员不具备 AI 工程简报权限。</p> : null}
      {state === "error" ? (
        <div className="px-4 py-8 text-center" role="alert">
          <p className="font-medium text-destructive">AI 简报暂不可用</p>
          <p className="mt-1 text-xs text-muted-foreground">读取失败不会被展示为“没有异常”。</p>
          <Button className="mt-4 h-11" onClick={onRetry} variant="outline">重新加载简报</Button>
        </div>
      ) : null}
      {state === "ready" && brief?.status === "unavailable" ? (
        <div className="border-b bg-pending/8 px-4 py-4" role="status">
          <div className="flex items-start gap-2"><PauseCircleIcon aria-hidden="true" className="mt-0.5 shrink-0 text-pending" /><div><p className="font-medium text-pending">AI 已暂停</p><p className="mt-1 text-xs text-muted-foreground">模型或预算当前不可用；最近可追溯 Finding 为 {elapsedLabel(brief.latest_finding_at)}。系统不会把失能伪装成正常。</p></div></div>
        </div>
      ) : null}
      {state === "ready" && brief ? (
        <dl className="grid grid-cols-3 border-b bg-muted/20">
          <div className="border-r px-4 py-3">
            <dt className="text-[11px] text-muted-foreground">Finding 接受率</dt>
            <dd className="mt-1 font-mono text-lg font-semibold">{brief.acceptance_rate_basis_points === null ? "—" : `${Math.round(brief.acceptance_rate_basis_points / 100)}%`}</dd>
            <p className="mt-0.5 text-[10px] text-muted-foreground">{brief.accepted_count}/{brief.reviewed_count} 人工裁决</p>
          </div>
          <div className="border-r px-4 py-3">
            <dt className="text-[11px] text-muted-foreground">被采取行动</dt>
            <dd className="mt-1 font-mono text-lg font-semibold">{brief.applied_count}</dd>
            <p className="mt-0.5 text-[10px] text-muted-foreground">实际 Apply 次数</p>
          </div>
          <div className="px-4 py-3">
            <dt className="text-[11px] text-muted-foreground">已收窄输出</dt>
            <dd className="mt-1 font-mono text-lg font-semibold">{brief.narrowed_output_count}</dd>
            <p className="mt-0.5 text-[10px] text-muted-foreground">低质类型暂停入箱</p>
          </div>
        </dl>
      ) : null}
      {state === "ready" && brief && brief.items.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <p className="font-medium">Agent 正在值守</p>
          <p className="mt-1 text-sm text-muted-foreground">还没有可用于简报的 Finding。</p>
        </div>
      ) : null}
      {state === "ready" && brief && brief.items.length > 0 ? (
        <ol className="grid sm:grid-cols-2" role="list">
          {brief.items.map((item) => (
            <li className="border-b p-4 sm:odd:border-r" key={item.finding_id}>
              <Link className="font-medium leading-5 hover:text-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25" href={item.href}>{item.title}</Link>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.summary}</p>
              <div className="mt-2 flex min-h-6 items-center gap-2">
                {item.evidence.length > 0 ? item.evidence.slice(0, 2).map((evidence, index) => (
                  <Link className="font-mono text-[10px] font-medium text-primary hover:underline" href={evidence.href} key={evidence.event_row_id}>[{index + 1}] {evidence.label}</Link>
                )) : <span className="text-[10px] text-destructive">无引用</span>}
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      {state === "ready" && brief ? (
        <Link className="flex min-h-11 items-center justify-center border-t px-4 text-sm font-medium text-primary hover:bg-muted/40" href="/ai-review">去收件箱处理 {brief.pending_review_count} 条待审 ›</Link>
      ) : null}
    </section>
  );
}
