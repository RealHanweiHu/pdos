"use client";

import { useState } from "react";
import { ClipboardText } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { capaDraftTextPayload, capaTextDraft, capaTextEditable, type CapaTextDraft } from "@/lib/capa-draft-text-view";
import type { QualityIssue } from "@/lib/build-quality-loop-view";

type Props = {
  issue: QualityIssue; disabled: boolean; names: Map<string, string>;
  onSave: (draft: CapaTextDraft, element: HTMLElement) => void;
};

export function CapaDraftTextRevision({ issue, disabled, names, onSave }: Props) {
  const [draft, setDraft] = useState(() => capaTextDraft(issue));
  if (!draft) return <p className="subtle">未取得完整原 CAPA 与固定措施身份，当前只读；请刷新核对。</p>;
  const editable = !disabled && capaTextEditable(issue);
  let changed = false;
  try { capaDraftTextPayload(issue, draft); changed = true; } catch { /* Incomplete drafts remain editable; no submission. */ }
  return <details className="space-y-4">
    <summary className="cursor-pointer font-medium">续写未决 CAPA 的措施文本</summary>
    <p className="subtle">仅修改原措施的内容说明，保存为新的问题版本。措施身份、顺序、类型、责任人、假设与复核要求保持，旧版本继续保留。</p>
    {!editable && <p className="subtle">当前版本、来源或专业资格尚不可续写；已有根因决定、完成记录或回链时也不能办理。以服务器最新核对为准。</p>}
    <fieldset disabled={!editable} className="space-y-3">
      <legend className="subtle mb-2">原 CAPA · 问题 v{draft.revision}</legend>
      {draft.actions.map((action, index) => <div key={action.id} className="space-y-2 rounded-lg border border-border p-3">
        <p className="subtle">原措施 {index + 1} · {draft.fixedCapa.actions[index].kind === "corrective" ? "纠正" : "预防"} · {names.get(draft.fixedCapa.actions[index].executor_id) ?? "原具名责任人（身份保持）"}</p>
        <label className="block space-y-2 text-sm"><span>措施 {index + 1} 的内容说明，尚未执行</span>
          <textarea maxLength={2000} value={action.text} onChange={event => {
            if (!editable) return;
            setDraft({ ...draft, actions: draft.actions.map((row, i) => i === index ? { ...row, text: event.target.value } : row) });
          }}/>
        </label>
      </div>)}
    </fieldset>
    <div className="space-y-3 rounded-lg border border-border p-3">
      <p className="font-medium text-sm">原假设与复核要求（保持不变）</p>
      {draft.fixedCapa.hypotheses.map((hypothesis, index) => <p key={index} className="whitespace-pre-wrap text-sm">假设 {index + 1}：{String(hypothesis.text)}</p>)}
      <dl className="space-y-2 text-sm">
        <div><dt className="subtle">后续验证方法</dt><dd className="whitespace-pre-wrap">{draft.fixedCapa.requirement.method}</dd></div>
        <div><dt className="subtle">验收要求</dt><dd className="whitespace-pre-wrap">{draft.fixedCapa.requirement.acceptance}</dd></div>
        <div><dt className="subtle">独立观察终点（原值）</dt><dd>{draft.fixedCapa.requirement.observation_until}</dd></div>
      </dl>
    </div>
    <p className="subtle">本次仅保存草稿文本，不记录措施完成、有效性或关闭。</p>
    <Button disabled={!editable || !changed} onClick={event => { if (editable && changed) onSave(draft, event.currentTarget); }}><ClipboardText/>核对并保存文本续版</Button>
  </details>;
}
