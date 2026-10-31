"use client";

import { useRef, useState } from "react";
import { ArrowUpRight, Check } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  PaiCandidateShell,
  type CandidatePresentation,
} from "./pai-candidate-shell";
import { ProposalSections } from "./proposal-sections";
import { catalogLabels } from "./catalog-fields";
import type { ProposalDraft, ProposalValues } from "./proposal-pai-draft";
import { addProposalParameter } from "./proposal-pai-draft";
import type { CatalogRecord } from "./category-preview-state";
import s from "./category-pai.module.css";

export function ProposalPaiPreview({
  draft,
  parameters,
  disabled,
  editing,
  active,
  onEdit,
  update,
  save,
  open,
}: CandidatePresentation & {
  draft: ProposalDraft;
  parameters: CatalogRecord[];
  disabled: boolean;
  update: (value: Partial<ProposalDraft>) => void;
  save: (draft: ProposalDraft) => {
    id?: string;
    version?: number;
    proposal?: import("./product-preview-state").Proposal;
    error?: string;
  };
  open: (id: string) => void;
}) {
  const [error, setError] = useState("");
  const submitted = useRef(false);
  const v = draft.values;
  const { category, records, base } = draft.context;
  function patch(value: Partial<ProposalValues>) {
    update({ values: { ...v, ...value } });
    setError("");
  }
  if (draft.status !== "ready")
    return (
      <div className={s.receipt}>
        <span>
          {draft.status === "saved" ? (
            <>
              <Check size={14} />
              已保存 {v.title} · v{draft.savedVersion}
            </>
          ) : draft.status === "superseded" ? (
            "已生成新版本，见下方草稿。"
          ) : (
            "已取消，未修改提案。"
          )}
        </span>
        {draft.savedId && (
          <button onClick={() => open(draft.savedId!)}>
            查看已保存内容
            <ArrowUpRight size={13} />
          </button>
        )}
      </div>
    );
  const textField = (
    label: string,
    key: "title" | "audience" | "summary" | "choice",
    multiline = false,
  ) => (
    <label>
      {label}
      {multiline ? (
        <textarea
          aria-label={`候选${label}`}
          value={v[key]}
          disabled={disabled}
          onChange={(e) => patch({ [key]: e.target.value })}
        />
      ) : (
        <input
          aria-label={`候选${label}`}
          value={v[key]}
          disabled={disabled}
          required={key === "title"}
          onChange={(e) => patch({ [key]: e.target.value })}
        />
      )}
    </label>
  );
  return (
    <PaiCandidateShell
      editing={editing}
      active={active}
      onEdit={onEdit}
      title={v.title || "立项提案草稿"}
      meta={`${category.name} · ${base ? `修订 v${base.version}` : "新提案 · 私有"}`}
      summary={[
        ["产品方向", v.summary],
        [
          "已带入",
          `${records.filter((r) => r.kind === "competitor").length} 竞品 · ${records.filter((r) => r.kind === "voice").length} 用户声音 · ${records.filter((r) => r.kind === "parameter").length} 参数`,
        ],
        [
          "待完善",
          `${v.specs.length} 条关键规格 · ${v.questions.length} 个待决问题`,
        ],
      ]}
    >
      <form
        className={s.candidate}
        aria-label="提案候选"
        onSubmit={(e) => {
          e.preventDefault();
          if (
            disabled ||
            submitted.current ||
            !v.title.trim() ||
            (base && !draft.reason.trim())
          )
            return;
          const result = save(draft);
          if (!result.id || result.error) {
            setError(result.error ?? "暂时无法保存，请重试。");
            return;
          }
          submitted.current = true;
          update({
            status: "saved",
            savedProposal: result.proposal,
            savedId: result.id,
            savedVersion: result.version,
          });
        }}
      >
        <div className={s.identityFields}>
          {textField("提案名称", "title")}
          <label>
            提案入口
            <select
              aria-label="候选提案入口"
              disabled={disabled || !!base}
              value={v.entry}
              onChange={(e) =>
                patch({ entry: e.target.value as ProposalValues["entry"] })
              }
            >
              {["自主新品", "派生迭代", "客户需求"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
        </div>
        {textField("目标用户与场景", "audience")}
        {textField("要解决的问题", "summary", true)}
        <ProposalSections
          values={v}
          onChange={patch}
          disabled={disabled}
          parameters={parameters}
          onAddParameters={(selected) => {
            if (disabled) return false;
            const current = selected.map((record) =>
              parameters.find(
                (r) => r.id === record.id && r.version === record.version,
              ),
            );
            if (current.some((record) => !record)) return false;
            const next = current.reduce(
              (candidate, record) =>
                record ? addProposalParameter(candidate, record) : candidate,
              draft,
            );
            if (next === draft) return false;
            update(next);
            setError("");
            return true;
          }}
        />
        <details className={s.moreFields}>
          <summary>已带入的品类资料 · {records.length} 条</summary>
          <p>{category.description || "主要场景待补充"}</p>
          <p>已有型号：{category.models.join("、") || "暂无"}</p>
          <ul className={s.sourceList}>
            {records.map((r) => (
              <li key={`${r.id}:${r.version}`}>
                <strong>{r.values.name}</strong>
                <small>
                  {catalogLabels[r.kind]} · {r.id} v{r.version} ·{" "}
                  {r.values.evidence ||
                    r.values.classification ||
                    r.values.unit ||
                    "待确认"}
                </small>
                <small>{r.values.source || "来源待补充"}</small>
              </li>
            ))}
          </ul>
          <p>保留发起时与手动添加的资料快照；已有规格引用不会自动更新。</p>
        </details>
        {base && (
          <>
            <label>
              修订原因
              <input
                aria-label="候选提案修订原因"
                disabled={disabled}
                required
                value={draft.reason}
                onChange={(e) => update({ reason: e.target.value })}
              />
            </label>
            <details className={s.moreFields}>
              <summary>对照原提案 · v{base.version}</summary>
              <div>
                <strong>{base.title}</strong>
                <p>{base.summary}</p>
                <p>{base.audience}</p>
                {base.options.map((option, i) => (
                  <p key={i}>
                    方案 {i === 0 ? "A" : "B"}：{option}
                  </p>
                ))}
                <p>{base.choice}</p>
                {base.specs.map((row, i) => (
                  <p key={i}>{row.join(" · ")}</p>
                ))}
                {base.questions.map((q, i) => (
                  <p key={i}>
                    {q.title} · {q.owner || "待认领"} · {q.due || "期限待定"}
                  </p>
                ))}
              </div>
            </details>
          </>
        )}
        <p>
          AI 草稿 · {base ? "保留原版，确认后追加修订" : "默认私有，确认后创建"}
          。保存不提交 G0。
        </p>
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
            取消草稿
          </button>
          <Button
            type="submit"
            disabled={
              disabled || !v.title.trim() || (!!base && !draft.reason.trim())
            }
          >
            {base ? "确认保存修订" : "创建私有草稿"}
          </Button>
        </footer>
      </form>
    </PaiCandidateShell>
  );
}
