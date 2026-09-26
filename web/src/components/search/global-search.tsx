"use client";

import { MagnifyingGlassIcon, ArrowSquareOutIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { WorkspaceShell } from "@/components/workspace-shell";
import { Button } from "@/components/ui/button";
import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import type { WorkspaceIdentity } from "@/components/workspace-types";

type Row = Record<string, unknown>;
const kinds: Record<string, string> = { project: "项目", requirement: "需求", task: "任务", issue: "问题", risk: "风险", decision: "决策", specification: "规格", sample: "样机", document: "项目附件", attachment: "本人会话附件", memory: "已审核知识" };
const text = (value: unknown) => value == null ? "" : String(value);
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const obj = (value: unknown): Row => isRecord(value) ? value : {};
async function read(path: string, signal?: AbortSignal): Promise<Row> {
  const response = await fetch(path, { cache: "no-store", signal });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(text(obj(obj(value).detail).message) || "搜索暂不可用，请稍后重试");
  return value;
}
function Highlight({ value, terms }: { value: string; terms: string[] }) {
  if (!terms.length) return value;
  const expression = new RegExp(`(${[...terms].sort((a, b) => b.length - a.length).map(term => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return <>{value.split(expression).map((part, i) => terms.some(term => term.toLowerCase() === part.toLowerCase()) ? <mark key={i} className="rounded-sm bg-primary/15 text-foreground">{part}</mark> : part)}</>;
}
function SourceReader({ hit, onClose }: { hit: Row; onClose: () => void }) {
  const [fragment, setFragment] = useState(Number(hit.fragment_ordinal) || 1), [offset, setOffset] = useState(0);
  const [data, setData] = useState<Row | null>(null), [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    void read(`/api/search/sources/${text(hit.kind)}/${text(hit.id)}?fragment=${fragment}&offset=${offset}`, controller.signal).then(value => {
      if (!controller.signal.aborted) { setData(value); setError(null); setLoading(false); }
    }).catch(e => { if (!controller.signal.aborted) { setData(null); setError(e instanceof Error ? e.message : "原文不可用"); setLoading(false); } });
    return () => controller.abort();
  }, [hit.kind, hit.id, fragment, offset]);
  function move(nextFragment: number, nextOffset = 0) { setLoading(true); setData(null); setError(null); setFragment(nextFragment); setOffset(nextOffset); }
  return <section aria-label="核对原资料" className="space-y-3 rounded-lg border bg-muted/20 p-4">
    <div className="flex items-start justify-between gap-3"><h2 className="font-semibold">核对原资料 · {text(data?.title ?? hit.title)}</h2><Button type="button" size="sm" variant="ghost" onClick={onClose}>收起</Button></div>
    {loading && <p role="status" className="text-sm">正在按当前权限读取…</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {data && !loading && <><p className="text-xs text-muted-foreground">{text(data.project_name) || "租户需求池"}{data.locator ? ` · ${text(data.locator)}` : ""} · 当前可读字段{!["document", "attachment"].includes(text(data.kind)) ? "（业务记录的可搜索文本）" : ""}</p>
      {Number(data.fragment_count) > 0 && <div className="flex flex-wrap items-center gap-2 text-xs"><span>片段 {fragment} / {String(data.fragment_count)}</span><Button type="button" variant="outline" size="sm" disabled={fragment <= 1} onClick={() => move(fragment - 1)}>上一片段</Button><Button type="button" variant="outline" size="sm" disabled={fragment >= Number(data.fragment_count)} onClick={() => move(fragment + 1)}>下一片段</Button></div>}
      <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 font-sans text-sm leading-6">{text(data.text) || (data.status === "ocr_required" ? "此文件尚无可用抽取正文，需要文字识别后再核对。" : "此记录没有可读正文。")}</pre>
      {Number(data.total_characters) > 0 && <p className="text-xs text-muted-foreground">显示本段第 {offset + 1}–{Math.min(offset + 6000, Number(data.total_characters))} 字，共 {String(data.total_characters)} 字。抽取文本不替代原图纸、签核或正式业务记录。</p>}
      <div className="flex flex-wrap gap-2">{offset > 0 && <Button type="button" size="sm" variant="outline" onClick={() => move(fragment, Math.max(0, offset - 6000))}>上一段正文</Button>}{typeof data.next_offset === "number" && <Button type="button" size="sm" variant="outline" onClick={() => move(fragment, Number(data.next_offset))}>继续读取正文</Button>}<Link href={text(data.href)} className="inline-flex items-center gap-1 text-sm text-primary underline">进入原业务页面<ArrowSquareOutIcon aria-hidden="true" /></Link></div>
    </>}
  </section>;
}

export function GlobalSearch() {
  const router = useRouter(), params = useSearchParams();
  const query = params.get("q") ?? "", project = params.get("project") ?? "", kind = params.get("kind") ?? "";
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null), [projects, setProjects] = useState<Project[]>([]);
  const [data, setData] = useState<Row | null>(null), [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false), [loggingOut, setLoggingOut] = useState(false);
  const [selected, setSelected] = useState<Row | null>(null);
  const [refresh, setRefresh] = useState(0);
  const sequence = useRef(0);
  const signature = JSON.stringify([query, project, kind]);
  const [resultSignature, setResultSignature] = useState("");
  const shown = resultSignature === signature ? data : null;
  const base = `/api/search?q=${encodeURIComponent(query)}${project ? `&project_id=${encodeURIComponent(project)}` : ""}${kind ? `&kinds=${encodeURIComponent(kind)}` : ""}`;
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const user = await requestIdentity();
        if (!user) { router.replace("/login"); return; }
        const available = await requestProjectList();
        if (active) { setIdentity(user); setProjects(available ?? []); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "搜索入口暂不可用"); }
    })();
    return () => { active = false; };
  }, [router]);
  useEffect(() => {
    if (!identity || !query.trim()) return;
    const controller = new AbortController(), current = ++sequence.current;
    void read(base, controller.signal).then(value => {
      if (!controller.signal.aborted && current === sequence.current) { setData(value); setResultSignature(signature); setSelected(null); setError(null); setLoading(false); }
    }).catch(e => { if (!controller.signal.aborted && current === sequence.current) { setData(null); setResultSignature(signature); setSelected(null); setError(e instanceof Error ? e.message : "搜索未完成"); setLoading(false); } });
    return () => controller.abort();
  }, [identity, query, base, signature, refresh]);
  async function more() {
    if (!shown?.next_cursor || loading) return;
    const current = ++sequence.current;
    setLoading(true); setError(null);
    try { const value = await read(`${base}&cursor=${encodeURIComponent(text(shown.next_cursor))}`); if (current === sequence.current) setData({ ...value, items: [...rows(shown.items), ...rows(value.items).filter(next => !rows(shown.items).some(old => old.kind === next.kind && old.id === next.id))] }); }
    catch (e) { if (current === sequence.current) setError(e instanceof Error ? e.message : "读取下一页失败"); }
    finally { if (current === sequence.current) setLoading(false); }
  }
  if (!identity) return <p role="status" className="p-6 text-sm">{error ?? "正在读取搜索权限…"}</p>;
  const terms = Array.isArray(shown?.terms) ? shown.terms.map(String) : [];
  return <WorkspaceShell active="search" identity={identity} loggingOut={loggingOut} onLogout={() => { setLoggingOut(true); void fetch("/api/session/logout", { method: "POST" }).finally(() => router.replace("/login")); }}>
    <main className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6"><header><h1 className="text-2xl font-semibold">搜索</h1><p className="mt-2 text-sm text-muted-foreground">查找业务记录、附件正文与已审核知识。仅返回当前有权读取的资料；私人附件仅限本人会话。</p></header>
      <form key={signature} className="space-y-3 rounded-lg border bg-card p-4" onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); const next = new URLSearchParams(); const entered = text(form.get("q")).trim(); if (!entered) { setError("请填写搜索词"); return; } next.set("q", entered); if (form.get("project")) next.set("project", text(form.get("project"))); if (form.get("kind")) next.set("kind", text(form.get("kind"))); setError(null); setSelected(null); setResultSignature(""); if (JSON.stringify([entered, text(form.get("project")), text(form.get("kind"))]) === signature) setRefresh(value => value + 1); router.push(`/search?${next}`); }}>
        <label className="block text-sm font-medium" htmlFor="global-search-query">关键词或编号</label><div className="flex gap-2"><input id="global-search-query" name="q" required maxLength={200} defaultValue={query} className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm" placeholder="例如：密封 泄漏，或样机编号 SN-120"/><Button type="submit"><MagnifyingGlassIcon aria-hidden="true" className="mr-1 size-4"/>搜索</Button></div>
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">资料范围<select name="project" defaultValue={project} className="mt-1 w-full rounded-md border bg-background p-2"><option value="">全部可访问资料</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="text-sm">资料类型<select name="kind" defaultValue={kind} className="mt-1 w-full rounded-md border bg-background p-2"><option value="">全部类型</option>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        <p className="text-xs text-muted-foreground">多个词用空格分开，顺序不限且每个词都须命中。项目筛选只看项目内资料；租户需求池在“全部可访问资料”中查找。</p>
      </form>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {query.trim() && resultSignature !== signature && <p role="status" className="text-sm">正在搜索…</p>}
      {shown && <><p role="status" className="text-sm">已显示 {rows(shown.items).length} 条匹配资料{shown.next_cursor ? "，还有更多结果" : ""}，按相关程度及更新时间排列。</p>{shown.terms_truncated === true && <p className="text-sm text-primary">本次只使用前8个不同关键词：{terms.join("、")}。请缩小条件后继续。</p>}
        {!rows(shown.items).length && <p className="rounded-md bg-muted/30 p-4 text-sm">当前可访问范围内没有匹配。可减少关键词、修改编号或调整资料类型。</p>}
        <div className="space-y-3">{rows(shown.items).map(hit => <article key={`${hit.kind}:${hit.id}`} className="space-y-2 rounded-lg border bg-card p-4"><p className="text-xs text-muted-foreground">{kinds[text(hit.kind)] ?? "资料"} · {text(hit.project_name) || "租户需求池"} · {new Date(text(hit.occurred_at)).toLocaleString("zh-CN")}</p><h2 className="font-medium"><Highlight value={text(hit.title)} terms={terms}/></h2><p className="whitespace-pre-wrap break-words text-sm leading-6"><Highlight value={text(hit.excerpt)} terms={terms}/></p>{hit.locator != null && <p className="text-xs text-muted-foreground">命中片段：{text(hit.locator)}。多个词可能分布于不同片段。</p>}{hit.status === "ocr_required" && <p className="text-xs text-primary">仅匹配文件名，正文尚待文字识别。</p>}<div className="flex flex-wrap items-center gap-4"><Button type="button" size="sm" variant="outline" onClick={() => setSelected(hit)}>核对原资料</Button><Link className="text-sm text-primary underline" href={text(hit.href)}>进入原业务页面</Link></div>{selected?.id === hit.id && selected?.kind === hit.kind && <SourceReader key={`${hit.kind}:${hit.id}`} hit={hit} onClose={() => setSelected(null)}/>}</article>)}</div>
        {shown.next_cursor != null && <Button type="button" variant="outline" disabled={loading} onClick={() => void more()}>{loading ? "正在读取…" : "更多结果"}</Button>}
      </>}
      {!query.trim() && <p className="text-sm text-muted-foreground">输入关键词开始。知识只包含已审核且来源仍有效的内容；搜索结果不代表测试通过、专业批准或业务承诺。</p>}
    </main>
  </WorkspaceShell>;
}
