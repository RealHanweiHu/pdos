"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

type Props = {
  gateReady?: boolean;
  projectId: string;
  gateId: string;
  gateLabel: string;
  onRecorded: () => void;
};

type Outcome = "approved" | "conditional" | "hold" | "rejected";

const OUTCOMES: ReadonlyArray<{ value: Outcome; label: string }> = [
  { value: "approved", label: "通过" },
  { value: "conditional", label: "有条件通过" },
  { value: "hold", label: "暂缓" },
  { value: "rejected", label: "否决" },
];

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail?.message ?? "记录 Gate 决策失败";
  } catch {
    return "记录 Gate 决策失败";
  }
}

/**
 * Records the gate decision — the outcome the whole review exists to produce.
 *
 * The panel could open sign-off rounds and collect sign-offs but had no way to
 * write the decision itself, so a completed review left no verdict.
 *
 * A conditional pass must carry at least one condition and a plain pass must
 * carry none; the server enforces both, and this form mirrors it so the rule
 * is visible before submitting rather than after.
 */
export function ProjectGateDecisionForm({
  gateReady = true,
  projectId,
  gateId,
  gateLabel,
  onRecorded,
}: Props) {
  const [outcome, setOutcome] = useState<Outcome>(gateReady ? "approved" : "hold");
  const [rationale, setRationale] = useState("");
  const [conditionTitle, setConditionTitle] = useState("");
  const [conditionOwner, setConditionOwner] = useState("");
  const [conditionDue, setConditionDue] = useState("");
  const [conditionEvidence, setConditionEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [members, setMembers] = useState<{ user_id: string; display_name: string }[] | null>(null);
  const [loadingMembers, setLoadingMembers] = useState(false);
  async function loadMembers() {
    setLoadingMembers(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/gates/${gateId}/assignment-options`, { cache: "no-store" });
      const body = await response.json().catch(() => null);
      if (!response.ok || !Array.isArray(body?.members)) throw new Error(body?.detail?.message ?? "项目成员暂不可用，请重试");
      setMembers(body.members);
    } catch (e) { setError(e instanceof Error ? e.message : "读取项目成员失败"); }
    finally { setLoadingMembers(false); }
  }
  const needsCondition = outcome === "conditional";
  const conditionComplete =
    conditionTitle.trim() !== "" &&
    conditionOwner.trim() !== "" &&
    conditionDue.trim() !== "" &&
    conditionEvidence.trim() !== "";

  const submittable =
    rationale.trim() !== "" && (!needsCondition || (conditionComplete && members?.some(member => member.user_id === conditionOwner))) && (gateReady || outcome === "hold" || outcome === "rejected") && !busy;

  return (
    <section className="space-y-2 rounded-md border p-3">
      <h4 className="text-sm font-semibold">记录 Gate 决策 · {gateLabel}</h4>
      {!gateReady && <p className="text-sm text-muted-foreground">仍有就绪缺项，可记录暂缓或否决；通过及有条件通过须先满足就绪条件。</p>}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="flex flex-wrap gap-2">
        <select
          aria-label="Gate 决策结论"
          className="h-9 rounded-md border px-2 text-sm"
          value={outcome}
          onChange={(event) => { const next = event.target.value as Outcome; setOutcome(next); if (next === "conditional" && !members) void loadMembers(); }}
        >
          {OUTCOMES.map((option) => (
            <option key={option.value} value={option.value} disabled={!gateReady && (option.value === "approved" || option.value === "conditional")}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <textarea
        aria-label="决策理由"
        className="min-h-16 w-full rounded-md border p-2 text-sm"
        placeholder="决策理由（必填）"
        value={rationale}
        onChange={(event) => setRationale(event.target.value)}
      />

      {needsCondition ? (
        <div className="space-y-2 rounded-md border border-dashed p-2">
          <p className="text-xs text-muted-foreground">
            有条件通过必须写明条件：做什么、谁负责、何时完成、以什么证据关闭。
          </p>
          <input
            aria-label="条件内容"
            className="h-9 w-full rounded-md border px-2 text-sm"
            placeholder="条件内容"
            value={conditionTitle}
            onChange={(event) => setConditionTitle(event.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <select aria-label="条件负责人" className="h-11 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm" disabled={loadingMembers || busy} value={conditionOwner} onChange={event => setConditionOwner(event.target.value)}>
              <option value="">{loadingMembers ? "正在读取项目成员…" : "选择本项目负责人"}</option>
              {members?.map(member => <option key={member.user_id} value={member.user_id}>{member.display_name}</option>)}
            </select>
            {!members && !loadingMembers && <Button type="button" variant="outline" size="sm" onClick={() => void loadMembers()}>重新读取成员</Button>}
            <input
              aria-label="条件截止日期"
              className="h-9 w-44 rounded-md border px-2 text-sm"
              placeholder="截止日期 YYYY-MM-DD"
              type="date"
              value={conditionDue}
              onChange={(event) => setConditionDue(event.target.value)}
            />
          </div>
          <input
            aria-label="条件关闭证据"
            className="h-9 w-full rounded-md border px-2 text-sm"
            placeholder="关闭证据"
            value={conditionEvidence}
            onChange={(event) => setConditionEvidence(event.target.value)}
          />
        </div>
      ) : null}

      <Button
        size="sm"
        disabled={!submittable}
        onClick={() => {
          setBusy(true);
          setError(null);
          void (async () => {
            try {
              const response = await fetch(
                `/api/projects/${projectId}/gates/${gateId}/decisions`,
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    status: outcome,
                    rationale: rationale.trim(),
                    // A plain pass must carry no conditions at all, so the key
                    // is omitted rather than sent as an empty array.
                    ...(needsCondition
                      ? {
                          conditions: [
                            {
                              title: conditionTitle.trim(),
                              owner_user_id: conditionOwner.trim(),
                              due_date: conditionDue,
                              closure_evidence: conditionEvidence.trim(),
                            },
                          ],
                        }
                      : {}),
                  }),
                },
              );
              if (!response.ok) {
                setError(await readError(response));
                return;
              }
              setRationale("");
              setConditionTitle("");
              setConditionOwner("");
              setConditionDue("");
              setConditionEvidence("");
              onRecorded();
            } catch {
              setError("连接中断，决策结果尚未确认；请刷新 Gate 核对后再继续。");
            } finally {
              setBusy(false);
            }
          })();
        }}
      >
        记录决策
      </Button>
    </section>
  );
}
