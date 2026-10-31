"use client";

import { ArrowUpRight, Check, PencilSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { CategoryDraft } from "./category-pai-draft";
import type { CatalogDraft } from "./catalog-pai-draft";
import type { ProposalDraft } from "./proposal-pai-draft";
import { ProposalSections } from "./proposal-sections";
import { catalogFields, catalogLabels } from "./catalog-fields";
import s from "./category-pai.module.css";

function Fields({ rows }: { rows: [string, string][] }) {
  return (
    <dl className={s.savedFields}>
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value || "待补充"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PaiSavedDocument({
  proposal,
  catalog,
  category,
  disabled,
  open,
  continueEditing,
}: {
  proposal?: ProposalDraft;
  catalog?: CatalogDraft;
  category?: CategoryDraft;
  disabled: boolean;
  open: () => void;
  continueEditing: () => void;
}) {
  const v = proposal?.savedProposal ?? proposal?.values;
  const record = catalog?.savedRecord;
  const withdrawn = record?.state === "withdrawn";
  const version = proposal?.savedVersion ?? catalog?.savedVersion;
  const primary = catalog
    ? catalogFields[catalog.kind].filter((f) =>
        [
          "name",
          "brand",
          "evidence",
          "source",
          "content",
          "sample",
          "key",
          "unit",
          "conditions",
        ].includes(f.key),
      )
    : [];
  const extra = catalog
    ? catalogFields[catalog.kind].filter((f) => !primary.includes(f))
    : [];
  return (
    <div className={s.editorForm}>
      <div
        className={`${s.candidate} ${s.savedDocument}`}
        aria-label="已保存内容"
      >
        <p className={s.saveNotice} role="status">
          <Check size={15} />
          <span>
            {withdrawn ? "已撤回" : "已保存"}
            {version ? ` · v${version}` : ""}
            <small>
              {proposal
                ? "私有草稿，尚未提交评审"
                : withdrawn
                  ? "历史版本仍保留"
                  : "已更新到品类资料"}
            </small>
          </span>
        </p>
        {v && (
          <>
            <Fields
              rows={[
                ["提案入口", v.entry],
                ["目标用户与场景", v.audience],
                ["要解决的问题", v.summary],
              ]}
            />
            <ProposalSections values={v} />
            <details className={s.moreFields}>
              <summary>品类资料与依据</summary>
              <p>{v.source}</p>
            </details>
          </>
        )}
        {catalog && (
          <>
            <Fields
              rows={primary.map((f) => [
                f.label,
                (record?.values ?? catalog.values)[f.key],
              ])}
            />
            {!!extra.length && (
              <details className={s.moreFields}>
                <summary>补充信息</summary>
                <Fields
                  rows={extra.map((f) => [
                    f.label,
                    (record?.values ?? catalog.values)[f.key],
                  ])}
                />
              </details>
            )}
          </>
        )}
        {category && (
          <Fields
            rows={[
              ["品类名称", category.name],
              ["主要场景", category.description],
            ]}
          />
        )}
        <footer>
          <button type="button" onClick={open}>
            {proposal
              ? "打开提案页"
              : catalog
                ? `查看${catalogLabels[catalog.kind]}资料`
                : "打开品类页"}
            <ArrowUpRight size={13} />
          </button>
          {(proposal?.savedProposal || record) && (
            <Button
              type="button"
              variant="outline"
              disabled={disabled}
              onClick={continueEditing}
            >
              <PencilSimple size={14} />
              {withdrawn ? "恢复并编辑" : "继续编辑"}
            </Button>
          )}
        </footer>
      </div>
    </div>
  );
}
