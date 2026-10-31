"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AnswerComparison } from "./answer-comparison";
import { AnswerTaskResult } from "./answer-task-result";
import styles from "../pai-conversation.module.css";

type Source = { citation_id: string; title: string; quote: string; source_revision: number; currentness?: string; read_basis_status?: string; fixed_body_available?: boolean; locator?: Record<string, unknown>; url?: string; object_url?: string; object_label?: string; relation?: unknown; group?: string; group_label?: string };
type Answer = { lookup?: string; notice?: string | null; sources?: unknown; unknowns?: unknown; comparison?: unknown; task_result?: unknown };
const uuid = /^[a-f0-9-]{36}$/i;
const sourcePath = /^\/api\/v1\/(?:personal|categories\/[a-f0-9-]{36})\/agent-runs\/[a-f0-9-]{36}\/assistant-sources\/[a-f0-9-]{36}(?:\?change_id=[a-f0-9]{64})?$/i;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
function sources(value: unknown): Source[] {
  if (!Array.isArray(value)) return [];
  const rows = value.filter((row): row is Source => object(row) && typeof row.citation_id === "string" && uuid.test(row.citation_id) && typeof row.title === "string" && typeof row.quote === "string" && Number.isInteger(row.source_revision) && Number(row.source_revision) > 0);
  // Keep one card per citation before additional snippets so every checked cell
  // can locate its source within the bounded source display.
  const primary = new Map<string, Source>();
  for (const row of rows) if (!primary.has(row.citation_id)) primary.set(row.citation_id, row);
  return [...primary.values(), ...rows.filter(row => primary.get(row.citation_id) !== row)].slice(0, 96);
}
export function sourceObjectHref(value: unknown): string | null {
  if (typeof value !== "string" || !value.startsWith("/?") || value.length > 1000 || value.includes("#")) return null;
  const params = new URLSearchParams(value.slice(2));
  const allowed = new Set(["area", "category", "product", "project", "projectView", "panel", "build", "run", "issue", "change"]);
  if ([...params.keys()].some(key => !allowed.has(key) || params.getAll(key).length !== 1) || params.get("area") !== "cockpit") return null;
  const identity = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  if (!["category", "product", "project"].every(key => identity.test(params.get(key) ?? ""))) return null;
  if (!["build", "run", "issue", "change"].every(key => !params.has(key) || identity.test(params.get(key) ?? ""))) return null;
  const destination = `${params.get("projectView")}:${params.get("panel")}`;
  const selectors: Record<string, string[]> = { "issues:quality": ["build", "issue"], "issues:followup": ["build", "issue"], "issues:changes": ["change"], "builds:summary": ["build"], "builds:results": ["build", "run"], "prep:supply": ["build"] };
  if (!Object.hasOwn(selectors, destination) || !selectors[destination].every(key => params.has(key)) || ["build", "run", "issue", "change"].some(key => params.has(key) && !selectors[destination].includes(key))) return null;
  return value;
}
const relations: Record<string, string> = { issue_capa: "问题对应的 CAPA", capa_issue: "CAPA 来源问题", change_issue: "变更依据中的问题", change_capa: "变更依据中的 CAPA", issue_change: "引用此问题的变更", capa_change: "引用此 CAPA 的变更", merged_into: "合并后的问题", merged_from: "合并前的问题", build_build: "同一试制轮次的登记记录", build_test_run: "试制轮次的测试记录", test_run_build: "测试对应的试制轮次", build_supply: "试制轮次的供应记录", supply_build: "供应记录对应的试制轮次" };
function location(value: Source["locator"]): string {
  if (!value) return "固定片段";
  if (Array.isArray(value.native) && typeof value.native[0] === "string") return value.native.slice(0, 3).join(" · ");
  if (value.json_pointer) return value.json_pointer === "/facts" ? "业务记录" : "知识记录";
  if (Number.isInteger(value.line_start)) return `第 ${value.line_start} 行`;
  return "固定片段";
}

export function SourceSnippet({ url, onUnavailable, onChanged, historical = false }: { url: string; onUnavailable: () => void; onChanged?: () => void; historical?: boolean }) {
  const [reading, setReading] = useState<{ text: string[]; next: number | null; loading: boolean }>({ text: [], next: null, loading: false });
  const lifetime = useRef({ active: true, attempt: 0 });
  useEffect(() => { const gate = lifetime.current; gate.active = true; return () => { gate.active = false; gate.attempt++; }; }, []);
  async function read() {
    if (!sourcePath.test(url) || reading.loading) return;
    const gate = lifetime.current, generation = ++gate.attempt;
    setReading(value => ({ ...value, loading: true }));
    try {
      const [path, rawQuery] = url.split("?");
      const query = new URLSearchParams(rawQuery); query.set("cursor", String(reading.next ?? 0)); query.set("page_chars", "1600");
      const response = await fetch(`${path}?${query}`, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) {
        const error: unknown = response.status === 409 ? await response.json() : null;
        if (object(error) && error.code === "SOURCE_STALE" && onChanged) {
          if (gate.active && generation === gate.attempt) { setReading({ text: [], next: null, loading: false }); onChanged(); }
          return;
        }
        throw new Error("Source unavailable");
      }
      const value: unknown = await response.json();
      if (!object(value) || typeof value.text !== "string" || Array.from(value.text).length > 2000 || !(value.next_cursor === null || Number.isInteger(value.next_cursor) && Number(value.next_cursor) > 0)) throw new Error("Invalid bounded source page");
      if (!gate.active || generation !== gate.attempt) return;
      setReading(previous => ({ text: [...previous.text, value.text as string], next: value.next_cursor as number | null, loading: false }));
    } catch {
      if (gate.active && generation === gate.attempt) { setReading({ text: [], next: null, loading: false }); onUnavailable(); }
    }
  }
  return <div className={styles.sourceSnippet}>
    {reading.text.length > 0 && <pre tabIndex={0} aria-label="当前可读的固定资料片段">{reading.text.join("")}</pre>}
    {(!reading.text.length || reading.next !== null) && <Button type="button" size="sm" variant="ghost" disabled={reading.loading} onClick={read}>{reading.loading ? "正在读取…" : reading.text.length ? "继续读取" : historical ? "查看原固定片段" : "查看资料段落"}</Button>}
  </div>;
}

function SourceCard({ source, anchorId }: { source: Source; anchorId: string }) {
  const [unavailable, setUnavailable] = useState(false);
  const [changed, setChanged] = useState(source.currentness === "updated");
  const [fixedBlocked, setFixedBlocked] = useState(false);
  const updated = changed || source.currentness === "updated";
  const objectHref = sourceObjectHref(source.object_url);
  const relation = object(source.relation) && typeof source.relation.type === "string" && Object.hasOwn(relations, source.relation.type) ? relations[source.relation.type] : null;
  if (unavailable) return <li id={anchorId} role="status" className={styles.lookupNote}>这条资料当前不可读取，请重新查询。</li>;
  return <li id={anchorId} className={styles.answerSource}>
    <p><strong>{source.title}</strong><span>v{source.source_revision} · {location(source.locator)}{updated ? " · 资料已更新" : source.currentness === "history" ? " · 历史版本" : ""}</span></p>
    {(source.group === "current" || source.group === "same_category") && <p className={styles.lookupNote}>{source.group === "same_category" ? "同品类其他项目" : source.group_label === "当前提案" ? "当前提案" : "当前项目"}</p>}
    {relation && <p className={styles.lookupNote}>显式关联 · {relation}</p>}
    {source.quote && <blockquote>{source.quote}</blockquote>}
    {objectHref && <a className="text-sm underline underline-offset-4" href={objectHref} title="打开当前登记对象；本回答保留引用的固定版本">{typeof source.object_label === "string" ? source.object_label : "查看当前对象"}</a>}
    {updated && <p role="status" className={styles.lookupNote}>保留原回答引用，当前事实请重新查询。</p>}
    {(!updated || source.fixed_body_available === true && !fixedBlocked) && source.url && sourcePath.test(source.url) && <SourceSnippet key={source.url} url={source.url} historical={updated} onUnavailable={() => setUnavailable(true)} onChanged={() => { setChanged(true); setFixedBlocked(true); }} />}
  </li>;
}

export function AnswerSources({ answer }: { answer?: Answer }) {
  const sourceDetails = useRef<HTMLDetailsElement>(null);
  if (!answer || answer.lookup === "not_run") return null;
  const rows = sources(answer.sources);
  const unknowns = Array.isArray(answer.unknowns) ? answer.unknowns.filter((value): value is string => typeof value === "string").slice(0, 10) : [];
  return <div className={styles.answerGrounding}>
    <AnswerComparison value={answer.comparison}/>
    <AnswerTaskResult value={answer.task_result} sources={rows} onSource={() => { if (sourceDetails.current) sourceDetails.current.open = true; }}/>
    {answer.notice && <p className={styles.lookupNote}>{answer.notice}</p>}
    {rows.length > 0 && <details ref={sourceDetails} className={styles.runDetails}><summary>来源 · {new Set(rows.map(row => row.citation_id)).size}</summary><ol className={styles.answerSources}>{rows.map((row, index) => <SourceCard key={`${row.citation_id}:${index}`} anchorId={`assistant-source-${row.citation_id}-${index}`} source={row} />)}</ol></details>}
    {unknowns.length > 0 && <p className={styles.lookupNote}>待确认：{unknowns.join("；")}</p>}
  </div>;
}
