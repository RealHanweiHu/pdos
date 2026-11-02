"use client";

import { useRef, useState } from "react";
import { ArrowUpRight, Check } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  catalogFields,
  catalogLabels,
  catalogTabs,
  type Field,
} from "./catalog-fields";
import type { CatalogDraft } from "./catalog-pai-draft";
import s from "./category-pai.module.css";
import {
  PaiCandidateShell,
  type CandidatePresentation,
} from "./pai-candidate-shell";

const primary = {
  competitor: ["name", "brand", "evidence", "source"],
  voice: ["name", "content", "source", "sample"],
  parameter: ["name", "key", "unit", "conditions", "source"],
};
export function CatalogPaiPreview({
  draft,
  disabled,
  editing,
  active,
  onEdit,
  update,
  save,
  open,
}: CandidatePresentation & {
  draft: CatalogDraft;
  disabled: boolean;
  update: (value: Partial<CatalogDraft>) => void;
  save: (draft: CatalogDraft) => {
    id?: string;
    version?: number;
    record?: import("./category-preview-state").CatalogRecord;
    error?: string;
  };
  open: (draft: CatalogDraft) => void;
}) {
  const [error, setError] = useState("");
  const submitted = useRef(false);
  const withdrawing = draft.action === "withdraw";
  const restoring = draft.base?.state === "withdrawn" && !withdrawing;
  const label = catalogLabels[draft.kind];
  const changes = draft.base
    ? catalogFields[draft.kind].filter(
        (f) =>
          (draft.values[f.key] ?? "").trim() !==
          (draft.base!.values[f.key] ?? "").trim(),
      )
    : [];
  const blocked =
    disabled ||
    (draft.base && !draft.reason.trim()) ||
    (!withdrawing &&
      (!draft.deidentified ||
        catalogFields[draft.kind].some(
          (f) => f.required && !draft.values[f.key]?.trim(),
        ) ||
        (draft.base && !restoring && !changes.length)));
  function field(f: Field) {
    const change = (value: string) => {
      update({
        values: { ...draft.values, [f.key]: value },
        deidentified: false,
      });
      setError("");
    };
    return (
      <label key={f.key} data-field={f.key}>
        {f.label}
        {f.required && " *"}
        {f.options ? (
          <select
            aria-label={`候选${f.label}`}
            value={draft.values[f.key] ?? ""}
            disabled={disabled}
            onChange={(e) => change(e.target.value)}
          >
            {!draft.values[f.key] && <option value="">未确认</option>}
            {f.options.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        ) : f.type === "textarea" ? (
          <textarea
            aria-label={`候选${f.label}`}
            disabled={disabled}
            required={f.required}
            value={draft.values[f.key] ?? ""}
            placeholder={f.placeholder}
            onChange={(e) => change(e.target.value)}
          />
        ) : (
          <input
            aria-label={`候选${f.label}`}
            disabled={disabled}
            readOnly={
              draft.kind === "parameter" && !!draft.base && f.key === "key"
            }
            type={f.type ?? "text"}
            min={f.min}
            step={f.step}
            required={f.required}
            value={draft.values[f.key] ?? ""}
            placeholder={f.placeholder}
            onInput={
              f.type === "date"
                ? (e) => change(e.currentTarget.value)
                : undefined
            }
            onChange={(e) => change(e.target.value)}
          />
        )}
      </label>
    );
  }
  if (draft.status !== "ready")
    return (
      <div className={s.receipt}>
        <span>
          {draft.status === "saved" ? (
            <>
              <Check size={14} />
              {draft.categoryName} · {draft.values.name} 已
              {withdrawing ? "撤回" : restoring ? "恢复" : "保存"} · v
              {draft.savedVersion}
            </>
          ) : draft.status === "discarded" ? (
            "已取消，未修改资料。"
          ) : (
            "此候选已更新，请查看下方的新版本。"
          )}
        </span>
        {draft.status === "saved" && (
          <button onClick={() => open(draft)}>
            查看已保存内容
            <ArrowUpRight size={13} />
          </button>
        )}
      </div>
    );
  return (
    <PaiCandidateShell
      editing={editing}
      active={active}
      onEdit={onEdit}
      title={draft.values.name || `新增${label}`}
      meta={`${draft.categoryName} · ${catalogTabs[draft.kind]}${draft.base ? ` · v${draft.base.version}` : ""}`}
      summary={[
        [
          withdrawing ? "操作" : draft.base ? "本次修改" : "内容",
          withdrawing
            ? "撤回记录，保留历史"
            : draft.base
              ? `${changes.length} 项 · ${changes.map((f) => f.label).join("、") || "待补充修改"}`
              : draft.kind === "voice"
                ? draft.values.content
                : draft.kind === "competitor"
                  ? `${draft.values.brand || "品牌待补充"} · ${draft.values.evidence || "类型未知"}`
                  : `${draft.values.unit || "单位待补充"} · ${draft.values.conditions || "条件待确认"}`,
        ],
        ["来源", draft.values.source || "待补充来源"],
      ]}
    >
      <form
        className={s.candidate}
        aria-label={`${label}候选`}
        onSubmit={(e) => {
          e.preventDefault();
          if (blocked || submitted.current) return;
          const result = save(draft);
          if (result.error || !result.id) {
            setError(result.error ?? "暂时无法保存，请重试。");
            return;
          }
          submitted.current = true;
          const next: CatalogDraft = {
            ...draft,
            status: "saved",
            savedRecord: result.record,
            savedId: result.id,
            savedVersion: result.version,
          };
          update(next);
        }}
      >
        {withdrawing ? (
          <p>撤回「{draft.values.name}」，不再参与当前汇总，历史版本仍保留。</p>
        ) : (
          <>
            <div className={s.fieldGrid}>
              {catalogFields[draft.kind]
                .filter((f) => primary[draft.kind].includes(f.key))
                .map(field)}
            </div>
            <details className={s.moreFields}>
              <summary>补充信息</summary>
              <div>
                {catalogFields[draft.kind]
                  .filter((f) => !primary[draft.kind].includes(f.key))
                  .map(field)}
              </div>
            </details>
          </>
        )}
        {draft.base && (
          <>
            {!withdrawing && (
              <p>
                本次修改 {changes.length} 项
                {!changes.length && !restoring && " · 可以继续对话补充"}
              </p>
            )}
            <label>
              {withdrawing ? "撤回原因" : "修订原因"}
              <textarea
                aria-label="候选维护原因"
                required
                disabled={disabled}
                value={draft.reason}
                onChange={(e) => {
                  update({ reason: e.target.value });
                  setError("");
                }}
                placeholder="说明本次维护的依据"
              />
            </label>
            <details className={s.moreFields}>
              <summary>对照原记录 · v{draft.base.version}</summary>
              <dl>
                {catalogFields[draft.kind].map((f) => (
                  <div key={f.key}>
                    <dt>{f.label}</dt>
                    <dd>{draft.base!.values[f.key] || "未填写 / 未知"}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </>
        )}
        {!withdrawing && (
          <label className={s.confirm}>
            <input
              type="checkbox"
              disabled={disabled}
              checked={draft.deidentified}
              onChange={(e) => update({ deidentified: e.target.checked })}
            />
            确认共享内容不含客户身份信息
          </label>
        )}
        {error && (
          <p className={s.error} role="alert">
            {error}
          </p>
        )}
        <footer>
          <button
            type="button"
            disabled={disabled}
            onClick={() => update({ status: "discarded" })}
          >
            取消维护
          </button>
          <Button type="submit" disabled={!!blocked}>
            {withdrawing
              ? "确认撤回"
              : restoring
                ? "确认恢复并修订"
                : draft.base
                  ? "确认保存新版本"
                  : `确认新增${label}`}
          </Button>
        </footer>
      </form>
    </PaiCandidateShell>
  );
}
