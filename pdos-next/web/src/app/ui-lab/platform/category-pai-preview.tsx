"use client";

import { useRef, useState } from "react";
import { ArrowUpRight, Check } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { CategoryDraft } from "./category-pai-draft";
import s from "./category-pai.module.css";
import {
  PaiCandidateShell,
  type CandidatePresentation,
} from "./pai-candidate-shell";

export function CategoryPaiPreview({
  draft,
  disabled,
  editing,
  active,
  onEdit,
  update,
  create,
  open,
}: CandidatePresentation & {
  draft: CategoryDraft;
  disabled: boolean;
  update: (value: Partial<CategoryDraft>) => void;
  create: (
    name: string,
    description: string,
  ) => { id?: string; error?: string };
  open: (id: string) => void;
}) {
  const [error, setError] = useState("");
  const submitted = useRef(false);
  if (draft.status !== "ready")
    return (
      <div className={s.receipt}>
        <span>
          {draft.status === "created" ? (
            <>
              <Check size={14} />
              已创建 {draft.name}
            </>
          ) : draft.status === "superseded" ? (
            "此候选已更新，请查看下方的新版本。"
          ) : (
            "已取消创建，未新增品类。"
          )}
        </span>
        {draft.status === "created" && draft.categoryId && (
          <button onClick={() => open(draft.categoryId!)}>
            打开品类
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
      title={draft.name || "新建品类"}
      meta="品类草稿 · 待确认"
      summary={[
        ["主要场景", draft.description || "待补充"],
        ["范围", "品类共享 · 确认后创建"],
      ]}
    >
      <form
        className={s.candidate}
        aria-label="品类候选"
        onSubmit={(e) => {
          e.preventDefault();
          if (
            disabled ||
            submitted.current ||
            !draft.name.trim() ||
            !draft.deidentified
          )
            return;
          const result = create(draft.name, draft.description);
          if (result.error || !result.id) {
            setError(result.error ?? "暂时无法创建，请重试。");
            return;
          }
          submitted.current = true;
          update({
            status: "created",
            categoryId: result.id,
            name: draft.name.trim(),
            description: draft.description.trim(),
          });
        }}
      >
        <label>
          品类名称
          <input
            aria-label="候选品类名称"
            required
            disabled={disabled}
            value={draft.name}
            onChange={(e) => {
              update({ name: e.target.value, deidentified: false });
              setError("");
            }}
            placeholder="例如：自行车充气泵"
          />
        </label>
        <label>
          主要场景
          <textarea
            aria-label="候选主要场景"
            disabled={disabled}
            value={draft.description}
            onChange={(e) => {
              update({ description: e.target.value, deidentified: false });
              setError("");
            }}
            placeholder="面向谁，解决什么使用问题？"
          />
        </label>
        <p>未明确的资料可以稍后补充。</p>
        <label className={s.confirm}>
          <input
            type="checkbox"
            checked={draft.deidentified}
            disabled={disabled}
            onChange={(e) => update({ deidentified: e.target.checked })}
          />
          确认共享内容不含客户身份信息
        </label>
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
            取消创建
          </button>
          <Button
            type="submit"
            disabled={disabled || !draft.name.trim() || !draft.deidentified}
          >
            确认创建品类
          </Button>
        </footer>
      </form>
    </PaiCandidateShell>
  );
}
