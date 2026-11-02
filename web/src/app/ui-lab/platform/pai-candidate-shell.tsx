"use client";

import type { ReactNode } from "react";
import { ArrowUpRight, FileText } from "@phosphor-icons/react";
import s from "./category-pai.module.css";

export type CandidatePresentation = {
  editing?: boolean;
  active?: boolean;
  onEdit?: () => void;
};

export function PaiCandidateShell({
  title,
  meta,
  summary,
  children,
  editing,
  active,
  onEdit,
}: CandidatePresentation & {
  title: string;
  meta: string;
  summary: [string, string][];
  children: ReactNode;
}) {
  if (editing) return <div className={s.editorForm}>{children}</div>;
  return (
    <section className={s.preview} aria-label={`${title}草稿摘要`}>
      <header>
        <FileText size={18} />
        <div>
          <strong>{title}</strong>
          <span>{meta}</span>
        </div>
      </header>
      {!active && (
        <dl className={s.previewRows}>
          {summary.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value || "待补充"}</dd>
            </div>
          ))}
        </dl>
      )}
      <button type="button" className={s.expand} onClick={onEdit}>
        {active ? "返回编辑" : "查看与编辑"} <ArrowUpRight size={13} />
      </button>
    </section>
  );
}
