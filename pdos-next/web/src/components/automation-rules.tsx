"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowClockwise, ArrowRight, Pause, Play, Plus } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { automationDollars, automationForm, automationFormSpec, automationPreviewCurrent, automationRecord, automationRoot, automationStorageKey, automationTaskStates, blankAutomationForm, blankAutomationLocal, newAutomationCommand, parseAutomationDetail, parseAutomationList, restoreAutomationLocal, runAutomationRequest, type AutomationDetail, type AutomationForm, type AutomationList, type AutomationLocal, type AutomationPending, type AutomationRule, type AutomationServiceGrant, type AutomationTriggerKind, type WorkspaceApi } from "@/lib/automation-rules";

type Props = { api: WorkspaceApi; principalId: string; categoryId: string; onOpenRun?: (runId: string, categoryId: string) => void };
const stateNames: Record<AutomationRule["state"], string> = { draft: "草稿", active: "已启用", paused: "已暂停", retired: "已退役" };
const inputClass = "mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm";
const message = (failure: unknown) => failure instanceof Error ? failure.message : "规则办理暂不可用。";
const triggerNames: Record<AutomationTriggerKind, string> = { manual: "本人手动", schedule: "定时", domain_event: "领域事件", relative_milestone: "相对里程碑" };
const taskStateNames: Record<string, string> = { proposed: "待分派", assigned: "待本人承接", accepted: "已承接", in_progress: "实际进行中", submitted: "待成果验收", completed: "成果已验收" };
function TriggerFields({ form, eventTypes, change }: { form: AutomationForm; eventTypes: string[]; change: (patch: Partial<AutomationForm>) => void }) {
  const textField = (key: keyof AutomationForm, label: string, required = false) => <label className="block text-sm">{label}<input required={required} className={inputClass} value={String(form[key])} onChange={event => change({ [key]: event.target.value })}/></label>;
  return <div className="space-y-3 rounded-lg border border-border p-3"><label className="block text-sm">触发方式<select className={inputClass} value={form.triggerKind} onChange={event => change({ triggerKind: event.target.value as AutomationTriggerKind })}>{Object.entries(triggerNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
    {form.triggerKind === "manual" && <p className="text-sm text-muted-foreground">仅由本人明确点击触发。启用本身不代表已发起手动运行。</p>}
    {form.triggerKind === "schedule" && <div className="space-y-3">{textField("firstAt", "首次计划时点（含时区 ISO）", true)}{textField("timezone", "原始 IANA 时区", true)}{textField("interval", "重复间隔秒数（留空仅一次）")}<p className="text-xs text-muted-foreground">例如 2030-10-18T09:00:00+08:00 与 Asia/Shanghai。按原声明时点办理，不替未知日期补值。</p></div>}
    {form.triggerKind === "domain_event" && <div className="space-y-3"><fieldset className="space-y-2"><legend className="text-sm font-medium">实际领域事件目录</legend>{!eventTypes.length && <p className="text-sm text-muted-foreground">未取得事件目录，不能保存新的事件选择。</p>}{eventTypes.map(type => <label key={type} className="flex items-start gap-2 break-all text-sm"><input type="checkbox" className="mt-1" checked={form.eventTypes.includes(type)} onChange={event => change({ eventTypes: event.target.checked ? [...form.eventTypes, type] : form.eventTypes.filter(value => value !== type) })}/>{type}</label>)}{form.eventTypes.filter(type => !eventTypes.includes(type)).map(type => <p key={type} className="break-all text-sm text-destructive">原固定事件当前不在目录中：{type}</p>)}</fieldset>{textField("eventSubject", "限定事件对象 UUID（可选）")}{textField("mergeWindow", "来源变化合并窗口秒数", true)}</div>}
    {form.triggerKind === "relative_milestone" && <div className="space-y-3"><p className="text-sm text-muted-foreground">须填写实际型号、项目及任务。日期由实际 owner 读取；未知时钟保留缺项，不由前端生成预计日期。</p><label className="block text-sm">里程碑来源<select className={inputClass} value={form.relativeSource} onChange={event => change(event.target.value === "commitment" ? { relativeSource: "commitment", relativeClock: "promised_at" } : { relativeSource: "plan_task", relativeClock: "earliest_start", promisor: "", recipient: "" })}><option value="plan_task">实际计划任务时钟</option><option value="commitment">本人对指定接收者的承诺时钟</option></select></label>{textField("relativeProject", "实际项目 UUID", true)}{textField("relativeTask", "实际任务 UUID", true)}<label className="block text-sm">相对时钟<select className={inputClass} value={form.relativeClock} onChange={event => change({ relativeClock: event.target.value as AutomationForm["relativeClock"] })}>{(form.relativeSource === "commitment" ? [["promised_at", "实际承诺时点"]] : [["earliest_start", "最早开始"], ["earliest_finish", "最早完成"], ["latest_start", "最晚开始"], ["latest_finish", "最晚完成"]]).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>{form.relativeSource === "commitment" && <>{textField("promisor", "实际承诺人 UUID", true)}{textField("recipient", "该承诺接收者 UUID", true)}</>}{textField("offset", "相对偏移秒数（负数之前，正数之后）", true)}</div>}
    {form.triggerKind !== "manual" && textField("expiry", "触发失效时点（含时区 ISO，可留空）")}
    <details className="space-y-3"><summary className="cursor-pointer text-sm">任务状态条件与级联上限</summary><div className="mt-3 space-y-3">{textField("conditionTask", "条件绑定的实际任务 UUID（可选）")}{(["onlyStates", "stopStates"] as const).map(key => <fieldset key={key} className="space-y-2"><legend className="text-sm font-medium">{key === "onlyStates" ? "只在这些状态受理（未选不增加状态筛选）" : "到达这些状态停止"}</legend><div className="flex flex-wrap gap-3">{automationTaskStates.map(state => <label key={state} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form[key].includes(state)} onChange={event => change({ [key]: event.target.checked ? [...form[key], state] : form[key].filter(value => value !== state) })}/>{taskStateNames[state]}</label>)}</div></fieldset>)}{textField("cascade", "最大因果级联深度", true)}</div></details>
  </div>;
}
function serviceGrant(value: AutomationServiceGrant | null) {
  if (!value) return <p className="text-sm text-muted-foreground">未读取到实际服务授权记录，不按已授予自动服务权限显示。</p>;
  const labels = { active: "活动", paused: "已暂停", superseded: "已被续版替代", expired: "已到期", stopped: "已停止" };
  return <section aria-label="实际服务授权" className="space-y-2 rounded-lg border border-border p-3 text-sm"><h4 className="font-medium">实际服务授权 · {labels[value.state]}</h4><p className="break-all">服务执行身份 {value.service_principal_id}<br/>委托人 {value.delegator_id}<br/>固定版本 {value.version_id}<br/>授权记录 {value.id} · 回执 {value.receipt_id}<br/>到期 {value.expires_at ?? "原授权未另设截止"}</p><p className="text-muted-foreground">委托人不是后台执行身份；范围、用途和预算受绑定的固定规则版本及当前服务授权约束。</p></section>;
}

export function ConnectedAutomationRules(props: Props) {
  const [binding, setBinding] = useState({ api: props.api, revision: 0 });
  if (binding.api !== props.api) { setBinding({ api: props.api, revision: binding.revision + 1 }); return null; }
  if (!props.categoryId) return <section aria-label="自动化规则" className="space-y-2 rounded-lg border border-border p-4"><h2 className="font-semibold">自动化规则</h2><p className="text-sm text-muted-foreground">请先选择一个可读品类，再读取或办理本人规则。</p></section>;
  return <ScopedAutomationRules key={`${binding.revision}:${props.principalId}:${props.categoryId}`} {...props}/>;
}

function ScopedAutomationRules({ api, principalId, categoryId, onOpenRun }: Props) {
  const scope = { principalId, categoryId }, key = automationStorageKey(scope);
  const [local, setLocal] = useState<AutomationLocal>(() => blankAutomationLocal(scope));
  const currentLocal = useRef(local), epoch = useRef(0), locked = useRef(false);
  const [reading, setReading] = useState<AutomationList | null>(null), [detail, setDetail] = useState<AutomationDetail | null>(null);
  const [busy, setBusy] = useState(true), [broken, setBroken] = useState(false), [denied, setDenied] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [rejected, setRejected] = useState(false);
  function remember(value: AutomationLocal) { localStorage.setItem(key, JSON.stringify(value)); currentLocal.current = value; setLocal(value); }
  function rememberEvent(value: AutomationLocal) { try { remember(value); return true; } catch { setError("本机恢复记录保存失败；尚未发送新请求，请恢复本机存储后重试。"); return false; } }
  async function read(stamp: number, selected = currentLocal.current.selectedRuleId) {
    const value = parseAutomationList(await api<unknown>(automationRoot(scope)));
    if (epoch.current !== stamp) return;
    setReading(value); setDenied(false);
    if (selected) { const next = parseAutomationDetail(await api<unknown>(`${automationRoot(scope)}/${selected}`), selected); if (epoch.current === stamp) setDetail(next); }
  }
  function failure(value: unknown, stamp: number) {
    if (epoch.current !== stamp) return;
    const status = (value as { status?: number })?.status;
    if (status === 401 || status === 403) {
      let removed = true; try { localStorage.removeItem(key); } catch { removed = false; }
      const empty = blankAutomationLocal(scope); currentLocal.current = empty; setLocal(empty); setReading(null); setDetail(null); setNotice(""); setDenied(true); setBroken(!removed);
      setError(`${message(value)}。已清除页面私有规则材料${removed ? "及本机恢复记录" : "；本机恢复记录无法移除，请先恢复存储"}。`);
    } else { setError(message(value)); setRejected(status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429); }
  }
  useEffect(() => {
    const stamp = ++epoch.current; locked.current = true;
    void Promise.resolve().then(async () => {
      if (epoch.current !== stamp) return;
      try { const raw = localStorage.getItem(key); if (raw) { const restored = restoreAutomationLocal(JSON.parse(raw), { principalId, categoryId }); if (!restored) throw new Error("本机原规则请求无法核对；暂不办理新请求，请保留记录并核对。"); if (epoch.current !== stamp) return; currentLocal.current = restored; setLocal(restored); } }
      catch (value) { if (epoch.current === stamp) { setBroken(true); setError(message(value)); } }
      try { await read(stamp); } catch (value) { failure(value, stamp); }
      finally { if (epoch.current === stamp) { locked.current = false; setBusy(false); } }
    });
    return () => { epoch.current = stamp + 1; locked.current = false; };
    // The wrapper owns a fresh component for every API/person/category binding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key, principalId, categoryId]);
  async function perform(action: (stamp: number) => Promise<void>) {
    if (locked.current) return;
    const stamp = epoch.current; locked.current = true; setBusy(true); setError(""); setRejected(false);
    try { await action(stamp); } catch (value) { failure(value, stamp); }
    finally { if (epoch.current === stamp) { locked.current = false; setBusy(false); } }
  }
  async function send(pending: AutomationPending, stamp: number) {
    const result = await runAutomationRequest(api, pending, scope, () => stamp === epoch.current);
    if (!result || stamp !== epoch.current) return;
    if (result.kind === "preview") { remember({ ...currentLocal.current, pending: { kind: "command", stage: "confirm", command: result.preview.command, preview: result.preview } }); return; }
    const next = { ...currentLocal.current, selectedRuleId: result.ruleId, editRuleId: pending.kind === "command" && pending.command.operation === "ai.automation.draft.save" ? result.ruleId : currentLocal.current.editRuleId, pending: null };
    try { remember(next); } catch { currentLocal.current = next; setLocal(next); setError("已取得匹配回执；本机原恢复记录尚未清除，重新打开只读，不会自动重发。"); }
    setNotice(result.kind === "saved" ? `规则已保存 · 回执 ${result.receiptId}` : `手动运行已受理 · ${result.runId}。受理不表示模型已经执行或工作已经完成。`);
    setReading(null); setDetail(null);
    try { await read(stamp, result.ruleId); } catch (value) { if ([401, 403].includes(Number((value as { status?: number })?.status))) failure(value, stamp); else if (stamp === epoch.current) setError(`已取得办理结果；当前列表读取失败：${message(value)}`); }
  }
  function start(pending: AutomationPending) { if (broken || denied || currentLocal.current.pending || locked.current) return; if (!rememberEvent({ ...currentLocal.current, pending })) return; setNotice(""); void perform(stamp => send(pending, stamp)); }
  function formChange(patch: Partial<AutomationForm>) { rememberEvent({ ...currentLocal.current, form: { ...currentLocal.current.form, ...patch } }); }
  function choose(ruleId: string) {
    if (!rememberEvent({ ...currentLocal.current, selectedRuleId: ruleId })) return;
    setDetail(null); void perform(async stamp => { const value = parseAutomationDetail(await api<unknown>(`${automationRoot(scope)}/${ruleId}`), ruleId); if (stamp === epoch.current) setDetail(value); });
  }
  function edit(rule?: AutomationRule) {
    const spec = rule?.draft?.spec ?? rule?.published?.spec;
    rememberEvent({ ...currentLocal.current, editRuleId: rule?.id ?? null, form: spec ? automationForm(spec) : blankAutomationForm() });
  }
  function saveDraft(event: FormEvent) {
    event.preventDefault(); if (!reading) return;
    try { const target = local.editRuleId ? reading.rules.find(row => row.id === local.editRuleId) : null; if (local.editRuleId && !target) throw new Error("原规则当前不可见，请重新读取。"); const command = newAutomationCommand(scope, reading.category_revision, "ai.automation.draft.save", { rule_id: target?.id ?? null, expected_rule_revision: target?.revision ?? 0, spec: automationFormSpec(local.form, reading), restored_from: null }); start({ kind: "command", stage: "execute", command }); }
    catch (value) { setError(message(value)); }
  }
  function prepare(operation: "ai.automation.activate" | "ai.automation.pause") {
    if (!reading || !detail) return;
    const version = operation === "ai.automation.pause" ? detail.rule.published : detail.rule.draft ?? detail.rule.published;
    if (!version) return;
    try { start({ kind: "command", stage: "preview", command: newAutomationCommand(scope, reading.category_revision, operation, { rule_id: detail.rule.id, expected_rule_revision: detail.rule.revision, version_id: version.id }) }); }
    catch (value) { setError(message(value)); }
  }
  function confirm() {
    const pending = currentLocal.current.pending;
    if (!pending || pending.kind !== "command" || pending.stage !== "confirm" || !pending.preview || !automationPreviewCurrent(pending.preview)) return;
    const request: AutomationPending = { kind: "command", stage: "execute", command: pending.command };
    if (rememberEvent({ ...currentLocal.current, pending: request })) void perform(stamp => send(request, stamp));
  }
  const frozen = busy || broken || denied || !!local.pending, selected = detail?.rule;
  const pending = local.pending, preview = pending?.kind === "command" && pending.stage === "confirm" ? pending.preview : null;
  return <section aria-label="自动化规则" className="min-w-0 space-y-4 rounded-lg border border-border p-4 sm:p-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">自动化规则</h2><p className="mt-1 text-sm text-muted-foreground">固定触发设置、目标、停止条件和预算；自动运行由实际服务授权办理。</p></div><Button size="sm" variant="outline" disabled={busy} onClick={() => void perform(async stamp => { setReading(null); setDetail(null); await read(stamp); })}><ArrowClockwise aria-hidden="true"/>刷新规则</Button></header>
    <p className="text-sm text-muted-foreground">支持本人手动、定时、领域事件和相对里程碑。自动规则经本人一次确认激活并绑定服务授权，由服务身份执行，不冒用委托人的真人会话。外部来源、联网、MCP 和业务写入保持关闭；只读模型工作可能产生费用，实际授权、资格、协议与预算由服务器核对。</p>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}{notice && <p role="status" className="break-all text-sm">{notice}</p>}
    {busy && <p role="status" className="text-sm">正在读取或核对此次规则请求…</p>}
    {!reading && !busy && <p className="text-sm">规则列表尚未取得，不能按空列表或已启用处理。</p>}
    {reading && <div className="space-y-3"><p className="text-xs text-muted-foreground">当前品类 {categoryId} · 本人 {principalId} · 读取时点 {reading.as_of}</p>{!reading.rules.length && <p className="text-sm">当前可读范围内尚无本人规则。</p>}<div className="grid gap-3 sm:grid-cols-2">{reading.rules.map(rule => <article className="min-w-0 space-y-2 rounded-lg border border-border p-3 text-sm" key={rule.id}><h3 className="break-words font-medium">{rule.name}</h3><p>{stateNames[rule.state]} · 当前 v{rule.revision} · 已受理 {rule.admitted_count} 次</p><p className="break-all text-xs text-muted-foreground">规则 {rule.id}<br/>最近受理 {rule.last_admitted_at ?? "尚无记录"}</p><Button size="sm" variant="outline" disabled={frozen} onClick={() => choose(rule.id)}>读取规则与运行历史</Button></article>)}</div><Button size="sm" variant="outline" disabled={frozen} onClick={() => edit()}><Plus aria-hidden="true"/>新建规则草稿</Button></div>}
    {selected && detail && <section aria-label="所选固定规则" className="space-y-3 rounded-lg border border-border p-3 text-sm"><h3 className="break-words font-medium">{selected.name} · {stateNames[selected.state]}</h3><p>触发方式：{selected.draft || selected.published ? triggerNames[(selected.draft ?? selected.published)!.spec.trigger_kind] : "固定设置尚未取得"}</p>{serviceGrant(selected.service_grant)}{selected.draft && <p className="break-all">草稿范围：{selected.draft.spec.product_id ? `固定型号 ${selected.draft.spec.product_id}` : `当前品类 ${categoryId}`}</p>}{selected.published && <p className="break-all">已发布范围：{selected.published.spec.product_id ? `固定型号 ${selected.published.spec.product_id}` : `当前品类 ${categoryId}`}</p>}<p>草稿 {selected.draft ? `v${selected.draft.revision} · ${selected.draft.id}` : "尚无"}<br/>已发布 {selected.published ? `v${selected.published.revision} · ${selected.published.id}` : "尚无"}</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={frozen || selected.state === "retired"} onClick={() => edit(selected)}>编辑新草稿</Button>{selected.state !== "retired" && (selected.draft || selected.state === "paused") && <Button size="sm" disabled={frozen} onClick={() => prepare("ai.automation.activate")}><Play aria-hidden="true"/>{selected.draft ? "预览启用固定草稿" : "预览恢复本规则"}</Button>}{selected.state === "active" && selected.published && <><Button size="sm" variant="outline" disabled={frozen} onClick={() => prepare("ai.automation.pause")}><Pause aria-hidden="true"/>预览暂停新运行</Button>{selected.published.spec.trigger_kind === "manual" && <Button size="sm" disabled={frozen} onClick={() => start({ kind: "trigger", ruleId: selected.id, body: { expected_rule_revision: selected.revision, version_id: selected.published!.id, idempotency_key: crypto.randomUUID() } })}>本人手动触发（可能产生模型费用）</Button>}</>}</div>{selected.published && <details><summary>读取已发布的目标、服务范围和预算声明</summary><pre className="mt-2 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted/40 p-3 text-xs">{JSON.stringify(selected.published.spec, null, 2)}</pre><p className="mt-2 text-muted-foreground">这是固定规则声明；不代表当前运行已经取得资格或额度。</p></details>}<details><summary>规则版本与办理回执</summary><ul className="mt-2 space-y-2">{detail.history.map(row => <li className="break-all" key={row.id}>{row.action} · v{row.revision} · 办理人 {row.actor_id}<br/>{row.created_at} · 回执 {row.receipt_id}</li>)}</ul></details><h4 className="font-medium">触发来源与抑制原因</h4>{!detail.triggers.length && <p>尚无实际触发记录。</p>}{detail.triggers.map(trigger => <article key={trigger.id} className="space-y-2 rounded-lg border border-border p-2"><p className="break-all">{triggerNames[trigger.kind]} · {trigger.decision === "suppressed" ? "已抑制，未创建新运行" : trigger.decision === "admitted" ? "已受理" : "等待受理"}<br/>固定版本 {trigger.version_id}<br/>记录时点 {trigger.created_at} · 受理时点 {trigger.admitted_at ?? "尚无"}</p>{trigger.error_code && <p className="break-all">实际原因：{trigger.error_code}</p>}<details><summary>实际触发来源</summary><pre className="max-w-full whitespace-pre-wrap break-all text-xs">{JSON.stringify(trigger.source, null, 2)}</pre></details>{trigger.run_id && <p className="break-all">原运行 {trigger.run_id}</p>}</article>)}<h4 className="font-medium">实际运行历史</h4>{!detail.runs.length && <p>尚无已受理的运行记录。</p>}{detail.runs.map(run => <article key={run.id} className="space-y-2 rounded-lg border border-border p-2"><p className="break-all">{run.state} · {run.created_at}<br/>固定规则版本 {run.version_id}<br/>原运行 {run.run_id}</p>{onOpenRun && <Button size="sm" variant="outline" onClick={() => onOpenRun(run.run_id, categoryId)}>打开原运行并接续<ArrowRight aria-hidden="true"/></Button>}</article>)}</section>}
    {reading && !denied && <form onSubmit={saveDraft} className="space-y-3"><h3 className="font-medium">{local.editRuleId ? "保存此规则的新草稿" : "新规则草稿"}</h3><fieldset disabled={frozen} className="space-y-3">{!local.editRuleId && <label className="block text-sm">实际型号 UUID（可选，相对里程碑必填）<input className={inputClass} value={local.form.productId} onChange={event => formChange({ productId: event.target.value })}/></label>}<label className="block text-sm">规则固定范围<input readOnly className={inputClass} value={local.form.productId ? `固定型号 ${local.form.productId}` : `当前品类 ${categoryId}`}/></label><TriggerFields form={local.form} eventTypes={reading.event_types} change={formChange}/>{([{ key: "name", label: "规则名称" }, { key: "goal", label: "工作目标" }, { key: "purpose", label: "用途" }, { key: "stop", label: "停止条件" }] as const).map(row => <label className="block text-sm" key={row.key}>{row.label}{row.key === "goal" || row.key === "stop" ? <textarea required rows={2} className={inputClass} value={local.form[row.key]} onChange={event => formChange({ [row.key]: event.target.value })}/> : <input required className={inputClass} value={local.form[row.key]} onChange={event => formChange({ [row.key]: event.target.value })}/>}</label>)}<fieldset className="space-y-2"><legend className="text-sm font-medium">固定使用的技能版本</legend>{!reading.skills.length && <p className="text-sm text-muted-foreground">未取得可选技能，不能准备此规则。</p>}{reading.skills.map(skill => <label className="flex items-start gap-2 break-words text-sm" key={skill.key}><input type="checkbox" className="mt-1" checked={local.form.skills.includes(skill.key)} onChange={event => formChange({ skills: event.target.checked ? [...local.form.skills, skill.key] : local.form.skills.filter(value => value !== skill.key) })}/><span>{skill.name} · {skill.version}</span></label>)}</fieldset><label className="block text-sm">本人实际预算<select required className={inputClass} value={local.form.budgetId} onChange={event => { const budget = reading.budgets.find(row => row.id === event.target.value); formChange({ budgetId: event.target.value, ...(budget ? { amount: automationDollars(budget.limit_micro_usd), input: String(budget.input_token_limit), output: String(budget.output_token_limit), calls: String(budget.call_limit) } : {}) }); }}><option value="">请选择实际预算</option>{reading.budgets.map(budget => <option key={budget.id} value={budget.id}>{budget.id} · {automationDollars(budget.limit_micro_usd)} USD</option>)}</select></label><p className="text-sm text-muted-foreground">规则声明的上限与本人实际预算共同约束新运行；选择预算不会充值或授予服务权限。</p><div className="grid gap-3 sm:grid-cols-2">{([{ key: "amount", label: "本规则费用上限（USD）", step: "0.000001", min: 0 }, { key: "input", label: "输入 token 上限", min: 1 }, { key: "output", label: "输出 token 上限", min: 1 }, { key: "calls", label: "模型调用次数上限", min: 1 }, { key: "tokens", label: "单次工作 token 上限", min: 1 }, { key: "cooldown", label: "两次受理冷却秒数", min: 0 }, { key: "maxRuns", label: "最多受理运行数", min: 1 }] as const).map(row => <label className="block text-sm" key={row.key}>{row.label}<input required type="number" min={row.min} step={"step" in row ? row.step : 1} className={inputClass} value={local.form[row.key]} onChange={event => formChange({ [row.key]: event.target.value })}/></label>)}</div></fieldset><Button type="submit" disabled={frozen || !reading.skills.length || !reading.budgets.length}>{local.form.triggerKind === "manual" ? "保存手动规则草稿" : "保存自动触发规则草稿"}</Button></form>}
    {preview && <section aria-label="确认规则状态变更" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><h3 className="font-medium">{preview.command.operation === "ai.automation.pause" ? "确认暂停新运行" : "确认启用固定规则版本"}</h3><p>规则 {(preview.command.payload as { rule_id: string }).rule_id} · 固定版本 {(preview.command.payload as { version_id: string }).version_id}</p><pre className="max-w-full overflow-auto whitespace-pre-wrap break-all bg-muted/40 p-2 text-xs">{JSON.stringify(preview.review, null, 2)}</pre><p>{preview.command.operation === "ai.automation.pause" ? "暂停只停止新运行；已受理工作的状态继续由原运行办理。" : automationRecord(preview.review.after) && automationRecord(preview.review.after.spec) && preview.review.after.spec.trigger_kind !== "manual" ? "本人确认将固定自动触发设置与服务授权；到达实际触发条件后可能产生模型费用，后台由服务身份办理。" : "启用后仍需本人明确手动触发；本次确认不会发起模型调用。"}</p>{automationRecord(preview.review.service_authorization) && <section aria-label="本次固定服务授权" className="space-y-2"><h4 className="font-medium">本次实际服务授权</h4><pre className="max-w-full whitespace-pre-wrap break-all bg-muted/40 p-2 text-xs">{JSON.stringify(preview.review.service_authorization, null, 2)}</pre><p>授权由服务器准备并随本次确认绑定，不从表单选择或提交执行身份。</p></section>}<Button disabled={busy || !automationPreviewCurrent(preview)} onClick={confirm}>确认此次规则状态变更</Button>{!automationPreviewCurrent(preview) && <p>本次确认已过期，请返回重新预览。</p>}</section>}
    {pending && !preview && <section aria-label="原规则请求恢复" className="space-y-3 rounded-lg border border-primary/40 p-3 text-sm"><p>{pending.kind === "trigger" ? "原手动触发受理结果待核对" : pending.stage === "preview" ? "原状态变更预览待核对" : "原规则保存结果待核对"}。刷新和重新打开只读取，不会自动再次提交。</p><Button variant="outline" disabled={busy || broken || denied} onClick={() => void perform(stamp => send(pending, stamp))}>{pending.kind === "trigger" ? "按原请求核对手动触发" : pending.stage === "preview" ? "重试原状态预览" : "核对并重试原保存请求"}</Button></section>}
    {pending && (preview || pending.kind === "command" && pending.stage === "preview" || rejected) && <Button size="sm" variant="outline" disabled={busy} onClick={() => { if (rememberEvent({ ...currentLocal.current, pending: null })) { setError(""); setRejected(false); } }}>{rejected ? "放弃已明确拒绝的本机请求，返回修改" : "取消本次预览，返回修改"}</Button>}
    {broken && <p className="text-sm text-destructive">本机恢复记录未能安全读取或保存。请恢复本机存储后重新打开；当前不发起新请求。</p>}
  </section>;
}
