"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Reason = { code: string; message: string };
type Ratio = { numerator: number; denominator: number; basis_points: number | null; required: number; met: boolean | null };
type Result = { status: string; criteria: { minimum_handled_runs: { actual: number; required: number; met: boolean }; followup_complete: boolean; confirmation: Ratio; withdrawal: Ratio }; reasons: Reason[] };
type Current = { checked_at: string; protocol_id: string; latest_collection_id: string | null; latest_collection_as_of: string | null; state: "current" | "blocked" | "unavailable"; original_result: Result | null; fresh_result: Result | null; reasons: Reason[]; operational_requirements: Reason[]; notice: string };
const states = { current: "当前核算条件满足", blocked: "当前条件未满足", unavailable: "当前证据不足，暂无法核对" };
const statuses: Record<string, string> = { meets_candidate_criteria: "符合候选数值要求", insufficient_evidence: "证据不足", does_not_meet_criteria: "未达到原登记要求" };
function record(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("当前核对资料不完整，请重新核对"); return value; }
function text(value: unknown): string { if (typeof value !== "string") throw new Error("当前核对资料不完整，请重新核对"); return value; }
function flag(value: unknown): boolean { if (typeof value !== "boolean") throw new Error("当前核对状态不完整，请重新核对"); return value; }
function count(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("当前核对数值不完整，请重新核对"); return value; }
function rate(value: unknown): number { const result = count(value); if (result > 10000) throw new Error("当前核对比率不完整，请重新核对"); return result; }
function stamp(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw new Error("当前核对时间不完整，请重新核对"); return result; }
function reasons(value: unknown): Reason[] { if (!Array.isArray(value)) throw new Error("当前核对原因不完整"); return value.map(value => { const item = record(value); return { code: text(item.code), message: text(item.message) }; }); }
function ratio(value: unknown): Ratio { const item = record(value); return { numerator: count(item.numerator), denominator: count(item.denominator), basis_points: item.basis_points === null ? null : rate(item.basis_points), required: rate(item.required), met: item.met === null ? null : flag(item.met) }; }
function result(value: unknown): Result | null {
  if (value === null) return null;
  const item = record(value), criteria = record(item.criteria), minimum = record(criteria.minimum_handled_runs);
  return { status: text(item.status), criteria: { minimum_handled_runs: { actual: count(minimum.actual), required: count(minimum.required), met: flag(minimum.met) }, followup_complete: flag(criteria.followup_complete), confirmation: ratio(criteria.confirmation), withdrawal: ratio(criteria.withdrawal) }, reasons: reasons(item.reasons) };
}
function current(value: unknown, protocolId: string): Current {
  const row = record(value), state = text(row.state);
  if (row.protocol_id !== protocolId || row.qualification_granted !== false || !Object.hasOwn(states, state)) throw new Error("当前核对回执与原登记或资格口径不匹配，请重新核对");
  return { checked_at: stamp(row.checked_at), protocol_id: protocolId, latest_collection_id: row.latest_collection_id === null ? null : text(row.latest_collection_id), latest_collection_as_of: row.latest_collection_as_of === null ? null : stamp(row.latest_collection_as_of), state: state as Current["state"], original_result: result(row.original_result), fresh_result: result(row.fresh_result), reasons: reasons(row.reasons), operational_requirements: reasons(row.operational_requirements), notice: text(row.notice) };
}
function percent(value: number | null) { return value === null ? "—" : `${value / 100}%`; }
function assessment(value: boolean | null) { return value === null ? "无法判断" : value ? "达到此项要求" : "尚未达到此项要求"; }
function ReasonList({ values }: { values: Reason[] }) { return <ul className="space-y-1.5 leading-5">{values.map((item, index) => <li className="break-words" key={`${item.code}-${index}`}>{item.message}</li>)}</ul>; }
function ResultView({ title, value }: { title: string; value: Result | null }) {
  return <section aria-label={title} className="min-w-0 space-y-2 border-t pt-3"><h4 className="font-medium">{title}</h4>{value ? <><p className="font-medium text-primary">{statuses[value.status] ?? "结果待核对"}</p><dl className="space-y-2"><div><dt className="text-muted-foreground">办理数</dt><dd>{value.criteria.minimum_handled_runs.actual} / {value.criteria.minimum_handled_runs.required} · {assessment(value.criteria.minimum_handled_runs.met)}</dd></div><div><dt className="text-muted-foreground">跟踪时长</dt><dd>{value.criteria.followup_complete ? "已完成原登记跟踪时长" : "尚未完成原登记跟踪时长"}</dd></div>{(["confirmation", "withdrawal"] as const).map(key => { const item = value.criteria[key]; return <div key={key}><dt className="text-muted-foreground">{key === "confirmation" ? "确认比例" : "撤回比例"}</dt><dd className="mt-1 space-y-1"><p className="text-base tabular-nums">{percent(item.basis_points)}</p><p>{item.numerator} / {item.denominator} · 原要求{key === "confirmation" ? "不低于" : "不高于"} {percent(item.required)}</p><p>{assessment(item.met)}</p></dd></div>; })}</dl><ReasonList values={value.reasons} /></> : <p className="text-muted-foreground">暂无可核对结果，缺少的依据见下方说明。</p>}</section>;
}
export function AiIssueTrialCurrent({ projectId, protocolId }: { projectId: string; protocolId: string }) { return <Check key={`${projectId}:${protocolId}`} projectId={projectId} protocolId={protocolId} />; }
function Check({ projectId, protocolId }: { projectId: string; protocolId: string }) {
  const [data, setData] = useState<Current | null>(null), [error, setError] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const active = useRef(true), locked = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function check() {
    if (locked.current) return; locked.current = true; setBusy(true); setError(null); setData(null);
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-trials/${encodeURIComponent(protocolId)}/current`, { method: "GET", cache: "no-store" });
      const body: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new Error(isRecord(body) && typeof body.detail === "string" ? body.detail : isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "当前条件暂不可核对，请稍后重试");
      const value = current(body, protocolId); if (active.current) setData(value);
    } catch (error) { if (active.current) setError(error instanceof Error ? error.message : "当前条件暂不可核对，请稍后重试"); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  return <details className="min-w-0 border-t pt-3"><summary className="cursor-pointer text-sm font-medium text-primary">核对当前条件</summary><div className="mt-3 space-y-3 text-xs"><p className="leading-5 text-muted-foreground">手动读取当前条件，对照原采集与当前重算。核对不修改原登记或旧回执，也不授予自动写入资格。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void check()}>{data ? "重新核对当前条件" : "核对当前条件"}</Button>{busy && <p role="status">正在读取当前条件并重新核算…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}{data && <><p className="font-medium text-primary">{states[data.state]}</p><p className="text-muted-foreground">核对时间：{new Date(data.checked_at).toLocaleString("zh-CN")}</p><p className="text-muted-foreground">{data.latest_collection_id && data.latest_collection_as_of ? `原采集截至：${new Date(data.latest_collection_as_of).toLocaleString("zh-CN")}` : "尚无可回查的原采集"}</p><p className="leading-5 text-muted-foreground">{data.notice}</p><div className="grid gap-4 sm:grid-cols-2"><ResultView title="原采集结果" value={data.original_result} /><ResultView title="当前重算结果" value={data.fresh_result} /></div>{data.reasons.length > 0 && <section aria-label="当前核对说明" className="space-y-2 border-t pt-3"><h4 className="font-medium">当前核对说明</h4><ReasonList values={data.reasons} /></section>}{data.operational_requirements.length > 0 && <section aria-label="后续运行要求" className="space-y-2 border-t pt-3"><h4 className="font-medium">后续运行要求</h4><p className="leading-5 text-muted-foreground">抽检等要求用于后续运行，不作为逐次确认办理的前置条件。</p><ReasonList values={data.operational_requirements} /></section>}<p className="leading-5 text-primary">当前核对不授予自动写入资格。数值条件满足不代表真实服务商调用已获证明，也不代表自动建单已启用。</p></>}</div></details>;
}
