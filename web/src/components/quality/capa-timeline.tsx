import { CheckCircleIcon, CircleIcon, WarningCircleIcon } from "@phosphor-icons/react";

import { cn } from "@/lib/utils";

import type { NcrDetail } from "./quality-types";

const steps = ["open", "containment", "root_cause", "action", "verification", "closed"] as const;
const labels = {
  open: "NCR 建立",
  containment: "即时遏制",
  root_cause: "根因分析",
  action: "纠正预防",
  verification: "有效性验证",
  closed: "关闭",
};

export function CapaTimeline({ detail }: { detail: NcrDetail }) {
  const current = steps.indexOf(detail.ncr.status);
  return (
    <section aria-labelledby="capa-timeline-title" className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] text-primary">{detail.ncr.code}</p>
          <h3 className="mt-1 font-semibold" id="capa-timeline-title">
            CAPA 执行链
          </h3>
        </div>
        <span className="rounded-full border bg-muted px-2.5 py-1 text-xs">
          {labels[detail.ncr.status]}
        </span>
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6" role="list">
        {steps.map((step, index) => {
          const complete = index < current || detail.ncr.status === "closed";
          const active = index === current && detail.ncr.status !== "closed";
          const Icon = complete ? CheckCircleIcon : active ? WarningCircleIcon : CircleIcon;
          return (
            <li
              className={cn(
                "flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-xs text-muted-foreground",
                complete && "border-success/30 text-success",
                active && "border-primary/40 bg-primary/5 font-medium text-foreground",
              )}
              key={step}
            >
              <Icon aria-hidden="true" className="shrink-0" weight={complete ? "fill" : "regular"} />
              {labels[step]}
            </li>
          );
        })}
      </ol>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <HistoryColumn
          empty="尚无根因记录"
          items={detail.root_causes.map((record) => ({
            id: record.id,
            title: `v${record.version} · ${record.method}`,
            meta: ({ draft: "待审核", approved: "已批准", superseded: "已被修订替代" })[record.status],
            body: record.root_cause,
          }))}
          title="根因版本"
        />
        <HistoryColumn
          empty="尚无 CAPA 措施"
          items={detail.actions.map((record) => ({
            id: record.id,
            title: record.action_type === "corrective" ? "纠正措施" : "预防措施",
            meta: `${({ planned: "待执行", in_progress: "执行中", completed: "已完成" })[record.status]} · ${record.due_date}`,
            body: record.description,
          }))}
          title="措施"
        />
        <HistoryColumn
          empty="尚无有效性复核"
          items={detail.effectiveness_reviews.map((record) => ({
            id: record.id,
            title: `复核 #${record.review_number}`,
            meta: record.result === "effective" ? "有效" : "无效，需补充措施",
            body: record.actual_result,
          }))}
          title="有效性历史"
        />
      </div>
    </section>
  );
}

function HistoryColumn({
  empty,
  items,
  title,
}: {
  empty: string;
  items: { id: string; title: string; meta: string; body: string }[];
  title: string;
}) {
  return (
    <div>
      <h4 className="text-sm font-semibold">{title}</h4>
      {items.length ? (
        <ul className="mt-2 space-y-2" role="list">
          {items.map((item) => (
            <li className="rounded-lg border bg-background p-3" key={item.id}>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-medium text-foreground">{item.title}</span>
                <span className="text-muted-foreground">{item.meta}</span>
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted-foreground">{item.body}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 rounded-lg border border-dashed px-3 py-5 text-center text-xs text-muted-foreground">
          {empty}
        </p>
      )}
    </div>
  );
}
