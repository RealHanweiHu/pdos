"use client";

import { useId, useState } from "react";
import { Flask, Play, Plus, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { coverageGaps, eventTimeProblems, fixedContextKey, handoffProblems, incompleteResultItems, measurementProblems, missingFieldNames, pairKey, resultStatusNames, runStatusNames, sourceText, startProblems, type CoveragePair, type MeasurementInput, type MissingMeasurementField, type ResultsIntent, type RunStartIntent, type SampleRef, type TestRun, type VerificationCallbacks, type VerificationContext, type VerificationRequest } from "./contracts";
import { blankEventTime, eventTimeFromDraft, EventTimeFields } from "./event-time";
import { useVerificationAction, VerificationActionReview } from "./preview";
import { VerificationTimes } from "./request-reading";

const inputClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
type Props = { request: VerificationRequest; samples: SampleRef[]; runs: TestRun[]; context: VerificationContext; callbacks: VerificationCallbacks; nextOwners: { id: string; label: string }[] };
type RowDraft = { key: number; testItemId: string; sampleId: string; rawValue: string; unit: string; conditions: string; equipment: string; environment: string; observedAt: string; originalTimezone: string; methodKnown: boolean; originalId: string; sourceRevision: string; locator: string; missing: MissingMeasurementField[]; note: string };
const blankRow = (key: number): RowDraft => ({ key, testItemId: "", sampleId: "", rawValue: "", unit: "", conditions: "", equipment: "", environment: "", observedAt: "", originalTimezone: "", methodKnown: false, originalId: "", sourceRevision: "", locator: "", missing: [], note: "" });

export function VerificationTestRuns(props: Props) {
  return <RunPanel key={props.request.id} {...props}/>;
}

function RunPanel(props: Props) {
  const { request, samples, runs, context, callbacks } = props;
  const prefix = useId();
  const [pairs, setPairs] = useState<CoveragePair[]>([]);
  const sampleIds = Array.from(new Set(pairs.map(pair => pair.sampleId)));
  const testItemIds = Array.from(new Set(pairs.map(pair => pair.testItemId)));
  const action = useVerificationAction(fixedContextKey(context, request, samples, runs), context.portReady && context.capabilities.planRun, callbacks);
  const accepted = request.acceptedCoverage;
  const planAllowed = context.portReady && context.capabilities.planRun && !!accepted && ["accepted", "scheduled", "executing"].includes(request.status);
  function toggle(pair: CoveragePair) { setPairs(previous => previous.some(value => pairKey(value) === pairKey(pair)) ? previous.filter(value => pairKey(value) !== pairKey(pair)) : [...previous, pair]); }
  function plan() {
    if (!planAllowed || !accepted) { action.setError("只能为已正式接收的实际范围准备 Run。"); return; }
    if (pairs.some(pair => !accepted.pairs.some(value => pairKey(value) === pairKey(pair)))) { action.setError("所选样件与测试项对应范围超出正式接收范围。"); return; }
    const coverage = { sampleIds, testItemIds, pairs };
    const problems = handoffProblems(request, samples, coverage, [], "handoff.offer");
    if (problems.length) { action.setError(problems.join(" ")); return; }
    void action.prepare({ action: "run.plan", request: { id: request.id, revision: request.revision }, build: request.build, samples: samples.filter(sample => sampleIds.includes(sample.id)), coverage });
  }
  return <section className="min-w-0 space-y-5" aria-label="测试执行与结果返回">
    <header><h2 className="flex items-center gap-2 text-lg font-semibold"><Flask aria-hidden/>TestRun 与结果返回</h2><p className="mt-1 text-sm opacity-70">执行状态与判定结果各自保存。配置变化须按允许的分段规程记录，或由主线建立新 Run。</p></header>
    {!context.portReady && <p role="status" className="rounded-lg bg-muted p-3 text-sm">待主线接入：{context.unavailableReason || "真实样件可用性、实际配置与具名动作复查接口尚未就绪。"}</p>}
    <details className="rounded-lg border border-border p-4"><summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-ring">为正式接收范围准备新的 Run</summary><form className="mt-4 space-y-4" aria-busy={action.busy} onSubmit={event => { event.preventDefault(); plan(); }}><fieldset disabled={action.locked || !planAllowed} className="space-y-3"><legend className="mb-2 text-sm font-medium">正式接收的逐件对应范围</legend>{accepted?.pairs.map((pair, index) => {
      const sample = samples.find(value => value.id === pair.sampleId);
      const item = request.testItems.find(value => value.id === pair.testItemId);
      return <label key={pairKey(pair)} htmlFor={`${prefix}-pair-${index}`} className="flex items-start gap-2 text-sm"><input id={`${prefix}-pair-${index}`} className="mt-1 accent-primary" type="checkbox" checked={pairs.some(value => pairKey(value) === pairKey(pair))} disabled={!sample || sample.availability !== "available"} onChange={() => toggle(pair)}/><span className="min-w-0 break-words">{sample?.label ?? pair.sampleId} / {item?.title ?? pair.testItemId}<span className="block text-xs opacity-70">实际配置 {sample?.actualConfiguration.id ?? "未接入"} · v{sample?.actualConfiguration.revision ?? "未知"}</span></span></label>;
    })}</fieldset>{!planAllowed && <p className="text-sm opacity-70">尚无可办理的正式接收范围或当前权限。</p>}<Button type="submit" disabled={action.locked || !planAllowed}>核对新 Run 固定范围</Button></form><div className="mt-4"><VerificationActionReview action={action} ready={planAllowed}/></div></details>
    {runs.length === 0 && <p className="rounded-lg border border-border p-4 text-sm opacity-70">尚无真实 TestRun。计划 Build 不会自动产生 Run 或测量。</p>}
    {runs.map(run => <RunEntry key={run.id} {...props} run={run}/>)}
  </section>;
}

function RunEntry({ request, samples, runs, context, callbacks, nextOwners, run }: Props & { run: TestRun }) {
  const prefix = useId();
  const [rows, setRows] = useState<RowDraft[]>([]);
  const [kind, setKind] = useState<ResultsIntent["kind"]>("preliminary");
  const [incompleteReason, setIncompleteReason] = useState("");
  const [nextOwnerId, setNextOwnerId] = useState("");
  const [returnedTime, setReturnedTime] = useState(blankEventTime);
  const [endTime, setEndTime] = useState(blankEventTime);
  const action = useVerificationAction(fixedContextKey(context, request, samples, runs), context.portReady, callbacks);
  const startAllowed = context.portReady && context.capabilities.startRun && !!context.executor && run.status === "planned" && run.requestId === request.id && !!request.acceptedCoverage && run.coverage.pairs.every(pair => request.acceptedCoverage?.pairs.some(value => pairKey(value) === pairKey(pair)));
  const resultsAllowed = context.portReady && context.capabilities.recordResults && ["running", "results_pending"].includes(run.status) && run.requestId === request.id;
  const editable = !action.locked && resultsAllowed;

  function updateRow(key: number, patch: Partial<RowDraft>) { setRows(previous => previous.map(row => row.key === key ? { ...row, ...patch } : row)); }
  function addRow() { setRows(previous => [...previous, blankRow(Math.max(0, ...previous.map(row => row.key)) + 1)]); }
  function start(data: Pick<RunStartIntent, "time" | "execution">) {
    if (!startAllowed || !run.samples.length || !run.coverage.testItemIds.length) { action.setError("当前权限、接收范围或 Run 状态不允许开测。"); return; }
    const drift = run.samples.some(sample => {
      const current = samples.find(value => value.id === sample.id);
      return !current || current.availability !== "available" || !current.source || current.actualConfiguration.id !== sample.actualConfiguration.id || current.actualConfiguration.revision !== sample.actualConfiguration.revision;
    });
    if (drift) { action.setError("实际样件可用性或配置已变化，禁止开测，请由主线重新核对。"); return; }
    void action.prepare({ action: "run.start", request: { id: request.id, revision: request.revision }, run: { id: run.id, revision: run.revision }, samples: run.samples, coverage: run.coverage, ...data });
  }
  function prepareResults() {
    if (!resultsAllowed || (rows.length === 0 && (kind !== "final" || incompleteResultItems(run, run.measurements).length > 0))) { action.setError("请选择执行中的 Run，并添加实际测量或明确缺项记录；全部对应覆盖已有测量时可只确认最终结束。"); return; }
    const measurements: MeasurementInput[] = [];
    const problems: string[] = [];
    rows.forEach((row, index) => {
      const sample = run.samples.find(sample => sample.id === row.sampleId);
      const item = request.testItems.find(item => item.id === row.testItemId);
      if (!sample || !item) { problems.push(`第 ${index + 1} 行须明确固定样件与测试项。`); return; }
      const sourcePosition = row.originalId || row.sourceRevision || row.locator ? { originalId: row.originalId, revision: Number(row.sourceRevision), kind: "original", locator: row.locator } : null;
      const measurement: MeasurementInput = { testItemId: row.testItemId, sample, rawValue: row.rawValue, unit: row.unit, conditions: row.conditions, equipment: row.equipment, environment: row.environment, observedAt: row.observedAt || null, originalTimezone: row.originalTimezone || null, method: row.methodKnown ? { id: item.method.id, revision: item.method.revision } : null, sourcePosition, missing: row.missing, note: row.note };
      problems.push(...measurementProblems(measurement, run, request).map(value => `第 ${index + 1} 行：${value}`));
      measurements.push(measurement);
    });
    const pairs = measurements.map(value => `${value.sample.id}:${value.testItemId}`);
    if (new Set(pairs).size !== pairs.length) problems.push("本次提交内样件与测试项重复；多次读数请分开附来源，不能覆盖已有读数。");
    if (measurements.some(value => run.measurements.some(existing => existing.sample.id === value.sample.id && existing.testItemId === value.testItemId))) problems.push("已有测量的对应范围不可再次提交；全部部分结果已返回时只确认最终结束。");
    const incomplete = incompleteResultItems(run, [...run.measurements, ...measurements]);
    if (incomplete.length && (!incompleteReason.trim() || !nextOwnerId.trim())) problems.push("未完成覆盖须说明原因与下一责任人。");
    const returnedAt = eventTimeFromDraft(returnedTime);
    const actualEnd = kind === "final" ? eventTimeFromDraft(endTime) : null;
    problems.push(...eventTimeProblems(returnedAt, kind === "final" ? "最终结果返回" : "部分结果返回"));
    if (actualEnd) {
      problems.push(...eventTimeProblems(actualEnd, "实际结束"));
      if (Date.parse(actualEnd.occurredAt) > Date.parse(returnedAt.occurredAt)) problems.push("最终返回不得早于实际结束。");
    }
    if (problems.length) { action.setError(problems.join(" ")); return; }
    void action.prepare({ action: "run.results", request: { id: request.id, revision: request.revision }, run: { id: run.id, revision: run.revision }, kind, returnedAt, actualEnd, samples: run.samples, coverage: run.coverage, measurements, incompleteTestItemIds: incomplete, incompleteReason, nextOwnerId });
  }

  return <article className="min-w-0 space-y-4 rounded-lg border border-border p-4" aria-label={`测试记录 ${run.title}`} aria-busy={action.busy}>
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="break-words font-semibold">{run.title}</h3><p className="mt-1 text-xs opacity-70">{run.id} · v{run.revision}</p></div><div className="grid gap-1 text-sm"><p>执行：{runStatusNames[run.status]}</p><p>本 Run 范围判定：{resultStatusNames[run.result]}</p></div></header>
    <div className="space-y-2 text-sm"><p className="font-medium">Run 固定实际测试对象</p>{run.samples.map(sample => <p key={sample.id} className="break-words">{sample.label} · 模穴 {sample.cavity ?? "未记录"} · 实际配置 {sample.actualConfiguration.id} v{sample.actualConfiguration.revision}</p>)}<p className="break-words opacity-70">精确对应范围：{run.coverage.pairs.map(pair => `${run.samples.find(sample => sample.id === pair.sampleId)?.label ?? pair.sampleId} / ${request.testItems.find(item => item.id === pair.testItemId)?.title ?? pair.testItemId}`).join("；") || "未记录"}</p></div>
    {coverageGaps(request, run.samples, run.coverage).length > 0 && <p className="rounded-lg bg-muted p-3 text-sm">本 Run 判定只适用于上述范围。原请求覆盖差距：{coverageGaps(request, run.samples, run.coverage).join(" ")}</p>}
    <RunStartForm context={context} enabled={startAllowed && !action.locked} onSubmit={start} onError={action.setError}/>
    {run.measurements.length > 0 && <section className="space-y-3 border-t border-border pt-4" aria-label="已记录测量"><h4 className="text-sm font-medium">实际测量与独立结论</h4>{run.measurements.map(measurement => <div key={measurement.id} className="min-w-0 border-b border-border pb-3 text-sm"><p className="break-words font-medium">{request.testItems.find(item => item.id === measurement.testItemId)?.title ?? measurement.testItemId} · {measurement.sample.label}</p><p className="mt-1 whitespace-pre-wrap break-words font-mono">原值：{measurement.rawValue || "缺项"} {measurement.unit}</p><p className="mt-1 break-words text-xs opacity-70">工况 {measurement.conditions || "缺项"}；设备 {measurement.equipment || "缺项"}；环境 {measurement.environment || "缺项"}；方法 {measurement.method ? `${measurement.method.id} v${measurement.method.revision}` : "缺项"}</p><p className="mt-1 break-words text-xs opacity-70">{sourceText(measurement.sourcePosition)}</p><p className="mt-1 break-words text-xs opacity-70">真实观测 {measurement.observedAt ?? "缺项"} · {measurement.originalTimezone ?? "原时区缺项"}</p><p className="mt-2">确定性判定：{resultStatusNames[measurement.computedResult]}；专业结论：{measurement.professionalConclusion ?? "尚未记录"}</p>{measurement.missing.length > 0 && <p className="mt-1 text-xs">明确缺项：{measurement.missing.map(field => missingFieldNames[field]).join("、")}</p>}</div>)}</section>}
    <details className="border-t border-border pt-4"><summary className="cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">录入部分或最终结果</summary><form className="mt-4 space-y-4" onSubmit={event => { event.preventDefault(); prepareResults(); }}><fieldset disabled={!editable} className="space-y-4"><legend className="sr-only">测量原值与缺项</legend>
      <label className="block space-y-1 text-sm" htmlFor={`${prefix}-kind`}><span>本次返回形式</span><select id={`${prefix}-kind`} className={inputClass} value={kind} onChange={event => setKind(event.target.value as ResultsIntent["kind"])}><option value="preliminary">部分结果</option><option value="final">最终结果（仍可为不确定或无效）</option></select></label>
      {rows.map((row, index) => <MeasurementRow key={row.key} row={row} index={index} prefix={`${prefix}-${row.key}`} request={request} run={run} update={patch => updateRow(row.key, patch)} remove={() => setRows(previous => previous.filter(value => value.key !== row.key))}/>)}
      <Button type="button" variant="outline" onClick={addRow}><Plus aria-hidden/>添加测量或缺项记录</Button>
      <EventTimeFields title={kind === "final" ? "最终结果真实返回" : "部分结果真实返回"} value={returnedTime} onChange={setReturnedTime}/>
      {kind === "final" && <EventTimeFields title="实际测试结束（单独保留时间与来源）" value={endTime} onChange={setEndTime}/>}
      <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm" htmlFor={`${prefix}-incomplete`}><span>未完成覆盖的原因</span><textarea id={`${prefix}-incomplete`} className={inputClass} maxLength={2000} value={incompleteReason} onChange={event => setIncompleteReason(event.target.value)}/></label><label className="space-y-1 text-sm" htmlFor={`${prefix}-next-owner`}><span>未完成项的下一责任人</span><select id={`${prefix}-next-owner`} className={inputClass} value={nextOwnerId} onChange={event => setNextOwnerId(event.target.value)}><option value="">请选择当前可分派人员</option>{nextOwners.map(owner => <option key={owner.id} value={owner.id}>{owner.label}</option>)}</select></label></div>
      <p className="text-xs opacity-70">空字段须明确勾选缺项；系统据真实读数和有效条件独立判定。部分结果不会将执行状态自动改为已审阅或已处置。</p>
    </fieldset>{!resultsAllowed && <p className="text-sm opacity-70">当前 Run 状态、身份或接口不允许录入结果。</p>}<Button type="submit" disabled={!editable}>核对本次结果与覆盖</Button></form></details>
    <VerificationActionReview action={action} ready={context.portReady && (action.preview?.intent.action === "run.start" ? startAllowed : resultsAllowed)}/>
    <details className="border-t border-border pt-4"><summary className="cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">Run 时间与来源</summary><div className="mt-3"><VerificationTimes times={run.times}/></div></details>
    {run.incompleteTestItemIds.length > 0 && <p className="break-words text-sm opacity-70">未完成测试项：{run.incompleteTestItemIds.map(id => request.testItems.find(item => item.id === id)?.title ?? id).join("、")}</p>}
  </article>;
}

function MeasurementRow({ row, index, prefix, request, run, update, remove }: { row: RowDraft; index: number; prefix: string; request: VerificationRequest; run: TestRun; update: (patch: Partial<RowDraft>) => void; remove: () => void }) {
  const item = request.testItems.find(item => item.id === row.testItemId);
  const fields = ["rawValue", "unit", "conditions", "equipment", "environment", "observedAt", "originalTimezone"] as const;
  return <fieldset className="min-w-0 space-y-3 rounded-lg border border-border p-3"><legend className="px-1 text-sm font-medium">记录 {index + 1}</legend><div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm" htmlFor={`${prefix}-sample`}><span>Run 固定样件</span><select id={`${prefix}-sample`} className={inputClass} required value={row.sampleId} onChange={event => update({ sampleId: event.target.value })}><option value="">请选择实际样件</option>{run.samples.map(sample => <option key={sample.id} value={sample.id}>{sample.label} · 实际配置 v{sample.actualConfiguration.revision}</option>)}</select></label><label className="space-y-1 text-sm" htmlFor={`${prefix}-item`}><span>固定测试项</span><select id={`${prefix}-item`} className={inputClass} required value={row.testItemId} onChange={event => update({ testItemId: event.target.value, methodKnown: false })}><option value="">请选择测试项</option>{request.testItems.filter(item => run.coverage.pairs.some(pair => pair.testItemId === item.id && pair.sampleId === row.sampleId)).map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>{fields.map(field => <label key={field} className="space-y-1 text-sm" htmlFor={`${prefix}-${field}`}><span>{missingFieldNames[field]}</span><input id={`${prefix}-${field}`} className={inputClass} maxLength={2000} value={row[field]} placeholder={field === "unit" ? `要求单位：${item?.method.unit || "待明确"}` : undefined} onChange={event => update({ [field]: event.target.value })}/></label>)}</div>
    <label className="flex items-start gap-2 text-sm"><input className="mt-1 accent-primary" type="checkbox" checked={row.methodKnown} disabled={!item} onChange={event => update({ methodKnown: event.target.checked })}/><span className="break-words">实际采用上述固定方法：{item ? `${item.method.title} · v${item.method.revision}` : "先选测试项"}</span></label>
    <fieldset className="grid gap-3 sm:grid-cols-3"><legend className="mb-2 text-sm font-medium">测量来源位置</legend><label className="space-y-1 text-sm" htmlFor={`${prefix}-original`}><span>原件 ID</span><input id={`${prefix}-original`} className={inputClass} value={row.originalId} maxLength={160} onChange={event => update({ originalId: event.target.value })}/></label><label className="space-y-1 text-sm" htmlFor={`${prefix}-revision`}><span>原件版本</span><input id={`${prefix}-revision`} className={inputClass} inputMode="numeric" value={row.sourceRevision} onChange={event => update({ sourceRevision: event.target.value })}/></label><label className="space-y-1 text-sm" htmlFor={`${prefix}-locator`}><span>页 / 行 / 单元格等位置</span><input id={`${prefix}-locator`} className={inputClass} value={row.locator} maxLength={2000} onChange={event => update({ locator: event.target.value })}/></label></fieldset>
    <fieldset className="flex flex-wrap gap-x-4 gap-y-2"><legend className="mb-2 text-sm font-medium">明确缺项</legend>{Object.entries(missingFieldNames).map(([field, label]) => <label key={field} className="flex items-center gap-2 text-xs"><input className="accent-primary" type="checkbox" checked={row.missing.includes(field as MissingMeasurementField)} onChange={() => update({ missing: row.missing.includes(field as MissingMeasurementField) ? row.missing.filter(value => value !== field) : [...row.missing, field as MissingMeasurementField] })}/>{label}</label>)}</fieldset>
    <label className="block space-y-1 text-sm" htmlFor={`${prefix}-note`}><span>异常与缺项说明</span><textarea id={`${prefix}-note`} className={inputClass} value={row.note} maxLength={2000} onChange={event => update({ note: event.target.value })}/></label><Button type="button" variant="ghost" onClick={remove} aria-label={`移除记录 ${index + 1}`}><Trash aria-hidden/>移除本行</Button>
  </fieldset>;
}

function RunStartForm({ context, enabled, onSubmit, onError }: { context: VerificationContext; enabled: boolean; onSubmit: (value: Pick<RunStartIntent, "time" | "execution">) => void; onError: (value: string) => void }) {
  const prefix = useId();
  const [draft, setDraft] = useState({ occurredAt: "", timezone: "", originalId: "", sourceRevision: "", locator: "", equipment: "", calibration: "", environment: "", conditions: "" });
  const fields = { occurredAt: "真实开始时间（含 UTC 或偏移）", timezone: "原始 IANA 时区", originalId: "开始记录原件 ID", sourceRevision: "开始记录原件版本", locator: "开始记录精确位置", environment: "实际环境", conditions: "实际工况" };
  function submit() {
    const equipment = context.startResources.equipment.find(value => sourceText(value) === draft.equipment);
    const calibration = context.startResources.calibration.find(value => sourceText(value) === draft.calibration);
    if (!enabled || !context.executor || !equipment || !calibration) { onError("具名身份、当前设备或校准来源尚未满足，请由主线复查。"); return; }
    const value: Pick<RunStartIntent, "time" | "execution"> = { time: { occurredAt: draft.occurredAt, originalTimezone: draft.timezone, source: { originalId: draft.originalId, revision: Number(draft.sourceRevision), kind: "original", locator: draft.locator } }, execution: { equipment, calibration, environment: draft.environment, conditions: draft.conditions, executorId: context.executor.id } };
    const problems = startProblems(value, context);
    if (problems.length) { onError(problems.join(" ")); return; }
    onSubmit(value);
  }
  return <details className="border-t border-border pt-4"><summary className="cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">具名开测与真实发生条件</summary><form className="mt-3 space-y-3" onSubmit={event => { event.preventDefault(); submit(); }}><fieldset disabled={!enabled} className="grid min-w-0 gap-3 sm:grid-cols-2"><legend className="sr-only">真实开测时间、设备、条件与来源</legend><p className="text-sm sm:col-span-2">服务器当前执行人：{context.executor?.label ?? "尚未接入具名身份"}</p>{Object.entries(fields).map(([field, label]) => <label key={field} className="space-y-1 text-sm" htmlFor={`${prefix}-${field}`}><span>{label}</span><input id={`${prefix}-${field}`} className={inputClass} required maxLength={2000} value={draft[field as keyof typeof draft]} placeholder={field === "occurredAt" ? "2026-10-02T09:00:00+08:00" : field === "timezone" ? "Asia/Shanghai" : undefined} onChange={event => setDraft(previous => ({ ...previous, [field]: event.target.value }))}/></label>)}{(["equipment", "calibration"] as const).map(field => <label key={field} className="space-y-1 text-sm" htmlFor={`${prefix}-${field}`}><span>{field === "equipment" ? "实际设备固定来源" : "当前校准固定来源"}</span><select id={`${prefix}-${field}`} className={inputClass} required value={draft[field]} onChange={event => setDraft(previous => ({ ...previous, [field]: event.target.value }))}><option value="">请选择服务器提供的当前版本</option>{context.startResources[field].map(value => <option key={sourceText(value)} value={sourceText(value)}>{sourceText(value)}</option>)}</select></label>)}</fieldset><p className="text-xs opacity-70">此处录入真实事件，服务器在命令事务内复查来源、设备、校准、人员资格、样件预约及破坏性消耗。</p><Button type="submit" variant="outline" disabled={!enabled}><Play aria-hidden/>核对具名开测</Button></form></details>;
}
