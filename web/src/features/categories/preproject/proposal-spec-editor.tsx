"use client";

import { useEffect, useRef, useState } from "react";
import {
  Check,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  Trash,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import {
  newSpecPatches,
  editedSpecContent,
  specUsesBounds,
  type ProposalDrafts,
  type DictionaryParameter,
  type ProposalEditableItem,
  type ProposalPatch,
} from "@/lib/proposal-spec-editor";
import { numericValueText } from "@/lib/spec-bound-values";
import { ProposalSourceInspector } from "./proposal-source-inspector";
import styles from "./proposal-document.module.css";

function SpecRow({
  item: currentItem,
  editable,
  busy,
  mutate,
  drafts = {},
  onDraft,
}: ProposalDrafts & {
  item: ProposalEditableItem;
  editable: boolean;
  busy: boolean;
  mutate: (ops: ProposalPatch[]) => Promise<boolean>;
}) {
  const entry = drafts[currentItem.item_id],
    editing = !!entry;
  const item = entry?.item ?? currentItem,
    content = item.content;
  const first =
    entry?.values.first ??
    String(content.value ?? content.lower ?? content.text_value ?? "");
  const second = entry?.values.second ?? String(content.upper ?? "");
  const condition =
    entry?.values.condition ?? String(content.condition_note ?? "");
  const change = (key: string, value: string) =>
    onDraft?.(item.item_id, {
      item,
      values: { ...entry?.values, [key]: value },
    });
  const stop = () => onDraft?.(item.item_id, null);
  const stale = editing && item.version !== currentItem.version;
  const bounds = specUsesBounds(content);
  const target =
    content.availability === "unknown"
      ? "待完善"
      : content.availability === "not_applicable"
        ? "不适用"
        : content.value_type === "boolean"
          ? content.text_value === "true"
            ? "是"
            : "否"
          : content.text_value != null
            ? String(content.text_value)
            : numericValueText(
                content.value as string | number | null,
                content.lower as string | number | null,
                content.upper as string | number | null,
              );
  const save = async () => {
    if (
      await mutate([
        {
          op: "upsert",
          item_id: item.item_id,
          base_version: item.version,
          kind: "spec",
          content: editedSpecContent(content, first, second, condition),
          source_refs: item.source_refs,
        },
      ])
    )
      stop();
  };
  return (
    <tr>
      <th scope="row">
        {String(content.parameter ?? content.key)}
        <small className={styles.cellNote}>
          {stale && "版本已更新，草稿已保留；取消后重新编辑。"}字典{" "}
          {content.parameter_version
            ? `v${content.parameter_version}`
            : "未关联"}{" "}
          · 条目 v{item.version}
        </small>
      </th>
      <td>
        {editing ? (
          <div className={styles.specValue}>
            {content.value_type === "boolean" ? (
              <select
            disabled={busy || !editable}
                aria-label={`${content.parameter}目标值`}
                value={first}
                onChange={(event) => change("first", event.target.value)}
              >
                <option value="">待完善</option>
                <option value="true">是</option>
                <option value="false">否</option>
              </select>
            ) : (
              <input
            disabled={busy || !editable}
                aria-label={`${content.parameter}${bounds ? "下限" : "目标值"}`}
                value={first}
                onChange={(event) => change("first", event.target.value)}
                placeholder="未确定"
              />
            )}
            {bounds && (
              <>
                <span>–</span>
                <input
            disabled={busy || !editable}
                  aria-label={`${content.parameter}上限`}
                  value={second}
                  onChange={(event) => change("second", event.target.value)}
                  placeholder="未确定"
                />
              </>
            )}
          </div>
        ) : (
          target
        )}
        <span className={styles.cellNote}>{String(content.unit ?? "")}</span>
      </td>
      <td>
        {editing ? (
          <input
            disabled={busy || !editable}
            aria-label={`${content.parameter}工况`}
            value={condition}
            onChange={(event) => change("condition", event.target.value)}
            placeholder="工况未定"
          />
        ) : (
          String(content.condition_note ?? "工况未定")
        )}
      </td>
      <td>
        <span className={styles.itemStatus}>
          {(
            {
              confirmed: "人工确认",
              ai_draft: "AI 草稿",
              expert_pending: "待专家确认",
              unknown: "未知",
            } as Record<string, string>
          )[String(content.item_status)] ?? "未知"}
        </span>
      </td>
      <td>
        <ProposalSourceInspector
          sources={item.source_refs.filter(
            (source): source is Record<string, unknown> =>
              !!source && typeof source === "object" && !Array.isArray(source),
          )}
          label="来源"
        />
      </td>
      {editable && (
        <td>
          <div className={styles.rowTools}>
            {editing ? (
              <>
                <Button
                  size="icon"
                  variant="ghost"
                  disabled={busy || stale}
                  aria-label={`保存${content.parameter}`}
                  onClick={() => void save()}
                >
                  <Check size={14} />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  disabled={busy}
                  aria-label={`取消编辑${content.parameter}`}
                  onClick={stop}
                >
                  <X size={14} />
                </Button>
              </>
            ) : (
              <Button
                size="icon"
                variant="ghost"
                disabled={busy}
                aria-label={`编辑${content.parameter}`}
                onClick={() => onDraft?.(item.item_id, { item, values: {} })}
              >
                <PencilSimple size={14} />
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              disabled={busy}
              aria-label={`删除规格${content.parameter}`}
              onClick={() =>
                void mutate([
                  {
                    op: "remove",
                    item_id: item.item_id,
                    base_version: item.version,
                    kind: "spec",
                    content,
                    source_refs: item.source_refs,
                  },
                ])
              }
            >
              <Trash size={14} />
            </Button>
          </div>
        </td>
      )}
    </tr>
  );
}

export function ProposalSpecEditor({
  items,
  categoryId,
  editable,
  busy,
  mutate,
  drafts,
  onDraft,
}: ProposalDrafts & {
  items: ProposalEditableItem[];
  categoryId: string;
  editable: boolean;
  busy: boolean;
  mutate: (ops: ProposalPatch[]) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState("");
  const [dictionary, setDictionary] = useState<{
    categoryId: string;
    rows: DictionaryParameter[];
    error: string;
  } | null>(null);
  const [selected, setSelected] = useState<DictionaryParameter[]>([]);
  const [attempt, setAttempt] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    let active = true;
    void (async () => {
      try {
        const rows: DictionaryParameter[] = [],
          seen = new Set<string>();
        let cursor: string | null = null;
        do {
          const page: {
            items: DictionaryParameter[];
            next_cursor?: string | null;
          } = await browserApi(
            `v1/categories/${categoryId}/parameters?page_size=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
          );
          rows.push(...page.items);
          cursor = page.next_cursor ?? null;
          if (cursor && seen.has(cursor))
            throw new Error("参数分页未推进，请重新读取。");
          if (cursor) seen.add(cursor);
        } while (cursor && active);
        if (active) setDictionary({ categoryId, rows, error: "" });
      } catch (error) {
        if (active)
          setDictionary({
            categoryId,
            rows: [],
            error: (error as Error).message,
          });
      }
    })();
    return () => {
      active = false;
    };
  }, [open, categoryId, attempt]);
  const current = dictionary?.categoryId === categoryId ? dictionary : null;
  const existing = new Set(items.map((item) => item.content.parameter_id));
  const available = (current?.rows ?? []).filter(
    (row) => !existing.has(row.parameter_id),
  );
  const results = available.filter((row) =>
    `${row.name} ${row.key} ${row.unit ?? ""}`
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase()),
  );
  const selectedIds = new Set(selected.map((row) => row.parameter_id));
  const picked = selected.filter((row) => !existing.has(row.parameter_id));
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  return (
    <section className={styles.panel} aria-label="关键规格">
      <header className={styles.panelHeading}>
        <h2>关键规格</h2>
        <span>{items.length} 项</span>
        {editable && (
          <div className={styles.pickerAnchor}>
            <Button
              ref={trigger}
              size="xs"
              variant="ghost"
              aria-expanded={open}
              disabled={busy}
              onClick={() => {
                setOpen((value) => !value);
              }}
            >
              <Plus />
              新增规格
            </Button>
            {open && (
              <div
                className={styles.parameterPicker}
                role="dialog"
                aria-label="从品类字典新增规格"
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    close();
                  }
                }}
              >
                <label className={styles.pickerSearch}>
                  <MagnifyingGlass size={14} />
                  <input
                    autoFocus
                    type="search"
                    aria-label="搜索参数"
                    placeholder="搜索名称或参数键"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </label>
                <div className={styles.pickerTools}>
                  <button
                    type="button"
                    disabled={!results.length || busy}
                    onClick={() =>
                      setSelected((old) => [
                        ...old,
                        ...results.filter(
                          (row) => !selectedIds.has(row.parameter_id),
                        ),
                      ])
                    }
                  >
                    全选搜索结果
                  </button>
                  <button
                    type="button"
                    disabled={!selected.length || busy}
                    onClick={() => setSelected([])}
                  >
                    清空已选
                  </button>
                </div>
                <div className={styles.parameterResults}>
                  {!current ? (
                    <p role="status">正在读取规格字典…</p>
                  ) : current.error ? (
                    <div role="alert">
                      <p>{current.error}</p>
                      <button
                        type="button"
                        onClick={() => setAttempt((value) => value + 1)}
                      >
                        重新读取
                      </button>
                    </div>
                  ) : results.length ? (
                    results.map((row) => (
                      <label key={`${row.parameter_id}:${row.version}`}>
                        <input
                          type="checkbox"
                          disabled={busy}
                          checked={selectedIds.has(row.parameter_id)}
                          onChange={(event) =>
                            setSelected((old) =>
                              event.target.checked
                                ? [...old, row]
                                : old.filter(
                                    (value) =>
                                      value.parameter_id !== row.parameter_id,
                                  ),
                            )
                          }
                        />
                        <span>
                          {row.name}
                          <small>
                            {row.unit || "无单位"} · v{row.version}
                          </small>
                        </span>
                      </label>
                    ))
                  ) : (
                    <p>
                      {available.length
                        ? "没有匹配参数"
                        : "字典参数已全部加入，或尚无参数"}
                    </p>
                  )}
                </div>
                <footer>
                  <span>已选 {picked.length} 项</span>
                  <Button size="xs" variant="ghost" onClick={close}>
                    取消
                  </Button>
                  <Button
                    size="xs"
                    disabled={
                      busy || !picked.length || !current || !!current.error
                    }
                    onClick={async () => {
                      if (await mutate(newSpecPatches(picked, items))) {
                        setSelected([]);
                        setQuery("");
                        close();
                      }
                    }}
                  >
                    添加 {picked.length || ""} 项
                  </Button>
                </footer>
              </div>
            )}
          </div>
        )}
      </header>
      <div className={styles.tableScroll}>
        <table className={`${styles.specTable} ${styles.editableSpecs}`}>
          <thead>
            <tr>
              <th>参数</th>
              <th>目标值</th>
              <th>工况</th>
              <th>状态</th>
              <th>来源</th>
              {editable && (
                <th>
                  <span className="sr-only">操作</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <SpecRow
                key={`${item.item_id}:${item.version}`}
                item={item}
                drafts={drafts}
                onDraft={onDraft}
                editable={editable}
                busy={busy}
                mutate={mutate}
              />
            ))}
          </tbody>
        </table>
      </div>
      {!items.length && (
        <p className={styles.empty}>
          尚无关键规格。{editable && "可从当前品类的规格字典中添加。"}
        </p>
      )}
    </section>
  );
}
