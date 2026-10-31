"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowClockwise, ArrowRight, MagnifyingGlass, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { readKnowledgeLibrary, readKnowledgeLibraryProducts, type KnowledgeLibraryApi } from "@/lib/knowledge-library";
import type { KnowledgeCandidate, KnowledgeRule, KnowledgeView } from "@/lib/knowledge-experience";
import { KnowledgeCandidateReading, KnowledgeLibrary, KnowledgeRuleReading } from "./knowledge-library";
import s from "../organization.module.css";
import { VerifiedAnswers, KnowledgeReviewReminders } from "./verified-answers";

type Category = { id: string; name: string };
type Entry = { scope: Category; product: string; data: KnowledgeView } & ({ kind: "candidate"; value: KnowledgeCandidate } | { kind: "rule"; value: KnowledgeRule });
type Props = { api: KnowledgeLibraryApi; categories: Category[]; principalId: string };
export function KnowledgeIndex(props: Props) { return <Index key={`${props.principalId}:${props.categories.map(c => c.id).join(":")}`} {...props}/>; }
function Index({ api, categories, principalId }: Props) {
  const [attempt, refresh] = useState(0), [state, setState] = useState<{ api: KnowledgeLibraryApi; attempt: number; rows: Entry[]; errors: string[] } | null>(null);
  const [tab, setTab] = useState("published"), [query, setQuery] = useState(""), [category, setCategory] = useState("");
  const [selected, select] = useState<Entry | null>(null), [manage, setManage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const categoryKey = JSON.stringify(categories);
  useEffect(() => {
    let active = true;
    const scopes = JSON.parse(categoryKey) as Category[];
    async function read() {
      const rows: Entry[] = [], errors: string[] = [];
      // Limit concurrency; each existing reader validates the returned category/product binding.
      for (const scope of scopes) {
        const context = { categoryId: scope.id, principalId, productId: null };
        const append = (data: KnowledgeView, product: string) => {
          rows.push(...data.candidates.map(value => ({ kind: "candidate" as const, value, scope, product, data })), ...data.rules.map(value => ({ kind: "rule" as const, value, scope, product, data })));
          if (data.candidates.length >= 100 || data.rules.length >= 100) errors.push(`${scope.name}：当前接口返回最近 100 条，请进入品类进一步查阅。`);
        };
        try {
          const [data, products] = await Promise.all([readKnowledgeLibrary(api, context), readKnowledgeLibraryProducts(api, context)]);
          if (!active) return;
          append(data, "品类通用");
          for (const product of products) {
            try { const details = await readKnowledgeLibrary(api, { ...context, productId: product.id }); if (!active) return; append(details, product.name); }
            catch (failure) { errors.push(`${scope.name} · ${product.name}暂不可读，请刷新或核对权限。`); const status = (failure as Error & { status?: number }).status; if (status === 401) { if (active) setState({ api, attempt, rows: [], errors }); return; } if (status === 403 || status === 404) { for (let i = rows.length - 1; i >= 0; i--) if (rows[i].scope.id === scope.id) rows.splice(i,1); break; } }
          }
        } catch (failure) { errors.push(`${scope.name}暂不可读，请刷新或核对权限。`); if ((failure as Error & { status?: number }).status === 401) { if (active) setState({ api, attempt, rows: [], errors }); return; } }
      }
      if (active) setState({ api, attempt, rows, errors });
    }
    void read(); return () => { active = false; };
  }, [api, principalId, categoryKey, attempt]);
  useEffect(() => { if (selected) dialog.current?.showModal(); else dialog.current?.close(); }, [selected]);
  const current = state?.api === api && state.attempt === attempt ? state : null;
  const status = (entry: Entry) => entry.kind === "candidate" ? "candidate" : ["expired", "needs_recheck"].includes(entry.value.usability.state) ? "inactive" : "published";
  const statusLabel = (entry: Entry) => entry.kind === "candidate" ? "候选" : entry.value.usability.state === "not_yet_effective" ? "尚未生效" : status(entry) === "inactive" ? (entry.value.usability.state === "expired" ? "已失效" : "需重核") : "已发布";
  const rows = current?.rows.filter(row => status(row) === tab && (!category || row.scope.id === category) && `${row.value.title} ${row.scope.name} ${row.product}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) ?? [];
  const managing = categories.find(c => c.id === manage);
  if (managing) return <><Button variant="ghost" size="sm" onClick={() => { setManage(""); refresh(v => v + 1); }}>← 返回知识</Button><VerifiedAnswers api={api} principalId={principalId} categoryId={managing.id} categoryName={managing.name}/><KnowledgeLibrary api={api} principalId={principalId} categoryId={managing.id} categoryName={managing.name}/></>;
  return <section className={s.page} aria-label="知识">
    <header className="workspace-page-heading"><div><h1>知识</h1><p>团队积累的经验、规则与适用边界。</p></div><Button size="xs" variant="ghost" aria-label="刷新知识" onClick={() => { select(null); refresh(v => v + 1); }}><ArrowClockwise/></Button></header>
    <KnowledgeReviewReminders api={api} categories={categories} onOpen={setManage}/>
    <div className={s.toolbar}><nav className="workspace-view-tabs" aria-label="知识状态">{[["answers","核实答案"],["published","已发布"],["candidate","候选"],["inactive","已失效"]].map(([id,label]) => <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}</nav><div className={s.filters}><select aria-label="筛选知识品类" value={category} onChange={e => setCategory(e.target.value)}><option value="">所有品类</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><label className={s.search}><MagnifyingGlass size={14}/><input type="search" aria-label="搜索知识" placeholder="搜索知识…" value={query} onChange={e => setQuery(e.target.value)}/></label></div></div>
    {tab === "answers" ? <>{categories.filter(scope => !category || scope.id === category).map(scope => <VerifiedAnswers key={scope.id} api={api} categoryId={scope.id} categoryName={scope.name} principalId={principalId}/>)}</> : <>{!current ? <p className={s.empty} role="status">正在读取知识…</p> : <>{current.errors.length > 0 && <div className={s.notice} role="status">{current.errors.join(" ")}<Button variant="ghost" size="xs" onClick={() => refresh(v => v + 1)}>重新读取</Button></div>}<div className={s.scroll}><table className={s.table}><thead><tr><th>知识</th><th>状态</th><th>适用范围</th><th>来源</th></tr></thead><tbody>{rows.map(row => <tr key={`${row.kind}:${row.value.id}`}><td><button className={s.titleLink} onClick={() => select(row)}>{row.value.title}</button></td><td><span className={s.tag}>{statusLabel(row)}</span></td><td>{row.scope.name}<small>{row.kind === "rule" ? `${row.value.applicability.purpose} · ${row.product}` : row.product}</small></td><td>{row.kind === "candidate" ? row.value.origin === "ai" ? "小Pai整理" : "人工记录" : "经验候选转化"}<small>{row.value.sources.length} 项引用</small></td></tr>)}</tbody></table></div>{!rows.length && <div className={s.empty}>暂无{query || category ? "匹配的" : ""}{tab === "published" ? "已发布知识" : tab === "candidate" ? "知识候选" : "失效知识"}。</div>}</>}
    </>}
    <dialog ref={dialog} className={s.peek} aria-label="知识详情" onCancel={() => select(null)}><header><span>知识详情</span><Button size="icon-xs" variant="ghost" aria-label="关闭知识详情" onClick={() => select(null)}><X/></Button></header>{selected && current?.rows.includes(selected) && <><div className={s.peekBody}>{selected.kind === "candidate" ? <KnowledgeCandidateReading value={selected.value} projects={selected.data.projects}/> : <KnowledgeRuleReading value={selected.value} projects={selected.data.projects} configurations={selected.data.configurations}/>}</div><footer><Button variant="outline" size="sm" onClick={() => { setManage(selected.scope.id); select(null); }}>管理该品类知识<ArrowRight/></Button></footer></>}</dialog>
  </section>;
}
