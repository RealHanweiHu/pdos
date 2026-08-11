import { ClipboardTextIcon } from "@phosphor-icons/react";

import { cn } from "@/lib/utils";

import type { Requirement } from "./requirement-types";

const statusLabels: Record<Requirement["status"], string> = {
  draft: "草稿",
  proposed: "待评估",
  approved: "已批准",
  rejected: "已拒绝",
  converted: "已转开发案",
};

const priorityLabels: Record<Requirement["priority"], string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "关键",
};

function RequirementRow({ requirement }: { requirement: Requirement }) {
  return (
    <>
      <span className="font-mono text-xs font-medium text-foreground">
        {requirement.code}
      </span>
      <span className="min-w-0 md:contents">
        <span className="block truncate font-medium">{requirement.title}</span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground md:mt-0">
          {requirement.customer?.name ?? "未关联客户"}
        </span>
      </span>
      <span className="hidden text-xs text-muted-foreground sm:block">
        {priorityLabels[requirement.priority]}
      </span>
      <span
        className={cn(
          "justify-self-start rounded-full px-2 py-0.5 text-[11px] font-medium",
          requirement.status === "draft" && "bg-muted text-muted-foreground",
          requirement.status === "proposed" && "bg-pending/10 text-pending",
          requirement.status === "approved" && "bg-success/10 text-success",
          requirement.status === "rejected" && "bg-destructive/10 text-destructive",
          requirement.status === "converted" && "bg-applied/10 text-applied",
        )}
      >
        {statusLabels[requirement.status]}
      </span>
    </>
  );
}

export function RequirementList({
  canEdit,
  onSelect,
  requirements,
  selectedId,
}: {
  canEdit: boolean;
  onSelect: (requirement: Requirement) => void;
  requirements: Requirement[];
  selectedId: string | null;
}) {
  if (requirements.length === 0) {
    return (
      <section className="rounded-lg border border-dashed py-16 text-center">
        <ClipboardTextIcon
          aria-hidden="true"
          className="mx-auto size-8 text-muted-foreground"
          weight="regular"
        />
        <h2 className="mt-3 font-semibold">还没有需求</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          从一条可验证的客户或市场需求开始。
        </p>
      </section>
    );
  }

  const grid =
    "grid min-h-14 grid-cols-[92px_minmax(0,1fr)_auto] items-center gap-3 px-3 text-left sm:grid-cols-[104px_minmax(0,1fr)_72px_auto] md:grid-cols-[112px_minmax(0,1fr)_160px_72px_88px]";

  return (
    <section aria-labelledby="requirement-list-title" className="min-w-0">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-semibold" id="requirement-list-title">
          全部需求
        </h2>
        <span className="font-mono text-xs text-muted-foreground">
          {requirements.length} 条
        </span>
      </div>
      <div
        aria-hidden="true"
        className={`${grid} hidden border-b text-[11px] font-medium text-muted-foreground md:grid`}
      >
        <span>编号</span>
        <span>标题</span>
        <span>客户</span>
        <span>优先级</span>
        <span>状态</span>
      </div>
      <ul className="divide-y rounded-lg border bg-card md:rounded-t-none md:border-t-0" role="list">
        {requirements.map((requirement) => (
          <li key={requirement.id}>
            {canEdit ? (
              <button
                aria-label={`打开需求 ${requirement.code}`}
                className={cn(
                  grid,
                  "w-full transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/30",
                  selectedId === requirement.id && "bg-accent",
                )}
                onClick={() => onSelect(requirement)}
                type="button"
              >
                <RequirementRow requirement={requirement} />
              </button>
            ) : (
              <div className={grid}>
                <RequirementRow requirement={requirement} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
