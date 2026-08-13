import { CaretRightIcon, WarningIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { CapaTimeline } from "./capa-timeline";
import { ComplaintForm } from "./complaint-form";
import { TriageForm } from "./triage-form";
import type {
  Complaint,
  ComplaintCreateInput,
  NcrCreateInput,
  NcrDetail,
} from "./quality-types";

const statusLabels: Record<Complaint["status"], string> = {
  open: "待 Triage",
  triaged: "已 Triage",
  investigating: "调查中",
  resolved: "已解决",
  closed: "已关闭",
};

export function QualityPanel({
  busy,
  canCreate,
  canManage,
  complaints,
  detail,
  error,
  identityUserId,
  loadState,
  onCreate,
  onRetry,
  onSelect,
  onTriage,
  selectedComplaint,
}: {
  busy: boolean;
  canCreate: boolean;
  canManage: boolean;
  complaints: Complaint[] | null;
  detail: NcrDetail | null;
  error: string | null;
  identityUserId: string;
  loadState: "idle" | "loading" | "ready" | "error";
  onCreate: (input: ComplaintCreateInput) => Promise<boolean>;
  onRetry: () => void;
  onSelect: (complaint: Complaint) => void;
  onTriage: (complaint: Complaint, input: NcrCreateInput) => Promise<boolean>;
  selectedComplaint: Complaint | null;
}) {
  if (loadState === "loading" || loadState === "idle") {
    return (
      <div aria-busy="true" aria-label="正在加载质量记录" className="space-y-3">
        {[0, 1, 2].map((item) => (
          <div className="h-16 animate-pulse rounded-lg bg-muted" key={item} />
        ))}
      </div>
    );
  }
  if (loadState === "error") {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center">
        <WarningIcon aria-hidden="true" className="mx-auto text-destructive" size={24} />
        <h3 className="mt-2 font-semibold">质量记录暂不可用</h3>
        <p className="mt-1 text-sm text-muted-foreground">读取失败不会被当作零投诉或 CAPA 已完成。</p>
        <Button className="mt-4 h-11" onClick={onRetry} variant="outline">
          重新加载
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">Complaint / CAPA</h3>
          <p className="mt-1 text-sm text-muted-foreground">异常优先；关闭项保留完整不可变质量历史。</p>
        </div>
        {canCreate ? (
          <ComplaintForm busy={busy} onSubmit={onCreate} ownerUserId={identityUserId} />
        ) : null}
      </div>
      {!complaints?.length ? (
        <div className="rounded-lg border border-dashed px-4 py-10 text-center" role="status">
          <h4 className="font-semibold">暂无质量反馈</h4>
          <p className="mt-1 text-sm text-muted-foreground">本项目还没有 Complaint 或 CAPA 记录。</p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <ul aria-label="Complaint 列表" className="space-y-2" role="list">
            {complaints.map((complaint) => (
              <li key={complaint.id}>
                <button
                  aria-pressed={selectedComplaint?.id === complaint.id}
                  className={cn(
                    "flex min-h-11 w-full items-start gap-3 rounded-lg border bg-card p-3 text-left focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/20",
                    selectedComplaint?.id === complaint.id && "border-primary/50 bg-primary/5",
                  )}
                  onClick={() => onSelect(complaint)}
                  type="button"
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-primary">{complaint.code}</span>
                      <span className="rounded-full border px-2 py-0.5 text-[10px] text-muted-foreground">
                        {statusLabels[complaint.status]}
                      </span>
                    </span>
                    <span className="mt-1 block truncate text-sm font-medium">{complaint.title}</span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {complaint.severity.toUpperCase()} · {new Date(complaint.reported_at).toLocaleDateString("zh-CN")}
                    </span>
                  </span>
                  <CaretRightIcon aria-hidden="true" className="mt-1 shrink-0 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
          <div className="min-w-0">
            {selectedComplaint ? (
              <section aria-labelledby="complaint-detail-title" className="rounded-lg border bg-card p-4">
                <p className="font-mono text-[11px] text-primary">{selectedComplaint.code}</p>
                <h3 className="mt-1 font-semibold" id="complaint-detail-title">
                  {selectedComplaint.title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{selectedComplaint.description}</p>
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                  <Meta label="来源" value={selectedComplaint.source} />
                  <Meta label="严重度" value={selectedComplaint.severity} />
                  <Meta label="发生时间" value={new Date(selectedComplaint.occurred_at).toLocaleString("zh-CN")} />
                  <Meta label="影响范围" value={selectedComplaint.affected_scope ?? "未填写"} />
                </dl>
                {selectedComplaint.status === "open" && canManage ? (
                  <TriageForm
                    busy={busy}
                    complaint={selectedComplaint}
                    onSubmit={(input) => onTriage(selectedComplaint, input)}
                  />
                ) : null}
              </section>
            ) : (
              <p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                选择一条 Complaint 查看质量链路。
              </p>
            )}
            {detail ? <div className="mt-4"><CapaTimeline detail={detail} /></div> : null}
          </div>
        </div>
      )}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-medium">{value}</dd>
    </div>
  );
}
