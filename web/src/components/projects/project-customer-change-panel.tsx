"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

type CustomerChange = {
  id: string;
  code: string;
  title: string;
  status: string;
  description: string | null;
  quote_note: string | null;
  lead_time_days: number | null;
  customer_decision_note: string | null;
  impact_analysis: {
    counts?: Record<string, number>;
    retest_required?: number;
  } | null;
  reply_drafted_by_user_id: string | null;
  engineering_change_request_id: string | null;
};

type LoadState = "loading" | "ready" | "error";

type Props = {
  projectId: string;
  canEdit: boolean;
  canApprove: boolean;
  currentUserId: string;
};

const STATUS_LABELS: Record<string, string> = {
  received: "已受理",
  impact_analyzed: "已分析影响",
  reply_drafted: "报价待审",
  reply_approved: "报价已批",
  accepted: "客户接受",
  rejected: "客户拒绝",
  cancelled: "已取消",
};

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail?.message ?? "操作失败";
  } catch {
    return "操作失败";
  }
}

async function post(path: string, body: unknown): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw new Error(await readError(response));
}

/**
 * Customer change requests (CCR).
 *
 * Kept visually distinct from the engineering ECR list because they are
 * different objects with different owners: a CCR may *raise* an ECR, but a
 * customer asking for something is not the same event as engineering deciding
 * to change it.
 */
export function ProjectCustomerChangePanel({
  projectId,
  canEdit,
  canApprove,
  currentUserId,
}: Props) {
  const [changes, setChanges] = useState<CustomerChange[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [quoteDrafts, setQuoteDrafts] = useState<Record<string, string>>({});
  const [leadTimeDrafts, setLeadTimeDrafts] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    const response = await fetch(`/api/projects/${projectId}/customer-changes`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    setChanges(body.items ?? []);
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/projects/${projectId}/customer-changes`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await readError(response));
        const body = await response.json();
        if (cancelled) return;
        setChanges(body.items ?? []);
        setState("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(failure instanceof Error ? failure.message : "客户变更暂不可用");
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const act = useCallback(
    async (operation: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await operation();
        await reload();
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : "操作失败，请重试");
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">正在加载客户变更…</p>;
  }

  if (state === "error") {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <div className="space-y-4" data-testid="customer-change-panel">
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <h3 className="text-sm font-semibold">客户变更请求（CCR）</h3>

      {changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">尚无客户变更请求。</p>
      ) : (
        <ul className="space-y-3">
          {changes.map((change) => {
            const base = `/api/projects/${projectId}/customer-changes/${change.id}`;
            const counts = change.impact_analysis?.counts;
            // The quote drafter must not approve their own reply; the server
            // enforces four eyes and the button simply is not offered.
            const isDrafter = change.reply_drafted_by_user_id === currentUserId;
            return (
              <li key={change.id} className="rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm">{change.code}</span>
                  <span className="font-medium">{change.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {STATUS_LABELS[change.status] ?? change.status}
                  </span>
                  {change.engineering_change_request_id ? (
                    <span className="text-xs text-muted-foreground">· 已关联 ECR</span>
                  ) : null}
                </div>

                {counts ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    影响：需求 {counts.requirements ?? 0} · 规格{" "}
                    {counts.specifications ?? 0} · 测试用例 {counts.test_cases ?? 0} ·
                    需复测 {change.impact_analysis?.retest_required ?? 0}
                  </p>
                ) : null}

                {change.quote_note ? (
                  <p className="mt-1 text-sm">
                    报价：{change.quote_note}（交期 {change.lead_time_days} 天）
                  </p>
                ) : null}

                <div className="mt-2 flex flex-wrap gap-2">
                  {canEdit && change.status === "received" ? (
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => void act(() => post(`${base}/analyze`, {}))}
                    >
                      分析影响
                    </Button>
                  ) : null}

                  {canEdit && change.status === "impact_analyzed" ? (
                    <>
                      <input
                        aria-label={`${change.code} 报价说明`}
                        className="h-9 flex-1 rounded-md border px-2 text-sm"
                        placeholder="报价说明"
                        value={quoteDrafts[change.id] ?? ""}
                        onChange={(event) =>
                          setQuoteDrafts((drafts) => ({
                            ...drafts,
                            [change.id]: event.target.value,
                          }))
                        }
                      />
                      <input
                        aria-label={`${change.code} 交期天数`}
                        className="h-9 w-24 rounded-md border px-2 text-sm"
                        inputMode="numeric"
                        placeholder="交期天数"
                        value={leadTimeDrafts[change.id] ?? ""}
                        onChange={(event) =>
                          setLeadTimeDrafts((drafts) => ({
                            ...drafts,
                            [change.id]: event.target.value,
                          }))
                        }
                      />
                      <Button
                        size="sm"
                        disabled={
                          busy ||
                          !(quoteDrafts[change.id] ?? "").trim() ||
                          !/^\d+$/.test(leadTimeDrafts[change.id] ?? "")
                        }
                        onClick={() =>
                          void act(() =>
                            post(`${base}/reply`, {
                              quote_note: (quoteDrafts[change.id] ?? "").trim(),
                              lead_time_days: Number(leadTimeDrafts[change.id]),
                            }),
                          )
                        }
                      >
                        起草答复
                      </Button>
                    </>
                  ) : null}

                  {canApprove && change.status === "reply_drafted" && !isDrafter ? (
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => void act(() => post(`${base}/reply/approve`, {}))}
                    >
                      批准对外答复
                    </Button>
                  ) : null}
                  {change.status === "reply_drafted" && isDrafter ? (
                    <span className="text-xs text-muted-foreground">
                      需另一人批准对外答复（四眼原则）
                    </span>
                  ) : null}

                  {canEdit && change.status === "reply_approved" ? (
                    <>
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          void act(() =>
                            post(`${base}/customer-decision`, { accepted: true }),
                          )
                        }
                      >
                        客户接受
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          void act(() =>
                            post(`${base}/customer-decision`, { accepted: false }),
                          )
                        }
                      >
                        客户拒绝
                      </Button>
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
