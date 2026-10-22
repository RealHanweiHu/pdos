"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { ClipboardText, LockKey, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  candidateFormBasisKey, candidateLinkKey, candidateMappingKey, candidatePayload, candidateSourceKey,
  validCandidateMaterials, validCandidateScope,
  type CandidateFormPayload, type CandidateFormScope, type CandidateFormSelection, type CandidateMaterials,
} from "./candidate-form-contract";

export type CandidateFormProps = {
  scope: CandidateFormScope | null;
  materials?: CandidateMaterials;
  /** The host alone checks capability, current evaluation, privacy, pending and UNKNOWN state. */
  disabled?: boolean;
  busy?: boolean;
  disabledReason?: string;
  allowProductVisibility?: boolean;
  /** Current editable draft only. Never clear a prepared command/pending recovery on null. */
  onChange: (payload: CandidateFormPayload | null) => void;
  onSubmit: (payload: CandidateFormPayload) => void;
};
const emptyMaterials: CandidateMaterials = { links: [], mappings: [], sources: [] };
const wrap = "min-w-0 [overflow-wrap:anywhere]";
const inputClass = "min-h-11 w-full min-w-0 rounded-lg border bg-background px-3 py-2 text-sm";
const emptySelection: CandidateFormSelection = { links: [], mappings: [], sources: [], reason: "", visibility: "private" };
const toggled = (keys: readonly string[], key: string): string[] =>
  keys.includes(key) ? keys.filter(value => value !== key) : [...keys, key];

/** No transport, new command/key, preview, confirmation or qualification inference. */
export function CandidateForm({ scope, materials = emptyMaterials, disabled = true, busy = false,
  disabledReason, allowProductVisibility = false, onChange, onSubmit }: CandidateFormProps) {
  const scopeValid = validCandidateScope(scope);
  const materialsValid = scopeValid && validCandidateMaterials(scope, materials);
  const basis = scopeValid && materialsValid ? candidateFormBasisKey(scope, materials) : null;
  // Commit the event gate before invalidating the editable parent draft. A
  // discarded render does not mutate the committed scope or unlock old events.
  const unlocked = disabled === false && busy !== true;
  const live = useRef<{ basis: string | null; unlocked: boolean }>({ basis: null, unlocked: false });
  const notified = useRef<string | null | undefined>(undefined);
  useLayoutEffect(() => {
    live.current = { basis, unlocked };
    if (notified.current !== basis) { notified.current = basis; onChange(null); }
    return () => { live.current = { basis: null, unlocked: false }; };
  }, [basis, unlocked, onChange]);
  const change = (payload: CandidateFormPayload | null) => {
    if (basis !== null && live.current.basis === basis && live.current.unlocked) onChange(payload);
  };
  const submit = (payload: CandidateFormPayload) => {
    if (basis !== null && live.current.basis === basis && live.current.unlocked) onSubmit(payload);
  };

  if (!scopeValid) return <section className={`panel space-y-3 ${wrap}`} aria-label="复验候选材料">
    <h3 className="text-base font-semibold">复验候选材料</h3>
    <p className="text-sm">当前固定问题、整改或访问范围尚不能核对，不能显示材料或填写候选。</p>
  </section>;
  if (!materialsValid) return <section className={`panel space-y-3 ${wrap}`} aria-label="复验候选材料">
    <h3 className="text-base font-semibold">复验候选材料</h3>
    <p role="alert" className="text-sm">返回的真实选项不完整或重复，请由宿主重新读取核对；不能猜测固定版本或来源。</p>
  </section>;
  // Complete scope/material bytes key the local form. A new Current or choice
  // never silently inherits an old reason/selection. Parent commands remain untouched.
  return <CandidateFields key={basis} scope={scope} materials={materials} disabled={disabled}
    busy={busy} disabledReason={disabledReason} allowProductVisibility={allowProductVisibility}
    onChange={change} onSubmit={submit} />;
}

function CandidateFields({ scope, materials, disabled = true, busy = false, disabledReason,
  allowProductVisibility = false, onChange, onSubmit }: Omit<CandidateFormProps, "scope" | "materials"> & {
    scope: CandidateFormScope; materials: CandidateMaterials;
  }) {
  const id = useId();
  const [selection, setSelection] = useState<CandidateFormSelection>(emptySelection);
  const locked = disabled !== false || busy === true;
  const payload = candidatePayload(scope, materials, selection, allowProductVisibility);
  const sharingAllowed = allowProductVisibility === true && scope.visibility === "product" &&
    materials.links.filter(choice => selection.links.includes(candidateLinkKey(choice.ref))).every(choice => choice.visibility === "product") &&
    materials.mappings.filter(choice => selection.mappings.includes(candidateMappingKey(choice.mapping))).every(choice => choice.visibility === "product") &&
    materials.sources.filter(choice => selection.sources.includes(candidateSourceKey(choice.reference))).every(choice => choice.visibility === "product");
  function change(next: CandidateFormSelection) {
    if (locked) return;
    setSelection(next);
    onChange(candidatePayload(scope, materials, next, allowProductVisibility));
  }

  return <section className={`panel space-y-4 ${wrap}`} aria-label="复验候选材料" aria-busy={busy}>
    <div className="space-y-1">
      <h3 className="flex items-center gap-2 text-base font-semibold"><ClipboardText aria-hidden className="size-5 shrink-0" />复验候选材料</h3>
      <p className="subtle">固定原失败与后续复验的对应，保存后仍待核对适用性、独立核验和观察完整性。</p>
    </div>
    <div className={`rounded-lg border p-3 text-sm space-y-1 ${wrap}`}>
      <p>{scope.issue_label || "当前固定问题"} · 当前第 {scope.current_issue.revision} 版用于并发核对</p>
      <p>{scope.capa_label || "当前固定整改"}</p>
      <p>{scope.origin_issue ? `原失败依据固定在第 ${scope.origin_issue.revision} 版，保留历史。` : "原失败固定版本尚未提供，不能推定其与当前版相同。"}</p>
      <p>本候选不作有效性决定，不关闭问题，也不放行产品。</p>
    </div>
    {locked && <p role="status" className="flex items-start gap-2 rounded-lg border p-3 text-sm">
      <LockKey aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{disabledReason || (busy ? "宿主正在办理，当前材料已锁定。" : "当前尚未接通可办理能力，材料填写与提交暂不可用。")}
        已有请求结果未知时，只能由宿主按原请求恢复，不能另发候选。</span>
    </p>}
    <fieldset disabled={locked} className={`space-y-4 ${wrap}`}>
      <legend className="text-sm font-medium">选择本次固定材料</legend>
      <fieldset className={`space-y-2 ${wrap}`}>
        <legend className="mb-2 text-sm font-medium">实际整改回链（最多 20 条）</legend>
        {!materials.links.length && <p className="subtle">暂无可选的真实整改回链。空选不会推定整改已履行。</p>}
        {materials.links.map(choice => {
          const key = candidateLinkKey(choice.ref);
          const selected = selection.links.includes(key);
          return <label key={key} className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${wrap}`}>
            <input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary" checked={selected}
              disabled={!selected && selection.links.length >= 20}
              onChange={() => change({ ...selection, links: toggled(selection.links, key) })} />
            <span className={wrap}><span className="font-medium">{choice.label || "固定回链，名称尚未提供"} · 第 1 版</span>
              <span className="mt-1 block text-muted-foreground">{choice.detail || "具体业务说明尚未提供，请核对宿主固定记录。"}</span></span>
          </label>;
        })}
      </fieldset>
      <fieldset className={`space-y-2 ${wrap}`}>
        <legend className="mb-2 text-sm font-medium">原失败与实际复验对应（最多 10000 项）</legend>
        {!materials.mappings.length && <p className="subtle">暂无可选的真实失败对应。不填写测量值，不猜测样件、测试项或通过结论。</p>}
        {materials.mappings.map(choice => {
          const key = candidateMappingKey(choice.mapping);
          const selected = selection.mappings.includes(key);
          return <div key={key} className={`rounded-lg border p-3 text-sm space-y-2 ${wrap}`}>
            <label className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary" checked={selected}
                disabled={!selected && selection.mappings.length >= 10000}
                onChange={() => change({ ...selection, mappings: toggled(selection.mappings, key) })} />
              <span className={`font-medium ${wrap}`}>{choice.label || "固定失败对应，名称尚未提供"}</span>
            </label>
            <dl className="grid min-w-0 grid-cols-1 gap-1 sm:grid-cols-2">
              <div className={wrap}><dt className="text-muted-foreground">原值（只读）</dt><dd>{choice.original_value ?? "尚未提供，保持未知"}</dd></div>
              <div className={wrap}><dt className="text-muted-foreground">工况（只读）</dt><dd>{choice.conditions ?? "尚未提供，保持未知"}</dd></div>
              <div className={wrap}><dt className="text-muted-foreground">原记录时钟</dt><dd className="font-mono">{choice.occurred_at ?? "尚未提供，保持未知"}</dd></div>
              <div className={wrap}><dt className="text-muted-foreground">原时区</dt><dd>{choice.original_timezone ?? "尚未提供，保持未知"}</dd></div>
            </dl>
            <p className="subtle">固定测试第 {choice.mapping.run.revision} 版 · 样件第 {choice.mapping.sample_revision} 版 · 实际配置第 {choice.mapping.actual_configuration_revision} 版</p>
            <p>{choice.detail || "实际对应的适用性尚需服务器与专业人员独立核对。"}</p>
            <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">查看固定对应与出处</summary>
              <p className={wrap}>原失败：{choice.mapping.failure_id}</p>
              <p className={wrap}>测试记录：{choice.mapping.run.id} · 样件：{choice.mapping.sample_id} · 测试项：{choice.mapping.item_id}</p>
              <p className={wrap}>实际配置：{choice.mapping.actual_configuration_id}</p>
              <p className={wrap}>测量：{choice.mapping.measurement_id ?? "未提供"} · 计算结果：{choice.mapping.projection_id ?? "未提供"}</p>
              {!choice.mapping.applicability_sources.length && <p>未提供对应适用性出处，保持未知。</p>}
              {choice.mapping.applicability_sources.map(ref => <p key={candidateSourceKey(ref)} className={`whitespace-pre-wrap ${wrap}`}>
                固定出处 {ref.artifact_id} · 第 {ref.expected_revision} 版 · 第 {ref.line} 行：{ref.quote}
              </p>)}
            </details>
          </div>;
        })}
      </fieldset>
      <fieldset className={`space-y-2 ${wrap}`}>
        <legend className="mb-2 text-sm font-medium">候选精确出处（最多 20 条）</legend>
        {!materials.sources.length && <p className="subtle">暂无可选的真实原文行。空选不会补造来源。</p>}
        {materials.sources.map(choice => {
          const ref = choice.reference;
          const key = candidateSourceKey(ref);
          const selected = selection.sources.includes(key);
          return <label key={key} className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${wrap}`}>
            <input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary" checked={selected}
              disabled={!selected && selection.sources.length >= 20}
              onChange={() => change({ ...selection, sources: toggled(selection.sources, key) })} />
            <span className={wrap}><span className="font-medium">{choice.title || "固定来源，名称尚未提供"} · 第 {ref.expected_revision} 版 · 第 {ref.line} 行</span>
              <span className={`mt-2 block whitespace-pre-wrap text-muted-foreground ${wrap}`}>{ref.quote}</span></span>
          </label>;
        })}
      </fieldset>
      <div className="space-y-2"><label htmlFor={`${id}-reason`} className="block text-sm font-medium">记录本候选的原因</label>
        <textarea id={`${id}-reason`} rows={3} className={inputClass} value={selection.reason}
          onChange={event => change({ ...selection, reason: event.target.value })} />
        <p className="subtle">填写 1 至 2000 字；不在原因中替代适用性或有效性批准。</p>
      </div>
      <div className="space-y-2"><label htmlFor={`${id}-visibility`} className="block text-sm font-medium">本候选可见范围</label>
        <select id={`${id}-visibility`} className={inputClass} value={selection.visibility}
          onChange={event => change({ ...selection, visibility: event.target.value === "product" ? "product" : "private" })}>
          <option value="private">仅本人可见</option><option value="product" disabled={!sharingAllowed}>产品范围可见（须宿主明确允许）</option>
        </select>
        <p className="subtle">默认仅本人可见；私人或受众尚不能核对的原材料不能扩大范围。</p>
        {selection.visibility === "product" && !sharingAllowed && <p role="alert" className="text-sm">所选材料或当前范围已不允许共享，请明确改选仅本人可见；不会自动改写原选择。</p>}
      </div>
      <p className="flex items-start gap-2 text-sm"><WarningCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span>回链、失败对应或出处可以暂缺，提交的候选仍保持待核对。原件安全、方法适用、独立性和观察条件由宿主另行核验。</span></p>
      <Button type="button" className="min-h-11 h-auto max-w-full whitespace-normal px-3 py-2 text-left [overflow-wrap:anywhere]"
        disabled={locked || payload === null} onClick={() => { if (!locked && payload) onSubmit(payload); }}>
        交给宿主核对本候选材料
      </Button>
      <p className="subtle">本按钮只交付所选材料；尚未预览、确认或保存。后续一次确认由共同办理入口执行。</p>
    </fieldset>
  </section>;
}
