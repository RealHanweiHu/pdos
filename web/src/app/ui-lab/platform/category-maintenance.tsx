"use client";

import { useState, type FormEvent } from "react";
import { MagnifyingGlass, Plus, Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Sheet } from "./product-preview-ui";
import {
  latestCatalogRecords,
  type CatalogKind,
  type CatalogRecord,
} from "./category-preview-state";
import type { ProductController } from "./product-preview-state";
import s from "./platform.module.css";
import p from "./product-preview.module.css";
import m from "./category-maintenance.module.css";

import {
  catalogFields as fields,
  catalogLabels as labels,
  type Field,
} from "./catalog-fields";

const originLabels = {
  human: "人工记录",
  imported: "导入资料",
  ai_draft: "AI 草稿",
};
export function CategoryMaintenance({
  controller: c,
  kind,
  disabled,
  empty,
  onPai,
}: {
  controller: ProductController;
  kind: CatalogKind;
  disabled: boolean;
  empty: boolean;
  onPai: (record?: CatalogRecord, values?: Record<string, string>) => void;
}) {
  const [query, setQuery] = useState("");
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const [editor, setEditor] = useState<{ record?: CatalogRecord } | null>(null);
  const [notice, setNotice] = useState("");
  const category = c.category!;
  const shown = empty
    ? []
    : latestCatalogRecords(c.catalogRecords).filter(
        (v) =>
          v.category === category.id &&
          v.kind === kind &&
          (showWithdrawn || v.state === "active") &&
          `${v.id} ${Object.values(v.values).join(" ")}`
            .toLowerCase()
            .includes(query.trim().toLowerCase()),
      );
  const headers =
    kind === "competitor"
      ? ["竞品", "品牌 / 场景", "数据类型", "报价", "来源"]
      : kind === "voice"
        ? ["主题", "用户与场景", "渠道", "样本量", "分类"]
        : ["参数", "单位", "参数版本", "测试条件", "完整性"];
  return (
    <>
      <div className={m.toolbar}>
        <div className={m.filters}>
          <span>{shown.length} 条</span>
          <label>
            <input
              type="checkbox"
              checked={showWithdrawn}
              onChange={(e) => setShowWithdrawn(e.target.checked)}
            />
            显示已撤回
          </label>
        </div>
        <div className={m.actions}>
          <button
            className={m.paiAction}
            aria-label={`让小Pai新增${labels[kind]}`}
            disabled={disabled || !c.allowed}
            onClick={() => onPai()}
          >
            <Sparkle size={14} /> 小Pai新增
          </button>
          <div className={p.search}>
            <MagnifyingGlass size={14} />
            <input
              aria-label={`搜索${labels[kind]}`}
              placeholder={`搜索${labels[kind]}`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setQuery("");
              }}
            />
          </div>
          <Button
            disabled={disabled || !c.allowed}
            onClick={() => {
              setNotice("");
              setEditor({});
            }}
          >
            <Plus size={14} />
            新增{labels[kind]}
          </Button>
        </div>
      </div>
      {notice && (
        <p className={m.notice} role="status">
          {notice}
        </p>
      )}
      {shown.length ? (
        <div className={`${s.tableWrap} ${p.table} ${m.table}`}>
          <table>
            <thead>
              <tr>
                {headers.map((h) => (
                  <th key={h} scope="col">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((record) => {
                const v = record.values;
                const rest =
                  kind === "competitor"
                    ? [
                        v.brand || v.scenario || "未填写",
                        v.evidence,
                        v.price
                          ? `${v.currency} ${v.price} · ${v.priceBasis}`
                          : "未知",
                        v.source,
                      ]
                    : kind === "voice"
                      ? [
                          v.scenario || "未填写",
                          v.channel,
                          v.sample ? `${v.sample} 份` : "未知",
                          v.classification,
                        ]
                      : [
                          v.unit,
                          `${record.id} v${record.version}`,
                          v.conditions || "未知",
                          [v.conditions, v.method, v.criterion].some(
                            (value) => !value || /未知|待/.test(value),
                          )
                            ? "待补齐"
                            : "已填写，待专业核对",
                        ];
                return (
                  <tr
                    key={record.id}
                    data-withdrawn={record.state === "withdrawn"}
                  >
                    <td>
                      <button
                        onClick={() => {
                          setNotice("");
                          setEditor({ record });
                        }}
                      >
                        {v.name}
                        {record.state === "withdrawn" && <small>已撤回</small>}
                      </button>
                    </td>
                    {rest.map((value, i) => (
                      <td key={i} title={value}>
                        {value}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={p.empty}>
          <h2>{query ? "没有匹配记录" : `还没有${labels[kind]}记录`}</h2>
          <p>
            {query
              ? "调整关键词，或清除搜索。"
              : `点击“新增${labels[kind]}”，开始维护当前品类。`}
          </p>
        </div>
      )}
      <p className={p.note}>
        {kind === "parameter"
          ? "修订生成新参数版本；已有提案继续引用原版本，不自动替换。"
          : kind === "voice"
            ? "共享区只记录公开或已去标识内容；保留样本量与出处，不把个别反馈当作普遍结论。"
            : "实测、宣传、推断与未知分别记录；报价保留币种、日期及税运口径。"}
      </p>
      {editor && (
        <CatalogEditor
          key={
            editor.record
              ? `${editor.record.id}:${editor.record.version}`
              : "new"
          }
          controller={c}
          kind={kind}
          record={editor.record}
          disabled={disabled}
          onPai={(record, values) => {
            setEditor(null);
            onPai(record, values);
          }}
          onClose={() => setEditor(null)}
          onSaved={(message) => {
            setEditor(null);
            setQuery("");
            setNotice(message);
          }}
        />
      )}
    </>
  );
}
function CatalogEditor({
  controller: c,
  kind,
  record,
  disabled,
  onClose,
  onSaved,
  onPai,
}: {
  controller: ProductController;
  kind: CatalogKind;
  record?: CatalogRecord;
  disabled: boolean;
  onClose: () => void;
  onSaved: (message: string) => void;
  onPai: (record?: CatalogRecord, values?: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    record
      ? { ...record.values }
      : Object.fromEntries(
          fields[kind].map((f) => [f.key, f.options?.[0] ?? ""]),
        ),
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [withdrawing, setWithdrawing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const withdrawn = record?.state === "withdrawn";
  const readOnly = disabled || !c.allowed || (withdrawn && !restoring);
  const history = record
    ? c.catalogRecords.filter((v) => v.id === record.id).toReversed()
    : [];
  function updateField(key: string, value: string) {
    setValues((current) => ({ ...current, [key]: value }));
    setError("");
  }
  const field = (f: Field) => (
    <label key={f.key}>
      {f.label}
      {f.required && <span className={m.required}> *</span>}
      {f.options ? (
        <select
          aria-label={f.label}
          value={values[f.key] ?? ""}
          onChange={(e) => updateField(f.key, e.target.value)}
        >
          {f.options.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      ) : f.type === "textarea" ? (
        <textarea
          aria-label={f.label}
          required={f.required}
          value={values[f.key] ?? ""}
          placeholder={f.placeholder}
          onChange={(e) => updateField(f.key, e.target.value)}
        />
      ) : (
        <input
          aria-label={f.label}
          readOnly={kind === "parameter" && f.key === "key" && !!record}
          type={f.type ?? "text"}
          required={f.required}
          min={f.min}
          step={f.step}
          value={values[f.key] ?? ""}
          placeholder={f.placeholder}
          onInput={
            f.type === "date"
              ? (e) => updateField(f.key, e.currentTarget.value)
              : undefined
          }
          onChange={(e) => updateField(f.key, e.target.value)}
        />
      )}
    </label>
  );
  function save(event: FormEvent) {
    event.preventDefault();
    if (readOnly) return;
    if (record && !reason.trim()) {
      setError("请填写本次修订原因。");
      return;
    }
    const prepared =
      kind === "parameter"
        ? {
            ...values,
            conditions: values.conditions || "未知，待确认",
            method: values.method || "未知，待确认",
            criterion: values.criterion || "未知，待确认",
          }
        : values;
    const result = c.saveCatalog(
      kind,
      c.category!.id,
      prepared,
      record,
      reason,
      restoring,
    );
    if (result.error) setError(result.error);
    else
      onSaved(
        `${values.name} 已${restoring ? "恢复并" : ""}保存${record ? `为 v${record.version + 1}` : ""}（预览）。`,
      );
  }
  return (
    <Sheet
      title={record ? `维护${labels[kind]}` : `新增${labels[kind]}`}
      onClose={onClose}
    >
      <h1>{record?.values.name || `新增${labels[kind]}`}</h1>
      <p>
        {c.category!.name}
        {record &&
          ` · ${record.id} v${record.version} · ${originLabels[record.origin]}`}
      </p>
      <button
        className={p.paiCreate}
        disabled={disabled || !c.allowed}
        onClick={() => onPai(record, values)}
      >
        <Sparkle size={15} />
        与小Pai一起{record ? "维护" : "新增"}
        <small>带入当前品类与{record ? "记录版本" : "已填内容"}</small>
      </button>
      {withdrawn && (
        <p className={m.notice}>
          这条记录已撤回，当前不参与列表和矩阵汇总。历史引用仍保留。
        </p>
      )}
      <form onSubmit={save} className={`${p.form} ${m.form}`}>
        <fieldset disabled={readOnly}>
          <div className={m.fields}>
            {fields[kind].filter((f) => !f.extra).map(field)}
          </div>
          {fields[kind].some((f) => f.extra) && (
            <details className={m.more}>
              <summary>
                {kind === "competitor" ? "报价与补充信息" : "补充说明"}
              </summary>
              <div className={m.fields}>
                {fields[kind].filter((f) => f.extra).map(field)}
              </div>
            </details>
          )}
          {record && (
            <label className={m.reason}>
              修订原因
              <textarea
                aria-label="修订原因"
                value={reason}
                required
                onChange={(e) => setReason(e.target.value)}
                placeholder={
                  restoring
                    ? "说明为何恢复及本次核对结果"
                    : "说明本次修改，原版本会保留"
                }
              />
            </label>
          )}
        </fieldset>
        {error && (
          <p className={m.error} role="alert">
            {error}
          </p>
        )}
        {!!history.length && (
          <details className={m.history}>
            <summary>版本记录 · {history.length}</summary>
            {history.map((version) => (
              <details key={version.version}>
                <summary>
                  v{version.version} · {version.author} ·{" "}
                  {version.state === "withdrawn"
                    ? "已撤回"
                    : originLabels[version.origin]}
                </summary>
                <p>{version.reason}</p>
                <dl>
                  {fields[kind].map((f) => (
                    <div key={f.key}>
                      <dt>{f.label}</dt>
                      <dd>{version.values[f.key] || "未填写 / 未知"}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ))}
          </details>
        )}
        {withdrawing && (
          <section className={m.withdraw}>
            <h2>撤回记录</h2>
            <p>不再用于当前汇总，保留原版本与已有引用。</p>
            <label>
              撤回原因
              <textarea
                aria-label="撤回原因"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <div className={m.actions}>
              <Button
                type="button"
                variant="outline"
                onClick={() => setWithdrawing(false)}
              >
                取消撤回
              </Button>
              <Button
                type="button"
                disabled={disabled || !reason.trim()}
                onClick={() => {
                  if (!record) return;
                  const result = c.withdrawCatalog(record, reason);
                  if (result.error) setError(result.error);
                  else
                    onSaved(
                      `${record.values.name} 已撤回（预览），历史记录保留。`,
                    );
                }}
              >
                确认撤回
              </Button>
            </div>
          </section>
        )}
        <footer className={m.footer}>
          {record && !withdrawing && !withdrawn && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                setReason("");
                setWithdrawing(true);
              }}
            >
              撤回记录
            </button>
          )}
          {withdrawn && !restoring ? (
            <Button
              type="button"
              disabled={disabled}
              onClick={() => {
                setRestoring(true);
                setReason("");
              }}
            >
              恢复并修订
            </Button>
          ) : (
            <Button
              type="submit"
              disabled={
                readOnly ||
                withdrawing ||
                !values.name?.trim() ||
                (!!record && !reason.trim())
              }
            >
              {restoring
                ? "保存并恢复"
                : record
                  ? kind === "parameter"
                    ? "保存新版本"
                    : "保存修订"
                  : `保存${labels[kind]}`}
            </Button>
          )}
        </footer>
      </form>
    </Sheet>
  );
}
