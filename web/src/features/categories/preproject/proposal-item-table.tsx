"use client";

/* Operate (10-25 platform design): options sit side by side as A/B columns and
   questions as one compact row each. Cells edit in place; ordinary edits collect
   as drafts for one "保存修订", while a new question or a change of question,
   owner or due date still goes through its own one-time confirmation. */
import { useLayoutEffect, useRef, useState } from "react";
import { Check, Plus, Trash, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type {
  ProposalEditableItem,
  ProposalPatch,
  ProposalDrafts,
  ProposalRowDraft,
} from "@/lib/proposal-spec-editor";
import styles from "./proposal-document.module.css";

export type NewQuestion = { key: string; question: string; owner_id: string; due_date: string };
type Props = ProposalDrafts & {
  items: ProposalEditableItem[];
  people: { id: string; name: string }[];
  editable: boolean;
  busy: boolean;
  mutate: (ops: ProposalPatch[]) => Promise<boolean>;
  kind: "option" | "question";
  onAssignQuestion?: (item: ProposalEditableItem, content: Record<string, unknown>) => void;
  /** Unsaved new question rows; each one is created through its own confirmation. */
  newQuestions?: NewQuestion[];
  onNewQuestions?: (rows: NewQuestion[]) => void;
  onCreateQuestion?: (row: NewQuestion) => void;
};

const optionKinds: Record<string, string> = { new: "新方案", status_quo: "保持现状", do_nothing: "不开展" };
const questionStates: Record<string, string> = { open: "待答复", answered: "已答复", carried: "已转入项目" };
const letter = (index: number) => index < 26 ? String.fromCharCode(65 + index) : String(index + 1);
const summaryField = (content: Record<string, unknown>) =>
  "summary" in content ? "summary" : "text" in content ? "text" : "description" in content ? "description" : "summary";
const questionAssignment = ["question", "owner_id", "due_date"] as const;

/** Keep only values that differ from the saved item; an unchanged row is not a draft. */
export function draftChange(currentItem: ProposalEditableItem, entry: ProposalRowDraft | undefined, key: string, value: string): ProposalRowDraft | null {
  const item = entry?.item ?? currentItem;
  const values = { ...entry?.values, [key]: value };
  for (const [name, next] of Object.entries(values)) if (String(item.content[name] ?? "") === next) delete values[name];
  return Object.keys(values).length ? { item, values } : null;
}

function OptionComparison({ items, editable, busy, mutate, drafts = {}, onDraft }: Props) {
  const [adding, setAdding] = useState<{ name: string; kind: string; summary: string } | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const newName = useRef<HTMLInputElement>(null);
  const focusAfter = useRef<"new" | "add" | null>(null);
  useLayoutEffect(() => {
    if (focusAfter.current === "new") newName.current?.focus();
    else if (focusAfter.current === "add") addButton.current?.focus();
    focusAfter.current = null;
  }, [adding, items.length]);
  const columns = items.map(currentItem => {
    const entry = drafts[currentItem.item_id];
    const item = entry?.item ?? currentItem;
    const content: Record<string, unknown> = { ...item.content, ...entry?.values };
    return { currentItem, entry, item, content, stale: !!entry && item.version !== currentItem.version };
  });
  const change = (currentItem: ProposalEditableItem, key: string, value: string) =>
    onDraft?.(currentItem.item_id, draftChange(currentItem, drafts[currentItem.item_id], key, value));
  const locked = busy || !editable;
  const count = items.length + (adding ? 1 : 0);
  return (
    <section className={styles.panel} aria-label="方案对比">
      <header className={styles.panelHeading}>
        <h2>方案对比</h2>
        <span>{items.length} 个方向</span>
        {editable && !adding && (
          <Button ref={addButton} size="xs" variant="ghost" disabled={busy} onClick={() => { focusAfter.current = "new"; setAdding({ name: "", kind: "new", summary: "" }); }}>
            <Plus />添加方案
          </Button>
        )}
      </header>
      {count > 0 && (
        <div className={styles.tableScroll} role="region" aria-label="方案对比表格" tabIndex={0}>
          <table className={`${styles.comparisonTable} ${editable ? styles.cellEdit : ""}`} style={{ minWidth: 72 + count * 200 }}>
            <thead>
              <tr>
                <th scope="col" className={styles.rowLabel}><span className="sr-only">对比项</span></th>
                {columns.map(({ currentItem, item }, index) => (
                  <th scope="col" key={currentItem.item_id}>
                    <span className={styles.columnHead}>
                      方案 {letter(index)}
                      {editable && (
                        <button
                          type="button"
                          className={styles.cellAction}
                          disabled={busy}
                          aria-label={`删除方案 ${letter(index)}`}
                          title={`删除方案 ${letter(index)}`}
                          onClick={async () => {
                            if (await mutate([{ op: "remove", item_id: currentItem.item_id, base_version: currentItem.version, kind: "option", content: currentItem.content, source_refs: currentItem.source_refs }])) {
                              onDraft?.(currentItem.item_id, null);
                              focusAfter.current = "add";
                            }
                          }}
                        >
                          <Trash size={13} />
                        </button>
                      )}
                    </span>
                    <small className={styles.cellNote}>v{item.version} · {item.origin === "ai_draft" ? "AI 起草" : "人工记录"}</small>
                  </th>
                ))}
                {adding && <th scope="col"><span className={styles.columnHead}>方案 {letter(items.length)} · 新增</span><small className={styles.cellNote}>尚未保存</small></th>}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row" className={styles.rowLabel}>名称</th>
                {columns.map(({ currentItem, content }, index) => (
                  <td key={currentItem.item_id}>
                    {editable ? <input aria-label={`方案 ${letter(index)} 名称`} disabled={locked} value={String(content.name ?? "")} placeholder="方案名称" onChange={event => change(currentItem, "name", event.target.value)} /> : <strong>{String(content.name ?? "")}</strong>}
                  </td>
                ))}
                {adding && <td><input ref={newName} aria-label="新方案名称" disabled={busy} value={adding.name} placeholder="方案名称" onChange={event => setAdding({ ...adding, name: event.target.value })} /></td>}
              </tr>
              <tr>
                <th scope="row" className={styles.rowLabel}>类型</th>
                {columns.map(({ currentItem, content }, index) => (
                  <td key={currentItem.item_id}>
                    {editable ? (
                      <select aria-label={`方案 ${letter(index)} 类型`} disabled={locked} value={String(content.kind ?? "")} onChange={event => change(currentItem, "kind", event.target.value)}>
                        {Object.entries(optionKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    ) : optionKinds[String(content.kind)] ?? "未确定"}
                  </td>
                ))}
                {adding && <td><select aria-label="新方案类型" disabled={busy} value={adding.kind} onChange={event => setAdding({ ...adding, kind: event.target.value })}>{Object.entries(optionKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td>}
              </tr>
              <tr>
                <th scope="row" className={styles.rowLabel}>说明</th>
                {columns.map(({ currentItem, content }, index) => {
                  const field = summaryField(currentItem.content);
                  return (
                    <td key={currentItem.item_id}>
                      {editable ? <textarea aria-label={`方案 ${letter(index)} 说明`} disabled={locked} rows={3} value={String(content[field] ?? "")} placeholder="补充方案方向" onChange={event => change(currentItem, field, event.target.value)} /> : <span className={styles.cellText}>{String(content[field] ?? "") || "未填写说明"}</span>}
                    </td>
                  );
                })}
                {adding && <td><textarea aria-label="新方案说明" disabled={busy} rows={3} value={adding.summary} placeholder="补充方案方向" onChange={event => setAdding({ ...adding, summary: event.target.value })} /></td>}
              </tr>
              {(adding || columns.some(column => column.entry)) && (
                <tr>
                  <th scope="row" className={styles.rowLabel}><span className="sr-only">本列操作</span></th>
                  {columns.map(({ currentItem, entry, stale }, index) => (
                    <td key={currentItem.item_id}>
                      {entry && (
                        <div className={styles.cellFooter}>
                          <span>{stale ? "版本已更新，草稿已保留；撤销后重新编辑。" : "未保存"}</span>
                          <Button size="xs" variant="ghost" disabled={busy} aria-label={`撤销方案 ${letter(index)} 的编辑`} onClick={() => onDraft?.(currentItem.item_id, null)}><X />撤销</Button>
                        </div>
                      )}
                    </td>
                  ))}
                  {adding && (
                    <td>
                      <div className={styles.cellFooter}>
                        <Button
                          size="xs"
                          disabled={busy || !adding.name.trim()}
                          onClick={async () => {
                            const summary = adding.summary.trim();
                            if (await mutate([{ op: "upsert", kind: "option", content: { name: adding.name.trim(), kind: adding.kind, ...(summary ? { summary } : {}) }, source_refs: [] }])) {
                              focusAfter.current = "add";
                              setAdding(null);
                            }
                          }}
                        >
                          <Check />保存方案
                        </Button>
                        <Button size="xs" variant="ghost" disabled={busy} onClick={() => { focusAfter.current = "add"; setAdding(null); }}>取消</Button>
                      </div>
                    </td>
                  )}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {!count && <p className={styles.empty}>暂无方案{editable ? "，可直接添加，或与旁边的小Pai继续完善。" : "。"}</p>}
    </section>
  );
}

function QuestionRow({ item: currentItem, index, people, editable, busy, mutate, drafts = {}, onDraft, onAssignQuestion, onRemoved }: Omit<Props, "items" | "kind"> & { item: ProposalEditableItem; index: number; onRemoved: () => void }) {
  const entry = drafts[currentItem.item_id];
  const item = entry?.item ?? currentItem;
  const content: Record<string, unknown> = { ...item.content, ...entry?.values };
  const stale = !!entry && item.version !== currentItem.version;
  const carried = currentItem.content.status === "carried";
  const reassigning = questionAssignment.some(key => String(content[key] ?? "") !== String(item.content[key] ?? ""));
  const change = (key: string, value: string) => onDraft?.(currentItem.item_id, draftChange(currentItem, entry, key, value));
  const locked = busy || !editable || carried;
  const label = String(currentItem.content.question ?? `问题 ${index + 1}`);
  const owner = people.find(person => person.id === content.owner_id)?.name ?? "未取得姓名";
  if (!editable)
    return (
      <tr>
        <td><span className={styles.cellText}>{String(content.question ?? "")}</span><small className={styles.cellNote}>v{item.version} · {item.origin === "ai_draft" ? "AI 起草" : "人工记录"}</small></td>
        <td>{owner}</td>
        <td>{String(content.due_date ?? "未确定")}</td>
        <td>{questionStates[String(content.status)] ?? "待答复"}{typeof content.answer === "string" && content.answer && <small className={styles.cellNote}>{content.answer}</small>}</td>
      </tr>
    );
  return (
    <tr data-draft={entry ? "true" : undefined}>
      <td>
        <input aria-label={`问题内容 ${index + 1}`} disabled={locked} value={String(content.question ?? "")} placeholder="填写问题" title={String(content.question ?? "")} onChange={event => change("question", event.target.value)} />
        <small className={styles.cellNote}>{stale ? "版本已更新，草稿已保留；撤销后重新编辑。" : reassigning ? "问题、负责人或期限有变化，需核对一次责任安排。" : `v${item.version} · ${item.origin === "ai_draft" ? "AI 起草" : "人工记录"}`}</small>
      </td>
      <td>
        <select aria-label={`问题负责人 ${index + 1}`} disabled={locked} value={String(content.owner_id ?? "")} onChange={event => change("owner_id", event.target.value)}>
          {!people.some(person => person.id === content.owner_id) && <option value={String(content.owner_id ?? "")}>未取得姓名</option>}
          {people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}
        </select>
      </td>
      <td><input type="date" aria-label={`问题期限 ${index + 1}`} required disabled={locked} value={String(content.due_date ?? "")} onChange={event => change("due_date", event.target.value)} /></td>
      <td>
        {carried ? questionStates.carried : (
          <>
            <select aria-label={`问题状态 ${index + 1}`} disabled={locked} value={String(content.status ?? "open")} onChange={event => change("status", event.target.value)}>
              <option value="open">待答复</option>
              <option value="answered">已答复</option>
            </select>
            {content.status === "answered" && <input aria-label={`问题答复 ${index + 1}`} disabled={locked} value={String(content.answer ?? "")} placeholder="填写答复" onChange={event => change("answer", event.target.value)} />}
          </>
        )}
      </td>
      <td>
        <div className={styles.rowTools}>
          {reassigning && (
            <Button size="icon" variant="ghost" disabled={busy || stale || !String(content.question ?? "").trim() || !String(content.due_date ?? "")} aria-label={`核对改派：${label}`} title="核对新的责任安排" onClick={() => onAssignQuestion?.(item, content)}>
              <Check size={14} />
            </Button>
          )}
          {entry && <Button size="icon" variant="ghost" disabled={busy} aria-label={`撤销此行编辑：${label}`} title="撤销此行编辑" onClick={() => onDraft?.(currentItem.item_id, null)}><X size={14} /></Button>}
          {!carried && (
            <Button
              size="icon"
              variant="ghost"
              disabled={busy}
              aria-label={`删除问题：${label}`}
              title="删除问题"
              onClick={async () => {
                if (await mutate([{ op: "remove", item_id: currentItem.item_id, base_version: currentItem.version, kind: "question", content: currentItem.content, source_refs: currentItem.source_refs }])) {
                  onDraft?.(currentItem.item_id, null);
                  onRemoved();
                }
              }}
            >
              <Trash size={14} />
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

function QuestionTable(props: Props) {
  const { items, people, editable, busy, newQuestions = [], onNewQuestions, onCreateQuestion } = props;
  const addButton = useRef<HTMLButtonElement>(null);
  const table = useRef<HTMLTableSectionElement>(null);
  const focusAfter = useRef<number | "add" | null>(null);
  useLayoutEffect(() => {
    const target = focusAfter.current;
    focusAfter.current = null;
    if (target === "add") addButton.current?.focus();
    else if (typeof target === "number") {
      const inputs = table.current?.querySelectorAll<HTMLInputElement>("tr > td:first-child > input");
      const next = inputs?.[Math.min(target, inputs.length - 1)];
      if (next) next.focus(); else addButton.current?.focus();
    }
  }, [items.length, newQuestions.length]);
  const updateNew = (key: string, values: Partial<NewQuestion>) => onNewQuestions?.(newQuestions.map(row => row.key === key ? { ...row, ...values } : row));
  const canAdd = editable && !!onNewQuestions && !!onCreateQuestion;
  return (
    <section className={styles.panel} aria-label="待决问题">
      <header className={styles.panelHeading}>
        <h2>待决问题</h2>
        <span>{items.length} 项</span>
      </header>
      {(items.length > 0 || newQuestions.length > 0) && (
        <div className={styles.tableScroll} role="region" aria-label="待决问题表格" tabIndex={0}>
          <table className={`${styles.specTable} ${styles.editableSpecs} ${styles.questionTable} ${editable ? styles.cellEdit : ""}`}>
            <colgroup><col /><col className={styles.ownerColumn} /><col className={styles.dueColumn} /><col className={styles.stateColumn} />{editable && <col className={styles.actionColumn} />}</colgroup>
            <thead>
              <tr>
                <th>问题</th>
                <th>负责人</th>
                <th>期限</th>
                <th>状态与答复</th>
                {editable && <th><span className="sr-only">操作</span></th>}
              </tr>
            </thead>
            <tbody ref={table}>
              {items.map((item, index) => (
                <QuestionRow key={`${item.item_id}:${item.version}`} {...props} item={item} index={index} onRemoved={() => { focusAfter.current = items.length > 1 ? Math.min(index, items.length - 2) : "add"; }} />
              ))}
              {canAdd && newQuestions.map((row, index) => (
                <tr key={row.key} data-draft="true">
                  <td>
                    <input aria-label={`新问题 ${index + 1}`} disabled={busy} value={row.question} placeholder="填写问题" onChange={event => updateNew(row.key, { question: event.target.value })} />
                    <small className={styles.cellNote}>新增问题，确认后登记负责人与期限</small>
                  </td>
                  <td>
                    <select aria-label={`新问题负责人 ${index + 1}`} disabled={busy} value={row.owner_id} onChange={event => updateNew(row.key, { owner_id: event.target.value })}>
                      <option value="">选择负责人</option>
                      {people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}
                    </select>
                  </td>
                  <td><input type="date" aria-label={`新问题期限 ${index + 1}`} required disabled={busy} value={row.due_date} onChange={event => updateNew(row.key, { due_date: event.target.value })} /></td>
                  <td>待答复</td>
                  <td>
                    <div className={styles.rowTools}>
                      <Button size="icon" variant="ghost" disabled={busy || !row.question.trim() || !row.owner_id || !row.due_date} aria-label={`核对新增问题 ${index + 1}`} title="核对新增问题" onClick={() => onCreateQuestion?.(row)}><Check size={14} /></Button>
                      <Button size="icon" variant="ghost" disabled={busy} aria-label={`移除未保存的新问题 ${index + 1}`} title="移除" onClick={() => { focusAfter.current = items.length + index > 0 ? items.length + index - 1 : "add"; onNewQuestions?.(newQuestions.filter(value => value.key !== row.key)); }}><X size={14} /></Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canAdd && (
        <button
          ref={addButton}
          type="button"
          className={styles.addRow}
          disabled={busy}
          onClick={() => {
            focusAfter.current = items.length + newQuestions.length;
            onNewQuestions?.([...newQuestions, { key: crypto.randomUUID(), question: "", owner_id: "", due_date: "" }]);
          }}
        >
          <Plus size={13} />添加问题
        </button>
      )}
      {editable && (items.length > 0 || newQuestions.length > 0) && (
        <p className={styles.note}>状态与答复随“保存修订”一起保存；新增问题或修改问题、负责人、期限时，会预览一次新的责任安排，原记录保留。</p>
      )}
      {!items.length && !newQuestions.length && (
        <p className={styles.empty}>暂无待决问题{canAdd ? "，可直接添加，或与旁边的小Pai继续完善。" : "。"}</p>
      )}
    </section>
  );
}

export function ProposalItemTable(props: Props) {
  return props.kind === "option" ? <OptionComparison {...props} /> : <QuestionTable {...props} />;
}
