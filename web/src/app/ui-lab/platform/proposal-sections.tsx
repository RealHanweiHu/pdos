"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { Plus, X } from "@phosphor-icons/react";
import type { ProposalValues } from "./proposal-pai-draft";
import { ProposalParameterPicker } from "./proposal-parameter-picker";
import type { CatalogRecord } from "./category-preview-state";
import s from "./category-pai.module.css";
import t from "./proposal-sections.module.css";

/** The same structure stays in place when a proposal changes from editing to saved. */
export function ProposalSections({
  values: v,
  onChange,
  disabled = false,
  parameters = [],
  onAddParameters,
}: {
  values: Pick<ProposalValues, "options" | "choice" | "specs" | "questions">;
  onChange?: (value: Partial<ProposalValues>) => void;
  disabled?: boolean;
  parameters?: CatalogRecord[];
  onAddParameters?: (records: CatalogRecord[]) => boolean;
}) {
  const [pickingSpec, setPickingSpec] = useState(false);
  const pickerId = useId();
  const specInputs = useRef<(HTMLInputElement | null)[]>([]);
  const addSpecButton = useRef<HTMLButtonElement>(null);
  const pendingSpecFocus = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingSpecFocus.current === null) return;
    if (pendingSpecFocus.current < 0) addSpecButton.current?.focus();
    else specInputs.current[pendingSpecFocus.current]?.focus();
    pendingSpecFocus.current = null;
  }, [v.specs.length]);
  function closeSpecPicker() {
    setPickingSpec(false);
    addSpecButton.current?.focus();
  }
  const questionInputs = useRef<(HTMLInputElement | null)[]>([]);
  const addButton = useRef<HTMLButtonElement>(null);
  const pendingFocus = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingFocus.current === null) return;
    if (pendingFocus.current < 0) addButton.current?.focus();
    else questionInputs.current[pendingFocus.current]?.focus();
    pendingFocus.current = null;
  }, [v.questions.length]);

  function questionField(i: number, key: "title" | "owner" | "due") {
    const value = v.questions[i][key];
    const placeholder =
      key === "title" ? "填写问题" : key === "owner" ? "待认领" : "待定";
    if (!onChange)
      return (
        <span className={!value ? t.empty : undefined}>
          {value || placeholder}
        </span>
      );
    return (
      <input
        ref={
          key === "title"
            ? (el) => {
                questionInputs.current[i] = el;
              }
            : undefined
        }
        aria-label={`候选${key === "title" ? "待决问题" : key === "owner" ? "问题负责人" : "问题期限"} ${i + 1}`}
        value={value}
        title={value || placeholder}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) =>
          onChange({
            questions: v.questions.map((item, j) =>
              i === j ? { ...item, [key]: e.target.value } : item,
            ),
          })
        }
      />
    );
  }

  return (
    <div className={t.sections}>
      <details className={s.moreFields}>
        <summary>方案与取舍 · 2 个方向</summary>
        <div className={t.comparison}>
          <table aria-label="方案对比" className={t.table}>
            <thead>
              <tr>
                <th scope="col">方案 A</th>
                <th scope="col">方案 B</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                {v.options.map((option, i) => (
                  <td key={i}>
                    {onChange ? (
                      <textarea
                        aria-label={`候选方案 ${i === 0 ? "A" : "B"}`}
                        rows={3}
                        value={option}
                        disabled={disabled}
                        placeholder="补充方案方向"
                        onChange={(e) => {
                          const options: [string, string] = [...v.options];
                          options[i] = e.target.value;
                          onChange({ options });
                        }}
                      />
                    ) : (
                      <span>{option || "待补充"}</span>
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
          <div className={t.choice}>
            <span>当前取舍</span>
            {onChange ? (
              <textarea
                aria-label="候选当前取舍与理由"
                rows={2}
                value={v.choice}
                disabled={disabled}
                placeholder="倾向的方案及理由"
                onChange={(e) => onChange({ choice: e.target.value })}
              />
            ) : (
              <span>{v.choice || "待补充"}</span>
            )}
          </div>
        </div>
      </details>
      <details className={s.moreFields}>
        <summary>关键规格 · {v.specs.length} 项</summary>
        <div
          className={t.tableScroll}
          role="region"
          aria-label="关键规格表格"
          tabIndex={0}
        >
          <table aria-label="关键规格" className={`${t.table} ${t.specs}`}>
            <colgroup>
              <col className={t.specName} />
              <col />
              <col className={t.reference} />
              {onChange && <col className={t.action} />}
            </colgroup>
            <thead>
              <tr>
                <th scope="col">参数</th>
                <th scope="col">当前定义</th>
                <th scope="col">依据 / 状态</th>
                {onChange && (
                  <th scope="col">
                    <span className={t.srOnly}>操作</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {v.specs.map((row, i) => (
                <tr key={i}>
                  <th scope="row">{row[0]}</th>
                  <td>
                    {onChange ? (
                      <input
                        ref={(el) => {
                          specInputs.current[i] = el;
                        }}
                        aria-label={`候选规格 ${i + 1}`}
                        value={row[1]}
                        title={row[1]}
                        placeholder="待补充"
                        disabled={disabled}
                        onChange={(e) =>
                          onChange({
                            specs: v.specs.map((r, j) =>
                              j === i
                                ? [
                                    r[0],
                                    e.target.value,
                                    r[2],
                                    r[3]?.startsWith("手动添加")
                                      ? "手动添加 / 待确认"
                                      : "AI起草 / 待确认",
                                  ]
                                : r,
                            ),
                          })
                        }
                      />
                    ) : (
                      <span>{row[1] || "待补充"}</span>
                    )}
                  </td>
                  <td className={t.meta}>
                    <span>{row[2] || "依据待补充"}</span>
                    <small>{row[3] || "待确认"}</small>
                  </td>
                  {onChange && (
                    <td className={t.rowAction}>
                      <button
                        type="button"
                        disabled={disabled}
                        aria-label={`移除候选规格 ${i + 1}`}
                        title={`移除${row[0]}`}
                        onClick={() => {
                          pendingSpecFocus.current = Math.min(
                            i,
                            v.specs.length - 2,
                          );
                          onChange({
                            specs: v.specs.filter((_, j) => i !== j),
                          });
                        }}
                      >
                        <X size={13} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {!v.specs.length && (
                <tr>
                  <td colSpan={onChange ? 4 : 3} className={t.empty}>
                    {onChange
                      ? "暂无关键规格，可从当前品类的规格字典添加。"
                      : "暂无关键规格"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {onAddParameters && (
          <>
            <button
              ref={addSpecButton}
              className={t.addRow}
              type="button"
              disabled={disabled}
              aria-expanded={pickingSpec}
              aria-controls={pickerId}
              onClick={() => setPickingSpec(!pickingSpec)}
            >
              <Plus size={13} />
              添加规格
            </button>
            {pickingSpec && (
              <ProposalParameterPicker
                id={pickerId}
                parameters={parameters}
                specs={v.specs}
                disabled={disabled}
                onClose={closeSpecPicker}
                onAdd={(records) => {
                  pendingSpecFocus.current = v.specs.length;
                  if (onAddParameters(records)) {
                    setPickingSpec(false);
                    return true;
                  }
                  pendingSpecFocus.current = null;
                  return false;
                }}
              />
            )}
          </>
        )}
      </details>
      <details className={s.moreFields}>
        <summary>待决问题 · {v.questions.length} 项</summary>
        <div
          className={t.tableScroll}
          role="region"
          aria-label="待决问题表格"
          tabIndex={0}
        >
          <table aria-label="待决问题" className={`${t.table} ${t.questions}`}>
            <colgroup>
              <col />
              <col className={t.owner} />
              <col className={t.due} />
              {onChange && <col className={t.action} />}
            </colgroup>
            <thead>
              <tr>
                <th scope="col">问题</th>
                <th scope="col">负责人</th>
                <th scope="col">期限</th>
                {onChange && (
                  <th scope="col">
                    <span className={t.srOnly}>操作</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {v.questions.map((q, i) => (
                <tr key={i}>
                  <td>{questionField(i, "title")}</td>
                  <td>{questionField(i, "owner")}</td>
                  <td>{questionField(i, "due")}</td>
                  {onChange && (
                    <td className={t.rowAction}>
                      <button
                        type="button"
                        disabled={disabled}
                        aria-label={`移除候选问题 ${i + 1}`}
                        title="移除问题"
                        onClick={() => {
                          pendingFocus.current = Math.min(
                            i,
                            v.questions.length - 2,
                          );
                          onChange({
                            questions: v.questions.filter((_, j) => i !== j),
                          });
                        }}
                      >
                        <X size={13} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {!v.questions.length && (
                <tr>
                  <td colSpan={onChange ? 4 : 3} className={t.empty}>
                    暂无待决问题
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {onChange && (
          <button
            className={t.addRow}
            ref={addButton}
            type="button"
            disabled={disabled}
            onClick={() => {
              pendingFocus.current = v.questions.length;
              onChange({
                questions: [...v.questions, { title: "", owner: "", due: "" }],
              });
            }}
          >
            <Plus size={13} />
            添加问题
          </button>
        )}
      </details>
    </div>
  );
}
