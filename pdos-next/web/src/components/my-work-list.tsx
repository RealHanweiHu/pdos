"use client";
import { CaretRight, Circle, SlidersHorizontal } from "@phosphor-icons/react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  workKindNames,
  type WorkKind,
  type WorkRow,
} from "@/lib/my-work-items";
import styles from "./my-work-list.module.css";

export type WorkReading = {
  name: string;
  loading: boolean;
  error: string;
  moreError?: string;
  more: boolean;
  busy?: boolean;
  retry: () => void;
  loadMore?: () => Promise<void>;
};
export function MyWorkList({
  rows,
  readings,
  onOpenProject,
  onOpenRun,
}: {
  rows: WorkRow[];
  readings: WorkReading[];
  onOpenProject: (categoryId: string, projectId: string) => void;
  onOpenRun: (runId: string, categoryId: string) => void;
}) {
  const [kind, setKind] = useState<WorkKind | "all">("all"),
    [period, setPeriod] = useState("all"),
    [query, setQuery] = useState("");
  const today = new Date(),
    day = (value: Date) =>
      `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  const now = day(today);
  const end = new Date(today);
  end.setDate(today.getDate() + ((7 - today.getDay()) % 7));
  const filtered = rows.filter(
    (row) =>
      (kind === "all" || row.kind === kind) &&
      `${row.title} ${row.project}`
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()) &&
      (period === "all" ||
        (period === "today"
          ? !!row.due && row.due <= now
          : period === "week"
            ? !!row.due && row.due > now && row.due <= day(end)
            : !row.due || row.due > day(end))),
  );
  const incomplete = readings.some(
    (item) => item.loading || item.error || item.more,
  );
  return (
    <section className={styles.list} aria-label="责任与期限清单">
      <div className={styles.toolbar}><span>{filtered.length} 项需要关注{incomplete ? " · 已加载" : ""}</span><small>按责任与期限排列</small><details className={styles.filters}><summary aria-label="搜索与筛选我的工作" title="搜索与筛选"><SlidersHorizontal size={15}/></summary><div>
        <input
          type="search"
          aria-label="搜索我的工作"
          placeholder="搜索工作或项目"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          aria-label="责任类型"
          value={kind}
          onChange={(event) => setKind(event.target.value as WorkKind | "all")}
        >
          <option value="all">全部类型</option>
          {(Object.entries(workKindNames) as [WorkKind, string][])
            .filter(([key]) => rows.some((row) => row.kind === key))
            .map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
        </select>
        <select
          aria-label="工作期限"
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
        >
          <option value="all">全部期限</option>
          <option value="today">今日与逾期</option>
          <option value="week">本周剩余</option>
          <option value="later">稍后与未定</option>
        </select>
        </div></details>
      </div>
      {readings
        .filter((item) => item.error || item.moreError)
        .map((item) => (
          <div key={item.name} className={styles.notice} role="alert">
            {item.name}：{item.error || item.moreError}
            <Button
              size="xs"
              variant="ghost"
              onClick={item.error ? item.retry : () => void item.loadMore?.()}
            >
              重试
            </Button>
          </div>
        ))}
      {filtered.map((row) => (
        <details key={row.id} className={styles.row}>
          <summary>
            <Circle size={14} className={styles.taskCircle} aria-hidden="true"/>
            <span className={styles.title} title={row.title}>
              {row.title}
            </span>
            <span className={styles.muted} title={row.project}>
              {row.project}
            </span>
            <span className={styles.state}>
              <small>{workKindNames[row.kind]}</small>
              {row.state}
            </span>
            <span
              className={styles.date}
              data-overdue={!!row.due && row.due < now}
              title={row.due ? `${row.dateKind} ${row.due}` : "尚未登记期限"}
            >
              {row.due ? `${row.dateKind} ${row.due.slice(5)}` : "—"}
            </span>
            <CaretRight size={12} aria-hidden="true"/>
          </summary>
          <div className={styles.detail}>
            <dl>
              {row.facts.map(([label, value], index) => (
                <div key={`${label}:${index}`}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            {"href" in row.target ? (
              <a href={row.target.href}>进入原工作</a>
            ) : (
              <Button
                size="xs"
                variant="outline"
                onClick={() => {
                  const target = row.target;
                  if ("runId" in target)
                    onOpenRun(target.runId, target.categoryId);
                  else if ("projectId" in target)
                    onOpenProject(target.categoryId, target.projectId);
                }}
              >
                {"runId" in row.target ? "继续对话" : "进入项目办理"}
              </Button>
            )}
          </div>
        </details>
      ))}
      {!filtered.length && (
        <p className={styles.notice} role="status">
          {readings.some((item) => item.loading)
            ? "正在读取…"
            : incomplete
              ? "已加载记录中暂无匹配项；部分资料尚未取得。"
              : "当前没有符合条件的工作。"}
        </p>
      )}
      {readings.some((item) => item.more) && (
        <div className={styles.notice}>
          <Button
            variant="outline"
            size="xs"
            disabled={readings.some((item) => item.busy)}
            onClick={() =>
              void Promise.allSettled(
                readings
                  .filter((item) => item.more)
                  .map((item) => item.loadMore?.()),
              )
            }
          >
            加载更多工作
          </Button>
          <span>筛选作用于已加载记录</span>
        </div>
      )}
    </section>
  );
}
