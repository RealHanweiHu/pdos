"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LockKey, MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import styles from "./proposal-list.module.css";

type Proposal = {
  id: string;
  title: string;
  status: string;
  revision: number;
  owner_id: string;
  visibility: string;
  categoryId: string;
};
type Page = { items: Proposal[]; next_cursor: string | null };
const statusLabels: Record<string, string> = {
  draft: "草稿",
  returned: "已退回",
  in_review: "评审中",
  approved: "已批准",
  rejected: "不立项",
  withdrawn: "已撤回",
};
const visibilityLabels: Record<string, string> = {
  private: "私有提案",
  category: "品类共享",
  audience: "指定受众",
};
type Props = {
  compact?: boolean;
  categoryId: string;
  api: typeof browserApi;
  categories?: { id: string; name: string }[];
};

export function ProposalList(props: Props) {
  return <List key={props.categoryId} {...props} />;
}
function List({ categoryId, api, categories, compact = false }: Props) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [scope, setScope] = useState(categories?.length ? "" : categoryId);
  const [retry, setRetry] = useState(0);
  const [reading, setReading] = useState<{
    key: string;
    items: Proposal[];
    cursors: Record<string, string | null>;
    errors: string[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const categoryIds =
    scope || (categories ?? []).map((item) => item.id).join(",");
  const key = JSON.stringify([categoryIds, q, status, retry]);
  const current = reading?.key === key ? reading : null;
  const load = useCallback(
    async (previous?: NonNullable<typeof reading>) => {
      const own = ++generation.current;
      setBusy(true);
      const ids = categoryIds
        .split(",")
        .filter((id) => id && (!previous || previous.cursors[id]));
      const results = await Promise.allSettled(
        ids.map(async (id) => {
          const query = new URLSearchParams({ page_size: "50" });
          if (q.trim()) query.set("q", q.trim());
          if (status) query.set("status", status);
          if (previous?.cursors[id]) query.set("cursor", previous.cursors[id]!);
          const page = await api<Page>(
            `v1/categories/${id}/proposals?${query}`,
          );
          if (
            !Array.isArray(page.items) ||
            (page.next_cursor && page.next_cursor === previous?.cursors[id])
          )
            throw new Error("分页位置未推进，请重新读取。");
          return { id, page };
        }),
      );
      if (generation.current !== own) return;
      let items = previous?.items ?? [];
      const cursors = { ...previous?.cursors },
        errors: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          const { id, page } = result.value;
          items = [
            ...items,
            ...page.items.map((item) => ({ ...item, categoryId: id })),
          ];
          cursors[id] = page.next_cursor;
        } else {
          const id = ids[index];
          items = items.filter((item) => item.categoryId !== id);
          delete cursors[id];
          errors.push(
            `${categories?.find((item) => item.id === id)?.name ?? "当前品类"}：${result.reason instanceof Error ? result.reason.message : "提案暂不可读"}`,
          );
        }
      });
      setReading({
        key,
        items: [...new Map(items.map((item) => [item.id, item])).values()],
        cursors,
        errors,
      });
      setBusy(false);
    },
    [api, categoryIds, categories, key, q, status],
  );
  useEffect(() => {
    const counter = generation;
    const timer = setTimeout(() => void load(), 180);
    return () => {
      clearTimeout(timer);
      counter.current++;
    };
  }, [load]);
  useEffect(() => {
    const refresh = () => setRetry((value) => value + 1);
    window.addEventListener("pdos:proposal-saved", refresh);
    return () => window.removeEventListener("pdos:proposal-saved", refresh);
  }, []);
  return (
    <div>
      <div className={styles.toolbar}>
        <nav className={styles.tabs} aria-label="提案状态">{[{ id: "", label: "全部" }, { id: "draft", label: "草稿" }, { id: "in_review", label: "评审中" }, { id: "approved", label: "已批准" }].map(item => <button type="button" key={item.id} aria-pressed={status === item.id} onClick={() => setStatus(item.id)}>{item.label}</button>)}<select aria-label="其他提案状态" value={["", "draft", "in_review", "approved"].includes(status) ? "" : status} onChange={event => setStatus(event.target.value)}><option value="">更多</option>{Object.entries(statusLabels).filter(([value]) => !["draft", "in_review", "approved"].includes(value)).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></nav>
        {categories && <select aria-label="筛选提案品类" value={scope} onChange={event => setScope(event.target.value)}><option value="">全部品类</option>{categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
        <label className={styles.search}>
          <MagnifyingGlass size={14} aria-hidden="true" />
          <input
            type="search"
            aria-label="搜索提案"
            placeholder="搜索提案"
            maxLength={160}
            value={q}
            onChange={(event) => setQ(event.target.value)}
          />
        </label>
      </div>
      {current?.errors.map((error) => (
        <p key={error} role="alert" className="workspace-read-error">
          {error}
        </p>
      ))}
      {!!current?.errors.length && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setRetry((value) => value + 1)}
        >
          重新读取提案
        </Button>
      )}
      {!current && (
        <p role="status" className="subtle">
          正在读取提案…
        </p>
      )}
      {compact ? <div className={styles.finder}>{current?.items.map(item => <a className={styles.finderRow} key={item.id} href={`/categories/${item.categoryId}/proposals/${item.id}`}><span>{item.title}<small>{visibilityLabels[item.visibility] ?? item.visibility} · v{item.revision}</small></span><span>{statusLabels[item.status] ?? item.status}</span></a>)}</div> : <div className={styles.tableScroll}><table className={styles.table}><thead><tr><th>提案</th><th>品类</th><th>可见范围</th><th>状态</th><th>版本</th></tr></thead><tbody>{current?.items.map(item => <tr key={item.id}><td><a href={`/categories/${item.categoryId}/proposals/${item.id}`} title={item.title}>{item.title}{item.visibility === "private" && <LockKey size={13} aria-label="私有提案"/>}</a></td><td>{categories?.find(category => category.id === item.categoryId)?.name ?? "当前品类"}</td><td>{visibilityLabels[item.visibility] ?? item.visibility}</td><td><span className={styles.state} data-state={item.status}>{statusLabels[item.status] ?? item.status}</span></td><td>v{item.revision}</td></tr>)}</tbody></table></div>}
      {current && !current.items.length && !current.errors.length && (
        <p className="workspace-list-empty">
          {q || status
            ? "没有符合条件的提案。"
            : "尚无立项提案。让小Pai结合品类资料起草第一份提案。"}
        </p>
      )}
      {current && Object.values(current.cursors).some(Boolean) && (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => void load(current)}
        >
          {busy ? "正在读取…" : "加载更多提案"}
        </Button>
      )}
    </div>
  );
}
