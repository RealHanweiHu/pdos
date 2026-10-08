"use client";

import { useId, type ReactNode } from "react";
import { ArrowClockwise, CheckCircle, Clock, LockKey, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  operations, tiers, uiSchema, same,
  type Evaluation, type Json, type Missing, type Operation, type Prepared,
  type SourceState, type VersionRef,
} from "./ui-contract";
import { canPrepare, outcomeLabel, type Notice, type UiState } from "./ui-state";

export type IssueOption = { ref: VersionRef; label: string };
export type OperationForm = { content: ReactNode; complete: boolean };
export type BusinessPreview = { content: ReactNode; complete: boolean };
export type UiViewCallbacks = {
  onSelectIssue: (ref: VersionRef | null) => void;
  onRefresh: () => void;
  onPrepare: (operation: Operation) => void;
  onConfirm: () => void;
  onRestore: () => void;
  onRepreview: () => void;
  onCancel: () => void;
};
/** Labels and slots are presentation only. The host retains all command and transport state. */
export type UiViewProps = {
  state: UiState;
  busy: boolean;
  callbacks: UiViewCallbacks;
  issueOptions?: readonly IssueOption[];
  /** Record key: kind:id:revision; principal name key: principal:id (no invented revision). */
  labels?: Readonly<Record<string, string>>;
  operationForms?: Partial<Readonly<Record<Operation, OperationForm>>>;
  renderPreview?: (review: Prepared["review"], operation: Operation) => BusinessPreview | null;
  detailSlots?: {
    failurePairs?: ReactNode;
    observationRecords?: ReactNode;
    reviewDetails?: ReactNode;
  };
};

const actionNames: Record<Operation, string> = {
  "quality.capa.verification.candidate.record": "记录复验候选",
  "quality.capa.observation.record": "记录实际观察",
  "quality.capa.verification.review": "具名专业复核",
  "quality.capa.effectiveness.decide": "具名决定措施有效性",
  "quality.issue.close": "单独具名关闭问题",
};
const actionDescriptions: Record<Operation, string> = {
  "quality.capa.verification.candidate.record": "固定复验与原失败的对应，适用性、独立核验和观察完整性仍保持未知。",
  "quality.capa.observation.record": "依据已发布的规则记录发生时间与实际观察，不从填写表单推定观察完整。",
  "quality.capa.verification.review": "按当前专业职责逐项复核适用性；未知保持未知，不能代替有效性决定。",
  "quality.capa.effectiveness.decide": "完整核对规则、观察与独立复核后，由具名人员分别作出有效性决定。",
  "quality.issue.close": "关闭是独立批准，既有有效性决定不会自动关闭问题或放行产品。",
};
const evaluationNames: Record<Evaluation, string> = {
  evaluated_current: "本次已核对当前事实",
  not_evaluated_historical: "历史固定版本，当前资格未评估",
  unavailable: "当前事实尚不能核对",
};
const sourceNames: Record<SourceState, string> = {
  current: "来源当前可核对", needs_recheck: "来源需重新核对", unavailable: "来源当前不可核对",
};
const noticeNames: Record<Notice, string> = {
  none: "",
  read_failed: "当前事实读取失败。请重试读取；尚未因本次读取发起业务操作。",
  read_cancelled: "本次读取已取消，当前事实仍待读取。可以手动重试。",
  selection_requires_explicit_choice: "返回的版本与当前选择不同，请明确选择要阅读的固定版本。",
  scope_rejected: "当前身份或访问范围不可用，相关资料与办理材料已清除。",
  saved: "已取得保存回执，当前事实仍需重新读取。请勿重复办理。",
  saved_read_failed: "已保存；后续读取失败。可以重试读取，不能重发已保存的操作。",
  saved_scope_rejected: "已取得保存结果；当前访问已不可用，相关资料与办理材料已清除。请勿重发。",
  not_started: "核对或预览尚未完成。可按原材料继续，尚未取得保存结果。",
  blocked: "当前办理条件不满足，请核对服务端返回的缺项与所选版本。",
  invalid_host_material: "返回的办理材料与当前固定范围不一致，不能继续提交。",
  original_request_only: "尚未取得确定保存回执。原材料与原标识已锁定，只能按原请求恢复核对。",
  preview_expired: "尚未提交的核对已过期。请用原材料重新预览，再人工确认。",
  not_saved_expired_proof: "服务端已明确核对原请求未保存且确认已过期。可用原材料重新预览，再人工确认。",
};
const touchButton = "min-h-11 h-auto max-w-full whitespace-normal px-3 py-2 text-left [overflow-wrap:anywhere]";
const wrap = "min-w-0 [overflow-wrap:anywhere]";
const hasContent = (content: ReactNode): boolean => Array.isArray(content) ? content.some(hasContent) :
  content !== undefined && content !== null && content !== false && content !== true && content !== "";

function Panel({ title, children, count }: { title: string; children: ReactNode; count?: number }) {
  return <section className={`panel space-y-3 ${wrap}`}>
    <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-base font-semibold">
      {title}{count !== undefined && <span className="text-xs font-normal text-muted-foreground">{count} 条固定记录</span>}
    </h3>
    {children}
  </section>;
}
function MissingList({ items }: { items: readonly Missing[] }) {
  if (!items.length) return <p className="subtle">本段未返回额外缺项；不据此推定资格或办理条件已满足。</p>;
  return <ul className="list-disc space-y-1 pl-5 text-sm">
    {items.map((item, i) => <li key={`${item.code}:${i}`} className={wrap}>{item.detail}</li>)}
  </ul>;
}
function RecordState({ evaluation, source }: { evaluation: Evaluation; source: SourceState }) {
  return <p className="subtle">{evaluationNames[evaluation]} · {sourceNames[source]}</p>;
}
function FixedRef({ kind, reference, labels }: {
  kind: string; reference: VersionRef; labels?: UiViewProps["labels"];
}) {
  const name = labels?.[`${kind}:${reference.id}:${reference.revision}`];
  return <div className={wrap}>
    <p className="text-sm">{name?.trim() ? name : "固定记录，名称尚未提供"} · 第 {reference.revision} 版</p>
    <details className="mt-1 text-xs text-muted-foreground">
      <summary className="cursor-pointer py-2">查看固定记录对账标识</summary>
      <p className={`py-1 font-mono ${wrap}`}>{reference.id}</p>
    </details>
  </div>;
}
function EventClock({ time, timezone, title = "记录的发生时间" }: {
  time: string; timezone: string; title?: string;
}) {
  return <div className="space-y-1 text-sm">
    <p>{title}：<span className={`font-mono ${wrap}`}>{time}</span></p>
    <p>原时区：<span className={wrap}>{timezone}</span></p>
  </div>;
}
function Person({ id, labels, title }: { id: string; labels?: UiViewProps["labels"]; title: string }) {
  return <div className="text-sm">
    <p>{title}：{labels?.[`principal:${id}`]?.trim() || "姓名尚未提供，保留具名记录"}</p>
    <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">查看具名人员对账标识</summary>
      <p className={`font-mono ${wrap}`}>{id}</p>
    </details>
  </div>;
}
function hasSaveTimePlaceholder(value: Json, depth = 0): boolean {
  if (value === "server_on_save") return true;
  if (depth > 40 || value === null || typeof value !== "object") return false;
  return Object.values(value).some(v => hasSaveTimePlaceholder(v, depth + 1));
}
function OutcomeNotice({ state }: { state: UiState }) {
  const saved = state.last_outcome === "saved";
  const message = noticeNames[state.notice] || (saved ? noticeNames.saved : "");
  if (!message) return null;
  return <div role="status" aria-live="polite" className={`rounded-lg border p-3 text-sm ${wrap}`}>
    <p className="flex items-start gap-2">
      {saved ? <CheckCircle className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden /> :
        <WarningCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}
      <span>{message}</span>
    </p>
  </div>;
}

/** No network, command construction, automatic retry, clock rewriting or authority inference. */
export function CapaEffectivenessView({ state, busy, callbacks, issueOptions = [], labels,
  operationForms, renderPreview, detailSlots }: UiViewProps) {
  const selectorId = useId();
  // The host clears private state on 401/403. Do not render externally retained slots or names.
  if (!state.context || state.schema_version !== uiSchema) return <section className="panel space-y-3" aria-label="整改复验办理">
    <h2 className="text-lg font-semibold">整改复验与关闭</h2>
    <OutcomeNotice state={state} />
    <p className="text-sm">当前访问范围尚未建立，不能显示资料或办理动作。</p>
  </section>;

  const model = state.model && same(state.model.context, state.context) &&
    same(state.model.issue.ref, state.selection) ? state.model : null;
  const pending = state.pending;
  const locked = pending !== null;
  const unknown = pending?.mode === "execute" && state.last_outcome === "unknown";
  const prepared = pending?.mode === "preview" ? state.preview : null;
  const businessPreview = prepared && renderPreview ? renderPreview(prepared.review, prepared.command.operation) : null;
  const previewCapability = prepared && model ? model.operations[prepared.command.operation] : null;
  const completePreview = businessPreview?.complete === true && hasContent(businessPreview.content);
  const confirmAllowed = !!prepared && completePreview && !busy && !state.read_failed && !state.loading &&
    previewCapability?.allowed === true && previewCapability.authority.authorized === true &&
    previewCapability.authority.qualified === true && previewCapability.current_evaluation === "evaluated_current" &&
    same(model?.current_issue, model?.issue.ref) && model?.issue.source_status === "current" &&
    !["blocked", "invalid_host_material"].includes(state.notice);
  const options = [...issueOptions];
  if (state.selection && !options.some(o => same(o.ref, state.selection))) options.push({
    ref: state.selection, label: `当前明确选择的固定问题版本 · 第 ${state.selection.revision} 版`,
  });
  const selectedKey = state.selection ? `${state.selection.id}:${state.selection.revision}` : "";
  const synthetic = model?.anchor?.nature === "synthetic" ||
    (model && operations.some(op => model.operations[op].authority.synthetic));

  return <div className={`space-y-4 ${wrap}`} aria-busy={busy || state.loading}>
    <section className="panel space-y-3">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className={wrap}><h2 className="text-lg font-semibold">整改复验与关闭</h2>
          <p className="subtle mt-1">固定原失败与后续复验，观察、专业复核、有效性与关闭分别办理。</p></div>
        <Button type="button" variant="outline" className={touchButton}
          disabled={busy || state.loading || locked} onClick={callbacks.onRefresh}>
          <ArrowClockwise aria-hidden />{state.loading ? "正在读取当前事实" : "读取当前事实"}
        </Button>
      </div>
      <OutcomeNotice state={state} />
      {synthetic && <p role="status" className="rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm">
        本地合成演练：用于核对办理流程，不代表真实专业资格、生产有效性或正式放行。
      </p>}
      <label htmlFor={selectorId} className="block text-sm font-medium">明确选择问题固定版本</label>
      <select id={selectorId} value={selectedKey} disabled={busy || locked}
        className="min-h-11 w-full min-w-0 rounded-lg border bg-background px-3 py-2 text-sm"
        onChange={event => callbacks.onSelectIssue(options.find(o => `${o.ref.id}:${o.ref.revision}` === event.target.value)?.ref ?? null)}>
        <option value="">请选择实际可读的问题版本</option>
        {options.map(option => <option key={`${option.ref.id}:${option.ref.revision}`} value={`${option.ref.id}:${option.ref.revision}`}>
          {option.label}
        </option>)}
      </select>
      <p className="subtle">当前版本变化不会自动替换所选历史版本。办理依据由服务器重新核对。</p>
    </section>

    {pending && <Panel title={unknown ? "按原请求恢复" : "本次办理进度"}>
      <p className="text-sm font-medium">{actionNames[pending.command.operation]}</p>
      {unknown ? <>
        <p className="text-sm flex items-start gap-2"><LockKey className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>提交结果未知，原材料、原标识及所选范围已锁定。不会因超时另造一次操作。</span></p>
        <Button type="button" className={touchButton} disabled={busy} onClick={callbacks.onRestore}>
          {busy ? "正在核对原请求" : "按原请求恢复核对"}
        </Button>
      </> : pending.mode === "expired_preview" ? <>
        <p className="text-sm">原材料保持不变。重新预览后仍需本人确认，不会自动批准。</p>
        <Button type="button" className={touchButton} disabled={busy} onClick={callbacks.onRepreview}>用原材料重新预览</Button>
        <Button type="button" variant="outline" className={`${touchButton} ml-0 sm:ml-2`} disabled={busy} onClick={callbacks.onCancel}>取消本次未提交办理</Button>
      </> : prepared ? <>
        <p className="text-sm">{prepared.named_decision ? "具名批准前完整核对" : "保存前完整核对"}</p>
        <p className="text-sm">{prepared.review.effect}</p>
        {businessPreview?.content ?? <p className="text-sm">完整业务预览尚未接通，不能确认保存。</p>}
        {hasSaveTimePlaceholder(prepared.review.before) || hasSaveTimePlaceholder(prepared.review.after) ?
          <p className="subtle">保存时由服务器记录的时点尚未生成；这是保存记录时间，不是实际观察发生时间。</p> : null}
        <p className="subtle">本次核对有效至：<span className={`font-mono ${wrap}`}>{prepared.expires_at}</span></p>
        {!completePreview && <p className="text-sm">办理材料或完整预览尚未接通，不能继续确认。</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="button" className={touchButton} disabled={!confirmAllowed} onClick={callbacks.onConfirm}>
            {prepared.named_decision ? "本人具名批准本次决定" : "核对上述内容，确认保存一次"}
          </Button>
          <Button type="button" variant="outline" className={touchButton} disabled={busy} onClick={callbacks.onCancel}>取消本次未提交办理</Button>
        </div>
      </> : <>
        <p className="text-sm">正在核对原办理材料。保存前还需完整预览及人工确认。</p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" className={touchButton} disabled={busy} onClick={callbacks.onRestore}>按原材料继续核对</Button>
          <Button type="button" variant="outline" className={touchButton} disabled={busy} onClick={callbacks.onCancel}>取消本次未提交办理</Button>
        </div>
      </>}
    </Panel>}

    {!model ? <Panel title="当前事实"><p className="text-sm">{state.loading ? "正在读取所选固定版本。" : "尚未取得对应固定版本的事实，请明确选择并读取。"}</p></Panel> : <>
      <Panel title="固定问题与原失败">
        <FixedRef kind="issue" reference={model.issue.ref} labels={labels} />
        <p className="text-sm">状态：{{ actioning: "措施办理中", awaiting_verification: "等待独立复验", closed: "已单独具名关闭" }[model.issue.status]}</p>
        <p className={`text-sm ${wrap}`}>用途：{model.issue.purpose}</p>
        <RecordState evaluation={model.issue.current_evaluation} source={model.issue.source_status} />
        <p className="subtle">{same(model.issue.ref, model.current_issue) ? "所选版本为服务器返回的当前版本。" : "所选历史版本只读；当前版本不由本页推算。"}</p>
        {model.anchor ? <div className="space-y-2 rounded-lg border p-3">
          <p className="text-sm font-medium">固定整改依据</p><FixedRef kind="anchor" reference={model.anchor.ref} labels={labels} />
          <p className="subtle">{sourceNames[model.anchor.source_status]} · {model.anchor.visibility === "private" ? "私人范围" : "产品范围"}</p>
          <p className="text-sm">保留最初失败版本：</p><FixedRef kind="issue" reference={model.anchor.origin_issue} labels={labels} />
        </div> : <p className="text-sm">固定整改依据尚未取得，不能从后续回链补造原失败事实。</p>}
        {detailSlots?.failurePairs ?? <p className="text-sm">原失败与新复验的逐样件、逐测试项完整对应尚未接通；不能只凭回链摘要认定已复验。</p>}
        <MissingList items={model.missing} />
      </Panel>

      <Panel title="晚回链与后续复验" count={model.late_links.length}>
        {!model.late_links.length && <p className="text-sm">尚未返回晚回链记录。</p>}
        {model.late_links.map(link => <article key={link.ref.id} className="space-y-2 rounded-lg border p-3">
          <FixedRef kind="late_link" reference={link.ref} labels={labels} />
          <p className="text-sm font-medium">{link.meaning === "planned" ? "计划与历史回链，未证明实际复验" : "宿主已返回实际办理回链，仍须核对完整事实"}</p>
          <RecordState evaluation={link.current_evaluation} source={link.source_status} />
          <p className="text-sm">固定验证请求：</p><FixedRef kind="formal" reference={link.formal} labels={labels} />
          {link.run ? <><p className="text-sm">固定复验轮次：</p><FixedRef kind="run" reference={link.run} labels={labels} /></> :
            <p className="text-sm">尚未返回实际复验轮次。</p>}
          <MissingList items={link.missing} />
        </article>)}
      </Panel>

      <Panel title="复验候选" count={model.candidates.length}>
        {!model.candidates.length && <p className="text-sm">尚未返回固定候选。</p>}
        {model.candidates.map(candidate => <article key={candidate.ref.id} className="space-y-2 rounded-lg border p-3">
          <FixedRef kind="candidate" reference={candidate.ref} labels={labels} />
          <p className="text-sm">固定整改依据：</p><FixedRef kind="anchor" reference={candidate.anchor} labels={labels} />
          <p className="text-sm">固定回链：</p><FixedRef kind="late_link" reference={candidate.late_link} labels={labels} />
          <p className="text-sm">{outcomeLabel(candidate.result)}</p>
          <dl className="grid min-w-0 grid-cols-1 gap-2 text-sm sm:grid-cols-3">
            <div><dt className="subtle">适用性</dt><dd>未知</dd></div>
            <div><dt className="subtle">独立核验</dt><dd>未知</dd></div>
            <div><dt className="subtle">观察完整性</dt><dd>未知</dd></div>
          </dl>
          <RecordState evaluation={candidate.current_evaluation} source={candidate.source_status} />
          <MissingList items={candidate.missing} />
        </article>)}
      </Panel>

      <Panel title="观察规则" count={model.rule_publications.length}>
        <p className="text-sm">规则由受控宿主发布。本页仅阅读，不能授予规则或专业资格。</p>
        {!model.rule_publications.length && <p className="text-sm">尚未取得已发布规则。</p>}
        {model.rule_publications.map(rule => <article key={rule.ref.id} className="space-y-2 rounded-lg border p-3">
          <FixedRef kind="rule" reference={rule.ref} labels={labels} />
          <p className="text-sm">{rule.nature === "synthetic" ? "本地合成规则，不代表生产资格" : "受控宿主返回的规则"}</p>
          <p className={`text-sm ${wrap}`}>有效范围：{rule.valid_from} 至 {rule.valid_until}</p>
          <RecordState evaluation={rule.current_evaluation} source={rule.source_status} />
          <MissingList items={rule.missing} />
        </article>)}
      </Panel>

      <Panel title="实际观察" count={model.observations.length}>
        {!model.observations.length && <p className="text-sm">尚未返回实际观察记录，不用当前时间补填。</p>}
        {model.observations.map(observation => <article key={observation.ref.id} className="space-y-2 rounded-lg border p-3">
          <FixedRef kind="observation" reference={observation.ref} labels={labels} />
          <p className={`text-sm ${wrap}`}>观察区间：{observation.observed_from} 至 {observation.observed_until}</p>
          <EventClock time={observation.occurred_at} timezone={observation.original_timezone} />
          <p className="text-sm">固定规则：</p><FixedRef kind="rule" reference={observation.rule} labels={labels} />
          <RecordState evaluation={observation.current_evaluation} source={observation.source_status} />
          <MissingList items={observation.missing} />
        </article>)}
        {detailSlots?.observationRecords ?? <p className="text-sm">逐项实际观察与措施完成明细尚未接通；时间摘要不代表观察已齐备。</p>}
      </Panel>

      <Panel title="具名专业复核" count={model.reviews.length}>
        {!model.reviews.length && <p className="text-sm">尚未返回独立专业复核。</p>}
        {model.reviews.map(review => <article key={review.ref.id} className="space-y-2 rounded-lg border p-3">
          <FixedRef kind="review" reference={review.ref} labels={labels} />
          <p className="text-sm">复核结论：{{ applicable: "适用", not_applicable: "不适用", unknown: "未知，保留缺项" }[review.conclusion]}</p>
          <Person id={review.reviewer_id} labels={labels} title="复核人员" />
          <p className="text-sm">固定候选：</p><FixedRef kind="candidate" reference={review.candidate} labels={labels} />
          <p className="text-sm">固定规则：</p><FixedRef kind="rule" reference={review.rule} labels={labels} />
          <p className="text-sm">固定观察记录：</p>
          {review.observations.map(reference => <FixedRef key={`${reference.id}:${reference.revision}`} kind="observation" reference={reference} labels={labels} />)}
          <EventClock time={review.occurred_at} timezone={review.original_timezone} title="复核记录的发生时间" />
          <RecordState evaluation={review.current_evaluation} source={review.source_status} />
          <MissingList items={review.missing} />
        </article>)}
        {detailSlots?.reviewDetails ?? <p className="text-sm">逐项专业复核依据与人员姓名明细尚未接通。</p>}
      </Panel>

      <Panel title="有效性与关闭">
        <p className="text-sm">{model.effectiveness ? outcomeLabel(model.effectiveness.outcome) : outcomeLabel("unknown")}</p>
        {model.effectiveness && <FixedRef kind="issue" reference={model.effectiveness.issue_ref} labels={labels} />}
        {model.effectiveness && <Person id={model.effectiveness.actor_id} labels={labels} title="有效性决定人员" />}
        <p className="text-sm">{model.issue.status === "closed" ? "服务器返回问题已关闭，历史事实仍保留。" : "问题尚未关闭，有效性决定与关闭分别办理。"}</p>
        <p className="subtle">未知不能变成无效；复核适用也不能自动变成有效、关闭或正式放行。</p>
      </Panel>

      <Panel title="本次可办理动作">
        {operations.map(operation => {
          const capability = model.operations[operation];
          const form = operationForms?.[operation];
          const formPresent = !!form && hasContent(form.content);
          const allowed = canPrepare(state, operation);
          return <article key={operation} className="space-y-3 rounded-lg border p-3">
            <h4 className="text-sm font-semibold">{actionNames[operation]} · {tiers[operation] === "T2" ? "具名批准" : "人工核对一次"}</h4>
            <p className="text-sm">{actionDescriptions[operation]}</p>
            <RecordState evaluation={capability.current_evaluation} source={model.issue.source_status} />
            {capability.current_evaluation === "evaluated_current" ? <p className="subtle">{capability.authority.qualified === null ? "专业资格尚不能核对" :
              capability.authority.qualified ? "服务器返回当前专业资格已核对" : "服务器返回当前专业资格不满足"}
              {capability.authority.authorized ? " · 本操作授权已核对" : " · 本操作当前未授权"}</p> :
              <p className="subtle">本段当前资格与权限未评估，不能办理。</p>}
            {tiers[operation] === "T2" && <p className="subtle">{capability.current_evaluation === "evaluated_current" && capability.independence === "verified" ? "服务器已核对独立办理条件" : "独立办理条件尚未得到核对"}</p>}
            <MissingList items={capability.missing} />
            {locked ? <p className="text-sm">已有原请求办理中，选择与表单保持锁定。</p> : formPresent ?
              <fieldset disabled={busy || !allowed} inert={busy || !allowed} className="min-w-0 space-y-3">
                <legend className="sr-only">{actionNames[operation]}办理材料</legend>{form!.content}
              </fieldset> : <p className="text-sm">办理材料尚未接通，不能预览或提交。</p>}
            {formPresent && !form!.complete && !locked && <p className="text-sm">完整实际选择与办理材料尚未准备齐，不能继续预览。</p>}
            <Button type="button" variant={tiers[operation] === "T2" ? "outline" : "default"}
              className={touchButton} disabled={busy || !allowed || !formPresent || form?.complete !== true}
              onClick={() => callbacks.onPrepare(operation)}><Clock aria-hidden />核对完整材料并预览</Button>
          </article>;
        })}
      </Panel>
    </>}
  </div>;
}
