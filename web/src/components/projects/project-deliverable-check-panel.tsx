"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

type CheckItem = {
  id: string;
  phase_code: string | null;
  phase_name: string | null;
  task_name: string | null;
  deliverable_name: string;
  requirement: string;
  is_gate: boolean;
  status: string;
  evidence_reference: string | null;
  completion_note: string | null;
};

type LoadState = "loading" | "ready" | "error";

type Props = {
  projectId: string;
  canManage: boolean;
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待完成",
  completed: "已完成",
  not_applicable: "不适用",
};

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail?.message ?? "操作失败";
  } catch {
    return "操作失败";
  }
}

/**
 * Deliverable checklist — the other half of the 「Gate·交付物」 tab.
 *
 * Two server rules shape this UI, both checked against the service rather than
 * assumed: completing *any* item requires an evidence reference, and a gate
 * item can never be waived as not-applicable ("hard gate cannot be bypassed").
 * Waiving a non-gate item requires a stated reason. The panel refuses the same
 * things the server does, so nobody meets these rules as a submit-time error.
 */
export function ProjectDeliverableCheckPanel({ projectId, canManage }: Props) {
  const [items, setItems] = useState<CheckItem[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [evidenceDrafts, setEvidenceDrafts] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    const response = await fetch(`/api/projects/${projectId}/deliverable-checks`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    setItems(body.items ?? []);
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/projects/${projectId}/deliverable-checks`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await readError(response));
        const body = await response.json();
        if (cancelled) return;
        setItems(body.items ?? []);
        setState("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(failure instanceof Error ? failure.message : "交付物检查暂不可用");
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

  const resolve = useCallback(
    async (item: CheckItem, status: "completed" | "not_applicable") => {
      const entered = (evidenceDrafts[item.id] ?? "").trim();
      // The same field carries the evidence when completing and the reason when
      // waiving, because the server wants exactly one of them in each case.
      const payload =
        status === "completed"
          ? { status, evidence_reference: entered }
          : { status, note: entered };
      const response = await fetch(
        `/api/projects/${projectId}/deliverable-checks/items/${item.id}/resolve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) throw new Error(await readError(response));
      setEvidenceDrafts((drafts) => ({ ...drafts, [item.id]: "" }));
    },
    [evidenceDrafts, projectId],
  );

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">正在加载交付物检查…</p>;
  }

  if (state === "error") {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  const pending = items.filter((item) => item.status === "pending");
  const gatePending = pending.filter((item) => item.is_gate);

  return (
    <div className="space-y-4" data-testid="deliverable-check-panel">
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">交付物检查</h3>
        <span className="text-xs text-muted-foreground">
          共 {items.length} 项 · 待完成 {pending.length} 项 · 其中 Gate 必需{" "}
          {gatePending.length} 项
        </span>
        {canManage ? (
          <Button
            className="ml-auto"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const response = await fetch(
                  `/api/projects/${projectId}/deliverable-checks/prepare`,
                  { method: "POST" },
                );
                if (!response.ok) throw new Error(await readError(response));
              })
            }
          >
            按模板生成检查项
          </Button>
        ) : null}
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          尚无检查项。可按项目所用模板生成。
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="rounded-md border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{item.deliverable_name}</span>
                {item.is_gate ? (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">
                    Gate 必需
                  </span>
                ) : null}
                <span className="text-xs text-muted-foreground">
                  {item.phase_name ?? item.phase_code ?? "—"}
                  {item.task_name ? ` · ${item.task_name}` : ""} ·{" "}
                  {STATUS_LABELS[item.status] ?? item.status}
                </span>
              </div>
              {item.evidence_reference ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  证据：{item.evidence_reference}
                </p>
              ) : null}

              {canManage && item.status === "pending" ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  <input
                    aria-label={`${item.deliverable_name} 证据或理由`}
                    className="h-9 flex-1 rounded-md border px-2 text-sm"
                    placeholder={
                      item.is_gate ? "完成证据引用（必填）" : "完成证据引用，或不适用的理由"
                    }
                    value={evidenceDrafts[item.id] ?? ""}
                    onChange={(event) =>
                      setEvidenceDrafts((drafts) => ({
                        ...drafts,
                        [item.id]: event.target.value,
                      }))
                    }
                  />
                  <Button
                    size="sm"
                    // Completing anything without evidence is refused server-side.
                    disabled={busy || !(evidenceDrafts[item.id] ?? "").trim()}
                    onClick={() => void act(() => resolve(item, "completed"))}
                  >
                    标记完成
                  </Button>
                  {/* 硬闸不可绕过：a gate item has no waive path at all. */}
                  {item.is_gate ? (
                    <span className="self-center text-xs text-muted-foreground">
                      Gate 必需项不可标记不适用
                    </span>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy || !(evidenceDrafts[item.id] ?? "").trim()}
                      onClick={() => void act(() => resolve(item, "not_applicable"))}
                    >
                      标记不适用
                    </Button>
                  )}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
