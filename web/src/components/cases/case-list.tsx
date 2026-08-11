import { FolderOpenIcon } from "@phosphor-icons/react";
import Link from "next/link";

import { cn } from "@/lib/utils";

import type { DevelopmentCase } from "./case-types";

export const caseStatusLabels: Record<DevelopmentCase["status"], string> = {
  draft: "草稿",
  evaluating: "评估中",
  approved: "已批准",
  rejected: "已拒绝",
  converted: "已转项目",
};

function CaseRow({ developmentCase }: { developmentCase: DevelopmentCase }) {
  return (
    <>
      <span className="font-mono text-xs font-medium">{developmentCase.code}</span>
      <span className="min-w-0">
        <span className="block truncate font-medium">{developmentCase.title}</span>
        <span className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground md:hidden">
          {developmentCase.requirement_id}
        </span>
      </span>
      <span className="hidden truncate font-mono text-[11px] text-muted-foreground md:block">
        {developmentCase.requirement_id}
      </span>
      <span
        className={cn(
          "justify-self-start rounded-full px-2 py-0.5 text-[11px] font-medium",
          developmentCase.status === "draft" && "bg-muted text-muted-foreground",
          developmentCase.status === "evaluating" && "bg-pending/10 text-pending",
          developmentCase.status === "approved" && "bg-success/10 text-success",
          developmentCase.status === "rejected" && "bg-destructive/10 text-destructive",
          developmentCase.status === "converted" && "bg-applied/10 text-applied",
        )}
      >
        {caseStatusLabels[developmentCase.status]}
      </span>
    </>
  );
}

export function CaseList({
  canEdit,
  cases,
  onSelect,
  selectedId,
}: {
  canEdit: boolean;
  cases: DevelopmentCase[];
  onSelect: (developmentCase: DevelopmentCase) => void;
  selectedId: string | null;
}) {
  if (cases.length === 0) {
    return (
      <section className="rounded-lg border border-dashed py-16 text-center">
        <FolderOpenIcon
          aria-hidden="true"
          className="mx-auto size-8 text-muted-foreground"
          weight="regular"
        />
        <h2 className="mt-3 font-semibold">还没有开发案例</h2>
        <p className="mt-1 text-sm text-muted-foreground">从一条已批准需求发起正式转化。</p>
        {canEdit ? (
          <Link className="mt-4 inline-flex min-h-11 items-center text-sm text-primary" href="/requirements">
            返回需求池
          </Link>
        ) : null}
      </section>
    );
  }

  const grid =
    "grid min-h-14 grid-cols-[96px_minmax(0,1fr)_auto] items-center gap-3 px-3 text-left md:grid-cols-[112px_minmax(0,1fr)_minmax(120px,180px)_88px]";

  return (
    <section aria-labelledby="case-list-title" className="min-w-0">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-semibold" id="case-list-title">
          全部案例
        </h2>
        <span className="font-mono text-xs text-muted-foreground">{cases.length} 条</span>
      </div>
      <div
        aria-hidden="true"
        className={`${grid} hidden border-b text-[11px] font-medium text-muted-foreground md:grid`}
      >
        <span>编号</span>
        <span>标题</span>
        <span>来源需求 ID</span>
        <span>状态</span>
      </div>
      <ul className="divide-y rounded-lg border bg-card md:rounded-t-none md:border-t-0" role="list">
        {cases.map((developmentCase) => (
          <li key={developmentCase.id}>
            {canEdit ? (
              <button
                aria-label={`打开开发案例 ${developmentCase.code}`}
                className={cn(
                  grid,
                  "w-full transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/30",
                  selectedId === developmentCase.id && "bg-accent",
                )}
                onClick={() => onSelect(developmentCase)}
                type="button"
              >
                <CaseRow developmentCase={developmentCase} />
              </button>
            ) : (
              <div className={grid}>
                <CaseRow developmentCase={developmentCase} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
