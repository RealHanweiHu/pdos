"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { DiscussionResearch } from "./discussion-research";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

import { ChangeDiscussionBrief, DiscussionInitiation, DiscussionStatement as Statement } from "./change-discussion-brief";

const strings = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const date = (v: unknown) => typeof v === "string" ? new Date(v).toLocaleString("zh-CN") : "未记录";
const statuses: Record<string, string> = { preparing: "判断是否需要多专业讨论", convened: "已排队", arguing: "讨论中", completed: "固定轮次完成", interrupted: "已中断", cancelled: "已停止", budget_stopped: "预算已停止", converged: "已收束", briefed: "已有摘要草稿" };
export function ChangeDiscussionRuns({ projectId, ecrId, source, requestedOpen = false, focusedRunId }: { projectId: string; ecrId?: string; source: Row; requestedOpen?: boolean; focusedRunId?: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [open, setOpen] = useState(false), [selected, setSelected] = useState<string[]>([]), [question, setQuestion] = useState(""), [rounds, setRounds] = useState(2);
  const [runSources, setRunSources] = useState<Record<string, Row>>({});
  const [parentRunId, setParentRunId] = useState(""), [followupReason, setFollowupReason] = useState("");
  const [researchSteps, setResearchSteps] = useState(0);
  const [participationMode, setParticipationMode] = useState("agent_choose");
  const panel = useRef<HTMLDetailsElement>(null);
  useEffect(() => { if (requestedOpen && panel.current) panel.current.open = true; }, [requestedOpen]);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const base = ecrId ? `/api/projects/${projectId}/changes/ecrs/${ecrId}/discussion-runs` : `/api/projects/${projectId}/changes/discussion-topics`;
  const request = useCallback(async (path = "", body?: unknown): Promise<Row> => {
    const target = body === undefined && path === "" && focusedRunId ? `?run_id=${focusedRunId}` : path;
    const response = await fetch(base + target, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || "讨论操作未完成");
    return obj(value);
  }, [base, focusedRunId]);
  const read = useCallback(async () => { setData(await request()); }, [request]);
  async function act(fn: () => Promise<void>) { setBusy(true); setError(""); try { await fn(); } catch(e) { setError(e instanceof Error ? e.message : "操作未完成"); } finally { setBusy(false); } }
  async function write(path: string, body: Row, idempotent = true) { const signature = JSON.stringify([path, body]); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() }; await request(path, { ...body, ...(idempotent ? { request_id: attempt.current.id } : {}) }); attempt.current = null; await read(); }
  const active = rows(data?.items).some(r => ["queued", "running"].includes(text(r.status)) || r.recovery_requested === true && r.status === "degraded");
  useEffect(() => {
    if (!open || !active || busy) return;
    const interval = setInterval(() => { void read().catch(e => setError(e instanceof Error ? e.message : "进度读取失败")); }, 5000);
    return () => clearInterval(interval);
  }, [open, active, busy, read]);
  const includeSupplierNotices = source.context_version === "change-work-package-context-v4";
  const canDiscuss = data?.rollout === "live" && (!includeSupplierNotices || data.notice_discussion_available === true);
  const projections = rows(obj(source.model_context).professional_projections);
  return <details ref={panel} className="rounded-md border p-3" onToggle={e => { setOpen(e.currentTarget.open); if (e.currentTarget.open && !data && !busy) void act(read); }}><summary className="cursor-pointer font-medium">多专业讨论 · 发起与回放</summary>
    <div className="mt-3 space-y-3 text-xs"><p>各席位按本次固定资料发言，共用原运行预算。资料缺项、他席观点与人工补充分别保留；讨论完成后仍须按原业务流程办理批准。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(read)}>刷新讨论记录</Button>
      {!canDiscuss && <p>多专业讨论尚未开放，需阶段评测后启用；可查看已有记录。</p>}
      {!focusedRunId && data?.can_request === true && <form className="space-y-2" onSubmit={e => { e.preventDefault(); void act(() => write("", { include_supplier_notices: includeSupplierNotices, expected_digest: source.digest, depth: obj(obj(source.model_context).coverage).depth, question: question.trim(), seats: selected, rounds, research_steps: researchSteps, participation_mode: participationMode, parent_run_id: parentRunId || null, followup_reason: parentRunId ? followupReason.trim() : null, ...(!ecrId ? { selections: source.selections } : {}) })); }}><fieldset className="space-y-2" disabled={busy || !canDiscuss || !source.digest}>
        <label className="block">参与方式<select className={field} value={participationMode} onChange={e => setParticipationMode(e.target.value)}><option value="agent_choose" disabled={data.initiation_rollout !== "live"}>由 Agent 判断是否需要讨论并选择实际席位</option><option value="selected">按我选择的专业直接讨论</option></select></label>
        {participationMode === "agent_choose" && data.initiation_rollout !== "live" && <p>自主发起判断尚待独立阶段评测开放；已开放时可选择人工指定专业方式。</p>}
        {participationMode === "agent_choose" && <p>下方所选专业是本次允许的候选范围。Agent 先根据实际资料判断是否需要多专业比较；无需讨论或资料不足时保留判断依据并停止，不制造专业共识。</p>}
        <label className="block">本次讨论来源<select className={field} value={parentRunId} onChange={e => setParentRunId(e.target.value)}><option value="">独立问题 · 新建讨论</option>{rows(data.items).filter(r => r.requested_by_user_id === data.actor_id && !["queued", "running", "waiting_input"].includes(text(r.status)) && !r.recovery_requested && !r.related_request_cancelled).map(r => <option key={text(r.run_id)} value={text(r.run_id)}>关联继续：{text(obj(r.session).question)} · {date(r.created_at)}</option>)}</select></label>
        {parentRunId && <><label className="block">本次补充的资料、范围或待解决问题<textarea className={field} required maxLength={2000} value={followupReason} onChange={e => setFollowupReason(e.target.value)}/></label><p>新讨论以本次资料和问题为依据，旧发言保留供回看；共用原累计额度与截止时间。原请求已用尽、过期或整体停止时不能继续。停止这一组会阻止所有关联讨论继续调用。</p></>}
        <label className="block">需要比较的分歧、方案与取舍<textarea required maxLength={4000} className={field} value={question} onChange={e => setQuestion(e.target.value)}/></label>
        <div className="grid gap-2 sm:grid-cols-2">{projections.map(p => <label className="flex items-start gap-2" key={text(p.key)}><input type="checkbox" disabled={!strings(p.reference_ids).length && !selected.includes(text(p.key))} checked={selected.includes(text(p.key))} onChange={e => setSelected(e.target.checked ? [...selected, text(p.key)] : selected.filter(k => k !== p.key))}/><span>{text(p.label)} · {strings(p.reference_ids).length} 份专业资料{p.status === "partial" ? "，仍有缺项" : ""}</span></label>)}</div>
        <label className="block">公开研究<select className={field} value={researchSteps} onChange={e => setResearchSteps(Number(e.target.value))}><option value={0}>使用已准备资料及人工追加快照</option><option value={2} disabled={data.research_rollout !== "live"}>允许各专业自主搜索和读取（每次发言前最多2步）</option><option value={3} disabled={data.research_rollout !== "live"}>允许各专业自主研究（每次发言前最多3步）</option></select></label>
        {researchSteps > 0 && <p>各专业可按实际缺项决定是否查找公开资料，查询、读取和判断共用原累计预算。搜索摘要仅作线索，读取的原文快照才可引用；公开研究不会扩大内部对象范围。</p>}
        {data.research_rollout !== "live" && <p>专业自主研究尚待阶段评测开放。</p>}
        <label className="block">讨论轮次上限<select className={field} value={rounds} onChange={e => setRounds(Number(e.target.value))}>{[1, 2, 3].map(n => <option key={n} value={n}>{n} 轮</option>)}</select></label>
        <p>最多计划 {selected.length * rounds * (1 + researchSteps) + (participationMode === "agent_choose" ? 1 : 0)} 次模型调用（{participationMode === "agent_choose" ? "包含发起判断及所选研究上限" : "按所选席位与研究上限"}），实际执行受原预算限制；完整一轮无新增且没有新人工补充时提前停止。复述同一资料不会计作新证据，也不计为共识。</p>
        <Button type="submit" size="sm" disabled={selected.length < 2 || !question.trim() || participationMode === "agent_choose" && data.initiation_rollout !== "live"}>{participationMode === "agent_choose" ? "固定范围并交由 Agent 判断" : "固定资料并排队讨论"}</Button>
      </fieldset></form>}
      {rows(data?.items).map(run => { const actualSource = runSources[text(run.run_id)] ?? source; const session = obj(run.session), resume = obj(run.resume), budget = obj(resume.budget), config = obj(run.config), seats = rows(config.seats), labels = obj(run.reference_labels), working = ["queued", "running"].includes(text(run.status)); return <details open={focusedRunId === run.run_id || undefined} className="space-y-2 rounded-md border p-3" key={text(run.run_id)}><summary className="cursor-pointer">{text(session.question)} · {session.stop_reason === "agent_not_needed" ? "已判断无需多专业讨论" : session.stop_reason === "agent_insufficient_evidence" ? "资料不足，尚未召集" : session.stop_reason === "unchanged_full_round" ? "完整一轮无新增，已停止" : statuses[text(run.effective_status)] ?? "状态待核对"} · {date(run.created_at)}</summary>
        {run.include_supplier_notices === true && <p>本场使用已固定的厂商通告原文、具名人审及实际工程资料；日期未知和适用范围缺项仍须逐项核对。</p>}
        {run.origin_run_id != null && <p>由原分析运行中的 Agent 发起，共用原预算；原运行编号 {text(run.origin_run_id)}。这里显示实际讨论进度，发起请求本身不代表已有结论。</p>}
        {run.origin_choice != null && <DiscussionInitiation value={{ output: obj(run.origin_choice) }} labels={labels} candidates={seats}/>}
        {run.parent_run_id != null && <p>这是关联原讨论继续的新记录：{text(obj(config.request).followup_reason)}。原记录保留，累计预算与截止时间共用；原讨论编号 {text(run.parent_run_id)}。</p>}
        {run.related_request_cancelled === true && <p>这一组共享请求已停止，已保存结果可回看；不能再恢复或另开关联讨论。</p>}
        <p>原资料版本{run.source_digest === actualSource.digest ? "仍与本次预览一致" : "与本次预览不同，请核对历史依据"}；已保存 {rows(run.receipts).length} 次真实模型发言。</p>
        {config.initiation != null && !run.initiation && <p>本次允许的候选专业：{rows(config.candidate_seats).map(s => text(s.label)).join("、")}。尚无成功发起判断回执，未据此宣称已经召集。</p>}
        {run.initiation != null && <DiscussionInitiation value={obj(run.initiation)} labels={labels} candidates={rows(config.candidate_seats)}/>}
        <p>参与专业：{seats.map(s => text(s.label)).join("、") || "尚未召集"} · 原轮次上限 {String(obj(config.request).rounds)} 轮；原共享预算调用上限 {String(obj(config.budget_profile).model_call_limit ?? "未记录")} 次（包含重试）。</p>
        {resume.budget != null && <details><summary className="cursor-pointer">原运行累计预算与接续条件</summary><div className="mt-2 space-y-1"><p>累计已计费 {String(budget.charged_tokens)}，仍预留 {String(budget.held_tokens)}，剩余 {String(budget.remaining_tokens)} / 原总上限 {String(budget.token_limit)} tokens。</p><p>剩余活动时间 {budget.remaining_active_seconds == null ? "暂无可核对记录" : `${Math.floor(Number(budget.remaining_active_seconds))} 秒`}；原绝对截止 {date(budget.absolute_deadline)}。未知调用 {String(budget.unresolved_calls)} 次。</p><p>恢复沿用原发起人、资料、轮次及累计预算；已完成发言不会重新调用。租户日额度或并发条件恢复后可申请接续；单次运行上限和截止时间不会重置。</p></div></details>}
        {!working && !run.recovery_requested && resume.can_request !== true && run.error_code != null && <div className="text-muted-foreground">{strings(resume.reasons).map((reason, i) => <p key={i}>{reason}</p>)}</div>}
        {run.error_code != null && <p className="text-destructive">本次未完整完成。{(text(run.error_code).startsWith("BUDGET_") || run.error_code === "DAILY_BUDGET_EXCEEDED") ? "预算暂不可用或已达到原上限，已完成发言保留。" : run.error_code === "APPLICATION_REQUEST_CANCELLED" ? "发起人已停止后续调用。" : run.error_code === "APPLICATION_RUN_LEASE_EXPIRED" ? "执行中断，可按原回执申请恢复；预算不会重置。" : "来源、权限或模型执行需要核对，已完成记录保留。"}</p>}
        {run.effective_status === "completed" && (!run.initiation || obj(obj(run.initiation).output).action === "convene") && <p>{session.stop_reason === "unchanged_full_round" ? "完整一轮无新增，已停止后续调用。" : "所选轮次已完成。"}请核对下方真实分歧与缺项；可在下方核对决策摘要，再按原业务流程办理。</p>}
        <div className="space-y-2">{rows(run.turns).map(turn => { const receipt = rows(run.receipts).find(r => r.turn_id === turn.id), output = obj(receipt?.output); return <div id={`discussion-turn-${turn.id}`} key={text(turn.id)} className="space-y-2 rounded-md bg-muted/40 p-2"><p className="font-medium">第 {String(turn.round_number)} 轮 · {turn.speaker_kind === "human" ? `${text(turn.author_name) || "原具名人员"} · 人工补充` : text(seats.find(s => s.key === turn.seat_key)?.label)} · {date(turn.created_at)}{turn.repetition_of_turn_id ? " · 与本席原发言重复" : ""}</p>
          {turn.speaker_kind === "human" ? <p className="whitespace-pre-wrap">{text(turn.content)}（尚未据此扩展事实资料）</p> : <>{rows(output.statements).map((v, i) => <Statement key={i} value={v} labels={labels}/>)}{rows(output.responses).map((r, i) => <div key={i}><p>回应原第 {String(rows(run.turns).find(t => t.id === r.turn_id)?.sequence)} 条发言：{r.position === "agree" ? "同意" : r.position === "disagree" ? "不同意" : "需补证据"}</p><Statement value={obj(r.basis)} labels={labels}/></div>)}{strings(output.missing).map((v, i) => <p key={i}>待补：{v}</p>)}</>}
        </div>; })}</div>
        {!ecrId && !focusedRunId && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => {
          const response = await fetch(`/api/projects/${projectId}/changes/discussion-runs/${run.run_id}`, { cache: "no-store" });
          const value: unknown = await response.json(), detail = obj(value);
          if (!response.ok) throw new Error(text(obj(detail.detail).message) || "原资料暂不可读取");
          setRunSources(previous => ({ ...previous, [text(run.run_id)]: obj(detail.source) }));
          if (detail.source_error != null) throw new Error(text(detail.source_error));
        })}>按原讨论资料核对当前版本</Button>}
        <DiscussionResearch projectId={projectId} run={run} canAdd={working && data?.can_request === true} onAdded={read}/>
        <ChangeDiscussionBrief key={text(obj(run.brief).digest)} run={run} currentSource={run.research_current === false ? "" : text(actualSource.digest)} canReview={data?.can_request === true} busy={busy} submit={body => act(() => write(`/${run.run_id}/brief-reviews`, body))}/>
        {working && <form onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const content = new FormData(form).get("content"); void act(async () => { await write(`/${run.run_id}/inputs`, { content }); form.reset(); }); }}><fieldset disabled={busy} className="space-y-2"><label className="block">人工补充（后续尚未固定输入的调用可见）<textarea name="content" required maxLength={4000} className={field}/></label><Button type="submit" size="sm" variant="outline">保存具名补充</Button></fieldset></form>}
        {run.requested_by_user_id === data?.actor_id && run.related_request_cancelled !== true && <details className="rounded-md border p-2"><summary className="cursor-pointer">停止这一组后续讨论</summary><p>停止共用原预算的所有关联运行，并禁止继续关联；已保存的发言和摘要保留。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => write(`/${run.run_id}/control/cancel_related`, {}, false))}>停止这一组全部后续调用</Button></details>}
        {run.requested_by_user_id === data?.actor_id && <div className="flex gap-2">{(working || run.status === "degraded" && run.recovery_requested === true) && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => write(`/${run.run_id}/control/cancel`, {}, false))}>停止本场后续调用</Button>}{(resume.can_request === true || run.recovery_requested === true && run.status === "degraded") && <Button type="button" size="sm" variant="outline" disabled={busy || run.recovery_requested === true} onClick={() => void act(() => write(`/${run.run_id}/control/recover`, {}, false))}>{run.recovery_requested ? "恢复请求已排队" : "按原预算与进度申请接续"}</Button>}</div>}
      </details>; })}
      {data?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { const more = await request(`?before_id=${data.next_before_id}`); setData({ ...more, items: [...rows(data.items), ...rows(more.items)] }); })}>更早讨论</Button>}
    </div>
  </details>;
}
