"use client";

import { Check, PencilSimple, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type {
  ProposalEditableItem,
  ProposalPatch,
  ProposalDrafts,
} from "@/lib/proposal-spec-editor";
import styles from "./proposal-document.module.css";

type Props = ProposalDrafts & {
  items: ProposalEditableItem[];
  people: { id: string; name: string }[];
  editable: boolean;
  busy: boolean;
  mutate: (ops: ProposalPatch[]) => Promise<boolean>;
  kind: "option" | "question";
  onAssignQuestion?: (item: ProposalEditableItem, content: Record<string, unknown>) => void;
};
function Row({
  item: currentItem,
  people,
  editable,
  busy,
  mutate,
  kind,
  drafts = {},
  onDraft,
  onAssignQuestion,
}: Omit<Props, "items"> & { item: ProposalEditableItem }) {
  const entry = drafts[currentItem.item_id],
    editing = !!entry;
  const item = entry?.item ?? currentItem;
  const draft = { ...item.content, ...entry?.values };
  const change = (key: string, value: string) =>
    onDraft?.(item.item_id, {
      item,
      values: { ...entry?.values, [key]: value },
    });
  const content = editing ? draft : item.content;
  const stale = editing && item.version !== currentItem.version;
  const stop = () => onDraft?.(item.item_id, null);
  const field = kind === "option" ? "name" : "question";
  const summaryField =
    "summary" in item.content
      ? "summary"
      : "text" in item.content
        ? "text"
        : "description";
  const input = (key: string, label: string) => (
    <input
            disabled={busy || !editable}
      aria-label={label}
      value={String(content[key] ?? "")}
      onChange={(event) => change(key, event.target.value)}
    />
  );
  return (
    <tr>
      <td>
        {editing ? (
          input(field, kind === "option" ? "方案名称" : "问题内容")
        ) : (
          <strong>{String(content[field])}</strong>
        )}
        <small className={styles.cellNote}>
          {stale && "版本已更新，草稿已保留；取消后重新编辑。"}v{item.version} ·{" "}
          {item.origin === "ai_draft" ? "AI 起草" : "人工记录"}
        </small>
      </td>
      {kind === "option" ? (
        <>
          <td>
            {editing ? (
              <select
            disabled={busy || !editable}
                aria-label="方案类型"
                value={String(content.kind)}
                onChange={(event) => change("kind", event.target.value)}
              >
                <option value="new">新方案</option>
                <option value="status_quo">保持现状</option>
                <option value="do_nothing">不开展</option>
              </select>
            ) : (
              ((
                {
                  new: "新方案",
                  status_quo: "保持现状",
                  do_nothing: "不开展",
                } as Record<string, string>
              )[String(content.kind)] ?? "未确定")
            )}
          </td>
          <td>
            {editing
              ? input(summaryField, "方案说明")
              : String(content[summaryField] ?? "未填写说明")}
          </td>
        </>
      ) : (
        <>
          <td>
            {editing ? <select aria-label="问题负责人" disabled={busy || !editable} value={String(content.owner_id ?? "")} onChange={event => change("owner_id", event.target.value)}>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select> : people.find((person) => person.id === content.owner_id)?.name ?? "未取得姓名"}
          </td>
          <td>{editing ? <input type="date" aria-label="问题期限" required disabled={busy || !editable} value={String(content.due_date ?? "")} onChange={event => change("due_date", event.target.value)}/> : String(content.due_date ?? "未确定")}</td>
          <td>
            {editing ? (
              <>
                <select
            disabled={busy || !editable}
                  aria-label="问题状态"
                  value={String(content.status)}
                  onChange={(event) => change("status", event.target.value)}
                >
                  <option value="open">待答复</option>
                  <option value="answered">已答复</option>
                </select>
                {content.status === "answered" && input("answer", "问题答复")}
              </>
            ) : (
              <>
                {(
                  {
                    open: "待答复",
                    answered: "已答复",
                    carried: "已转入项目",
                  } as Record<string, string>
                )[String(content.status)] ?? "待答复"}
                {typeof content.answer === "string" && content.answer && (
                  <small className={styles.cellNote}>{content.answer}</small>
                )}
              </>
            )}
          </td>
        </>
      )}
      {editable && (
        <td>
          <div className={styles.rowTools}>
            {editing ? (
              <>
                <Button
                  size="icon"
                  variant="ghost"
                  disabled={
                    busy ||
                    stale ||
                    !String(content[field] ?? "").trim() ||
                    (kind === "question" &&
                      content.status === "answered" &&
                      !String(content.answer ?? "").trim())
                  }
                  aria-label={`保存${kind === "option" ? "方案" : "问题"}`}
                  onClick={async () => {
                    if (kind === "question" && ["question", "owner_id", "due_date"].some(key => draft[key] !== item.content[key])) { onAssignQuestion?.(item, draft); return; }
                    if (
                      await mutate([
                        {
                          op: "upsert",
                          item_id: item.item_id,
                          base_version: item.version,
                          kind: item.kind,
                          content: draft,
                          source_refs: item.source_refs,
                        },
                      ])
                    )
                      stop();
                  }}
                >
                  <Check size={14} />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  disabled={busy}
                  aria-label="取消此行编辑"
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
                aria-label={`编辑${String(content[field])}`}
                onClick={() => onDraft?.(item.item_id, { item, values: {} })}
              >
                <PencilSimple size={14} />
              </Button>
            )}
          </div>
        </td>
      )}
    </tr>
  );
}
export function ProposalItemTable(props: Props) {
  const { items, kind, editable } = props;
  return (
    <section
      className={styles.panel}
      aria-label={kind === "option" ? "方案对比" : "待决问题"}
    >
      <header className={styles.panelHeading}><h2>{kind === "option" ? "方案对比" : "待决问题"}</h2><span>{items.length} 项</span></header>
      <div className={styles.tableScroll}>
        <table className={`${styles.specTable} ${styles.editableSpecs}`}>
          <thead>
            <tr>
              <th>{kind === "option" ? "方案" : "问题"}</th>
              <th>{kind === "option" ? "类型" : "负责人"}</th>
              <th>{kind === "option" ? "说明" : "期限"}</th>
              {kind === "question" && <th>状态与答复</th>}
              {editable && (
                <th>
                  <span className="sr-only">操作</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <Row
                key={`${item.item_id}:${item.version}`}
                {...props}
                item={item}
              />
            ))}
          </tbody>
        </table>
      </div>
      {kind === "question" && editable && (
        <p className={styles.empty}>
          修改问题、负责人或期限时，会预览一次新的责任安排；原记录保留。
        </p>
      )}
      {!items.length && (
        <p className={styles.empty}>
          暂无{kind === "option" ? "方案" : "待决问题"}
          ，可与旁边的小Pai继续完善。
        </p>
      )}
    </section>
  );
}
