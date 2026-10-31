"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { MagnifyingGlass, X } from "@phosphor-icons/react";
import type { CatalogRecord } from "./category-preview-state";
import {
  proposalHasParameter,
  type ProposalValues,
} from "./proposal-pai-draft";
import t from "./proposal-sections.module.css";

export function ProposalParameterPicker({
  id,
  parameters,
  specs,
  disabled,
  onAdd,
  onClose,
}: {
  id: string;
  parameters: CatalogRecord[];
  specs: ProposalValues["specs"];
  disabled: boolean;
  onAdd: (records: CatalogRecord[]) => boolean;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (search.current?.disabled) close.current?.focus({ preventScroll: true });
    else search.current?.focus({ preventScroll: true });
    // Keep the batch action above the sticky save bar without moving the app shell.
    const node = panel.current;
    if (!node) return;
    for (
      let parent = node.parentElement;
      parent && parent !== document.body;
      parent = parent.parentElement
    ) {
      if (!/auto|scroll/.test(getComputedStyle(parent).overflowY)) continue;
      const bounds = node.getBoundingClientRect();
      const frame = parent.getBoundingClientRect();
      parent.scrollTop += Math.min(
        Math.max(0, bounds.bottom - frame.bottom + 76),
        Math.max(0, bounds.top - frame.top - 12),
      );
      break;
    }
  }, []);

  // Versioned selection drops stale/withdrawn entries instead of silently changing a reference.
  const key = (r: CatalogRecord) => `${r.id}:${r.version}`;
  const chosen = parameters.filter(
    (r) => selected.includes(key(r)) && !proposalHasParameter(specs, r),
  );
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = parameters
    .filter((r) => {
      const text = [r.values.name, r.values.key, r.values.unit, r.id]
        .join(" ")
        .toLocaleLowerCase();
      return terms.every((term) => text.includes(term));
    })
    .sort(
      (a, b) =>
        Number(proposalHasParameter(specs, a)) -
        Number(proposalHasParameter(specs, b)),
    );
  const allAdded =
    parameters.length > 0 &&
    parameters.every((r) => proposalHasParameter(specs, r));
  const unselectedMatches = matches.filter(
    (r) => !proposalHasParameter(specs, r) && !selected.includes(key(r)),
  );

  return (
    <div
      ref={panel}
      id={id}
      className={t.specPicker}
      role="group"
      aria-label="从当前品类规格字典添加参数"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className={t.pickerSearch}>
        <MagnifyingGlass size={14} aria-hidden="true" />
        <input
          ref={search}
          aria-label="搜索规格参数"
          placeholder="搜索参数名称、编号或单位…"
          autoComplete="off"
          disabled={disabled}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.preventDefault();
          }}
        />
        <button
          ref={close}
          type="button"
          onClick={onClose}
          aria-label="取消添加规格"
          title="取消添加规格"
        >
          <X size={14} />
        </button>
      </div>
      <div className={t.parameterList} aria-label="参数搜索结果" role="group">
        {matches.map((r) => {
          const added = proposalHasParameter(specs, r);
          const checked = chosen.some((item) => item.id === r.id);
          return (
            <label
              key={key(r)}
              className={t.parameterRow}
              data-added={added}
              data-selected={checked}
            >
              <input
                type="checkbox"
                aria-label={`选择参数 ${r.values.name}`}
                disabled={disabled || added}
                checked={added || checked}
                onChange={(e) => {
                  setSelected(
                    e.target.checked
                      ? [...selected, key(r)]
                      : selected.filter((k) => k !== key(r)),
                  );
                  setError("");
                }}
              />
              <span
                className={t.parameterName}
                title={`${r.values.name} · ${r.values.key || r.id}`}
              >
                {r.values.name}
              </span>
              <span
                className={t.parameterMeta}
                title={`${r.values.unit || "单位未知"} · ${r.id} v${r.version}`}
              >
                {r.values.unit || "单位未知"} · {r.id} v{r.version}
              </span>
              {added && <span className={t.addedLabel}>已添加</span>}
            </label>
          );
        })}
        {!matches.length && (
          <div className={t.pickerEmpty} role="status">
            {!parameters.length ? (
              "当前品类暂无可用参数，可先在规格字典中维护。"
            ) : (
              <>
                没有匹配的参数
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    search.current?.focus();
                  }}
                >
                  清除搜索
                </button>
              </>
            )}
          </div>
        )}
      </div>
      <div className={t.pickerActions}>
        <div className={t.pickerBulkActions}>
          <span role="status">
            {allAdded ? "字典参数已全部添加" : `已选 ${chosen.length} 项`}
          </span>
          <button
            type="button"
            disabled={disabled || !unselectedMatches.length}
            title="勾选当前搜索结果中可添加的参数，保留其他已选项"
            onClick={() => {
              if (disabled) return;
              setSelected((previous) => [
                ...new Set([...previous, ...unselectedMatches.map(key)]),
              ]);
              setError("");
            }}
          >
            全选搜索结果
          </button>
          <button
            type="button"
            disabled={disabled || !chosen.length}
            title="清空所有已选项，包括当前搜索结果之外的选择"
            onClick={() => {
              if (disabled) return;
              setSelected([]);
              setError("");
            }}
          >
            清空已选
          </button>
        </div>
        <button
          type="button"
          disabled={disabled || !chosen.length}
          onClick={() => {
            if (disabled || !chosen.length) return;
            if (!onAdd(chosen)) setError("参数已变化，请重新选择后添加。");
          }}
        >
          添加{chosen.length ? ` ${chosen.length} 项` : "所选"}
        </button>
      </div>
      {error && (
        <p className={t.pickerError} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
