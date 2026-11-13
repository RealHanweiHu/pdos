"use client";

/* 要我决定 · 小Pai 运行 (D78, P77): pending candidates and unanswered questions grouped
   by run, and the whole-package confirmation of one run's candidates (D77). Every item
   keeps its own preview, token and command; the server checks each one again. */
import { useCallback, useEffect, useState } from "react";
import { candidateLabels, sameCandidateCommand, type DomainCommand } from "@/lib/domain-candidate";
import { parseRunDecisions, runDecisionsPath, type RunCandidate, type RunDecision, type RunDecisionsApi, type RunDecisionsPage } from "./run-decisions-read";

export type { RunDecisionsApi, RunQuestion, RunCandidate, RunDecision, RunDecisionsPage } from "./run-decisions-read";
export { parseRunDecisions, runDecisionsPath, runTitle, decideHref, decideTarget, initialSelection } from "./run-decisions-read";
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export const candidateName = (item: RunCandidate) => candidateLabels[item.operation ?? ""] ?? "小Pai 候选";

export type PackagePreview = { eventId: string; operation: string; command: DomainCommand; review: Record<string, unknown>; expiresAt: string | null };
export type PackageFailure = { eventId: string; operation: string; message: string };
const message = (failure: unknown) => {
  const text = (failure as Error)?.message;
  return text && !/^(Failed to fetch|Load failed)$/.test(text) ? text : "连接中断，请稍后重新核对。";
};
/** Each selected candidate is previewed on its own; a failed preview stays out of the package. */
export async function previewPackage(api: RunDecisionsApi, item: RunDecision, selected: string[]): Promise<{ previews: PackagePreview[]; failures: PackageFailure[] }> {
  if (!item.category) throw new Error("个人运行没有可整包确认的候选。");
  const root = `v1/categories/${item.category.id}`;
  const chosen = item.candidates.filter(entry => entry.package && entry.command && selected.includes(entry.event_id));
  const outcomes = await Promise.allSettled(chosen.map(async entry => {
    const result = await api<{ command: DomainCommand; review: Record<string, unknown>; expires_at: string | null; confirmation_token?: string }>(`${root}/commands/preview`, entry.command);
    if (!result?.command || !sameCandidateCommand(result.command, entry.command!) || !result.command.payload.confirmation_token || !record(result.review))
      throw new Error("预览与原候选不一致，请刷新后重新核对。");
    return { eventId: entry.event_id, operation: entry.operation ?? "", command: result.command, review: result.review, expiresAt: result.expires_at ?? null };
  }));
  const previews: PackagePreview[] = [], failures: PackageFailure[] = [];
  outcomes.forEach((outcome, index) => {
    const entry = chosen[index];
    if (outcome.status === "fulfilled") previews.push(outcome.value);
    else failures.push({ eventId: entry.event_id, operation: entry.operation ?? "", message: message(outcome.reason) });
  });
  return { previews, failures };
}

export type PackageStatus = "adopted" | "refused" | "failed" | "unknown" | "not_attempted";
export type PackageResultItem = { event_id: string; operation: string; status: PackageStatus; receipt?: { id: string; operation: string; subject_id: string; subject_type: string }; error?: { code: string; reason: string | null; message: string } };
export type PackageResult = { run_id: string; items: PackageResultItem[] } & Record<PackageStatus, number>;
const statuses: PackageStatus[] = ["adopted", "refused", "failed", "unknown", "not_attempted"];
export function parsePackageResult(value: unknown, runId: string, sent: PackagePreview[]): PackageResult {
  if (!record(value) || value.run_id !== runId || !Array.isArray(value.items) || value.items.length !== sent.length) throw new Error("整包确认结果未完整取得，请刷新核对每条候选。");
  value.items.forEach((entry, index) => {
    if (!record(entry) || entry.event_id !== sent[index].eventId || !statuses.includes(entry.status as PackageStatus)
      || entry.status === "adopted" && !(record(entry.receipt) && typeof entry.receipt.id === "string" && entry.receipt.operation === sent[index].command.operation))
      throw new Error("整包确认结果与提交的候选不一致，请刷新核对。");
  });
  for (const status of statuses) if (value[status] !== value.items.filter(entry => (entry as PackageResultItem).status === status).length) throw new Error("整包确认结果的计数不一致，请刷新核对。");
  return value as PackageResult;
}
export async function confirmPackage(api: RunDecisionsApi, item: RunDecision, previews: PackagePreview[]): Promise<PackageResult> {
  if (!item.category || !previews.length) throw new Error("没有可确认的候选。");
  const value = await api<unknown>(`v1/categories/${item.category.id}/agent-runs/${item.run_id}/candidates/confirm`, {
    items: previews.map(preview => ({ event_id: preview.eventId, command: preview.command })),
  });
  return parsePackageResult(value, item.run_id, previews);
}
export const statusNames: Record<PackageStatus, string> = { adopted: "已保存", refused: "未进入整包", failed: "未保存", unknown: "结果待核对", not_attempted: "未办理" };

export type RunDecisionsState = { status: "loading" | "ready" | "error"; page: RunDecisionsPage | null; error: string; retry: () => void };
export function useRunDecisions(api: RunDecisionsApi, principalId: string, reload: number): RunDecisionsState {
  const [attempt, setAttempt] = useState(0);
  const scope = JSON.stringify([principalId, reload, attempt]);
  const [stored, setStored] = useState<{ scope: string; api: RunDecisionsApi; page: RunDecisionsPage | null; error: string } | null>(null);
  useEffect(() => {
    let live = true;
    api<unknown>(runDecisionsPath).then(value => {
      if (live) setStored({ scope, api, page: parseRunDecisions(value, principalId), error: "" });
    }).catch(failure => { if (live) setStored({ scope, api, page: null, error: message(failure) }); });
    return () => { live = false; };
  }, [api, principalId, scope]);
  const retry = useCallback(() => setAttempt(value => value + 1), []);
  const current = stored?.scope === scope && stored.api === api ? stored : null;
  return { status: !current ? "loading" : current.error ? "error" : "ready", page: current?.page ?? null, error: current?.error ?? "", retry };
}
