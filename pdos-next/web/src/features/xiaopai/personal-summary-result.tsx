"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { parsePersonalSummary, summaryFromRun, summaryHref, type PersonalSummary, type SummaryItem } from "@/lib/personal-summary";
import type { WorkspaceApi } from "@/lib/automation-rules";

function Entry({ item }: { item: SummaryItem }) {
  const href = summaryHref(item), named = item.facts.latest_named_status;
  const namedText = named && typeof named === "object" && "fact_summary" in named && typeof named.fact_summary === "string" ? named.fact_summary : null;
  return <article className="min-w-0 space-y-3 rounded-lg border border-border bg-background p-3 sm:p-4">
    <h4 className="break-words font-medium">{item.title}</h4>
    <dl className="space-y-3 text-sm">
      <div><dt className="text-muted-foreground">发生了什么变化</dt><dd className="mt-1 whitespace-pre-wrap break-words">{item.change.text}{namedText && <p className="mt-2">最新具名记录：{namedText}</p>}</dd></div>
      <div><dt className="text-muted-foreground">为什么与我有关</dt><dd className="mt-1 whitespace-pre-wrap break-words">{item.relationship.text}</dd></div>
      <div><dt className="text-muted-foreground">接下来谁做什么</dt><dd className="mt-1 whitespace-pre-wrap break-words">{item.next_step.text}<p className="mt-1">{item.next_step.responsible ? `具名责任人：${item.next_step.responsible.name ?? item.next_step.responsible.id}` : "下一责任人未单独登记。"}</p>{item.next_step.recorded_by && <p className="mt-1 text-muted-foreground">具名记录人：{item.next_step.recorded_by.name ?? item.next_step.recorded_by.id}</p>}</dd></div>
      <div><dt className="text-muted-foreground">从哪里继续</dt><dd className="mt-1">{href ? <a className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline" href={href}>查看原事项<ArrowRight aria-hidden="true" size={14}/></a> : "原事项链接当前不可用。"}</dd></div>
    </dl>
    <dl className="space-y-1 text-sm text-muted-foreground">
      {!!item.facts.commitment_as_recorded && typeof item.facts.commitment_as_recorded === "object" && <><div><dt>原登记数量</dt><dd>{"quantity" in item.facts.commitment_as_recorded && typeof item.facts.commitment_as_recorded.quantity === "number" ? item.facts.commitment_as_recorded.quantity : "未知"}</dd></div><div><dt>原约定时间</dt><dd>{"expected_at" in item.facts.commitment_as_recorded && typeof item.facts.commitment_as_recorded.expected_at === "string" ? item.facts.commitment_as_recorded.expected_at : "未知"}</dd></div></>}
      {"promised_at_as_recorded" in item.facts && <div><dt>原承诺时间</dt><dd>{typeof item.facts.promised_at_as_recorded === "string" ? item.facts.promised_at_as_recorded : "未知"}</dd></div>}
      {typeof item.facts.issue_status_as_recorded === "string" && <div><dt>原问题登记状态</dt><dd>{item.facts.issue_status_as_recorded}</dd></div>}
      {item.facts.needs_recheck_as_recorded === true && <div><dt>原问题核对标记</dt><dd>原记录标记需重核，请在原事项核对当前依据。</dd></div>}
      {"opened_at_as_recorded" in item.facts && <div><dt>原开单时点</dt><dd>{typeof item.facts.opened_at_as_recorded === "string" ? item.facts.opened_at_as_recorded : "未登记"}</dd></div>}
      {"risk_as_recorded" in item.facts && <div><dt>原问题登记风险（不作项目健康度）</dt><dd>{typeof item.facts.risk_as_recorded === "string" ? item.facts.risk_as_recorded : "未登记"}</dd></div>}
      {"observation_until_as_recorded" in item.facts && <><div><dt>CAPA 原有效性观察截止</dt><dd>{typeof item.facts.observation_until_as_recorded === "string" ? item.facts.observation_until_as_recorded : "未登记"}</dd></div><div><dt>措施完成期限</dt><dd>未单独登记</dd></div></>}
      {typeof item.facts.baseline_latest_finish_as_recorded === "string" && <><div><dt>已批准基线预计</dt><dd>{item.facts.baseline_latest_finish_as_recorded}</dd></div><div><dt>日期含义</dt><dd>预计日期不代表承诺、实际完成或门禁通过。</dd></div></>}
      {typeof item.facts.due_at_as_recorded === "string" && <div><dt>{item.facts.date_kind === "internal_check" ? "内部检查时间（不是对方承诺）" : "原登记时间"}</dt><dd>{item.facts.due_at_as_recorded}</dd></div>}
    </dl>
    <p className="text-xs text-muted-foreground">可能影响：{item.possible_impact} · 记录时点 <time dateTime={item.recorded_at}>{new Date(item.recorded_at).toLocaleString("zh-CN")}</time></p>
    <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">原来源与版本</summary><p className="mt-2 break-all">{item.kind} · {item.object.id}{item.object.version_id && <> · 固定事实 {item.object.version_id}</>}{item.object.revision && <> · v{item.object.revision}</>}</p><p>摘要生成时点 {item.as_of}；历史不替代当前业务事实。</p></details>
  </article>;
}
export function PersonalSummaryResult({ summary }: { summary: PersonalSummary }) {
  return <section className="min-w-0 space-y-4" aria-label="本人结构摘要"><header><h3 className="font-semibold">我的工作摘要</h3><p className="mt-1 text-sm text-muted-foreground">生成于 <time dateTime={summary.as_of}>{new Date(summary.as_of).toLocaleString("zh-CN")}</time> · 按本人当时可读范围整理，当前办理请继续到原事项。</p></header>
    {!summary.complete && <p role="status" className="rounded-lg border border-border bg-muted/30 p-3 text-sm">本次覆盖不完整{summary.omitted_current_items ? `，还有 ${summary.omitted_current_items} 条当前事项未列入` : ""}。未读取到的来源不按没有变化处理。</p>}
    {summary.groups.map(group => <section key={group.id} className="space-y-3" aria-label={group.title}><h4 className="text-sm font-semibold">{group.title}</h4>{group.items.map(item => <Entry key={item.id} item={item}/>)}{group.unchanged_items.length > 0 && <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm text-muted-foreground">持续未变的事项（{group.unchanged_items.length}）</summary><div className="mt-3 space-y-3">{group.unchanged_items.map(item => <Entry key={item.id} item={item}/>)}</div></details>}{!group.items.length && !group.unchanged_items.length && <p className="text-sm text-muted-foreground">本次可读范围内暂无此组条目。</p>}</section>)}
    <details className="text-sm text-muted-foreground"><summary className="cursor-pointer">本次覆盖</summary><ul className="mt-2 space-y-1">{summary.coverage.map(c => <li key={c.source} className="break-words">{c.source}：已读 {c.returned}{c.available === null ? "" : ` / ${c.available}`}{c.has_more ? "，后续尚未全部读取" : ""}{c.unavailable ? `，${c.unavailable} 项当前不可读` : ""}</li>)}</ul><p className="mt-2">未再列入的事项不代表已完成。健康度和风险等级以原具名业务记录为准。</p></details>
  </section>;
}
/** Small Xiaopai mount hook: this renderer does not fetch or bypass server READ. */
export function PersonalSummaryRunResult({ output, principalId }: { output: unknown; principalId: string }) {
  if (!output || typeof output !== "object" || !("result" in output) || !output.result || typeof output.result !== "object" || !("personal_summary" in output.result)) return null;
  let value: PersonalSummary;
  try { value = parsePersonalSummary(output.result.personal_summary, principalId); } catch { return <p role="alert">摘要结构或本人范围无法核对，原内容未显示。</p>; }
  return <PersonalSummaryResult summary={value}/>;
}
type SummaryReadProps = { api: WorkspaceApi; principalId: string; categoryId: string; runId: string; onRead?: () => void };
export function SummaryRunReader(props: SummaryReadProps) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  return <ScopedSummaryRunReader key={`${props.principalId}:${props.categoryId}:${props.runId}:${binding.revision}`} {...props}/>;
}
function ScopedSummaryRunReader({ api, principalId, categoryId, runId, onRead }: SummaryReadProps) {
  const [data, setData] = useState<{ api: WorkspaceApi; principalId: string; categoryId: string; runId: string; summary: PersonalSummary } | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const epoch = useRef({ sequence: 0, alive: true });
  useEffect(() => { const fence = epoch.current; ++fence.sequence; fence.alive = true; return () => { fence.alive = false; }; }, [api, principalId, categoryId, runId]);
  async function read() { const stamp = ++epoch.current.sequence; setData(null); setError(""); setBusy(true); try { const value = await api<unknown>(`v1/categories/${categoryId}/agent-runs/${runId}`); if (epoch.current.alive && stamp === epoch.current.sequence) { setData({ api, principalId, categoryId, runId, summary: summaryFromRun(value, principalId, runId) }); onRead?.(); } } catch (e) { if (epoch.current.alive && stamp === epoch.current.sequence) { setData(null); setError(e instanceof Error ? e.message : "摘要当前不可读取。"); } } finally { if (epoch.current.alive && stamp === epoch.current.sequence) setBusy(false); } }
  return <div className="space-y-3"><Button size="sm" variant="outline" disabled={busy} onClick={() => void read()}><ArrowClockwise aria-hidden="true"/>{busy ? "正在核对原摘要…" : data ? "重新核对读取权限" : "读取本次结构摘要"}</Button>{error && <p role="alert" className="text-sm text-destructive">{error}；摘要正文未显示。</p>}{data && data.api === api && data.principalId === principalId && data.categoryId === categoryId && data.runId === runId && <PersonalSummaryResult summary={data.summary}/>}</div>;
}
