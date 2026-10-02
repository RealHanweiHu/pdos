"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ResearchSearch } from "./research-search";
import { ResearchSubscriptions } from "./research-subscriptions";
import { ProductRequestError, request, type Evidence, type EvidenceContent, type ResearchSource, type Workspace } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const uses: Record<string, string> = { internal_analysis: "内部分析", internal_citation: "内部引用", redistribution: "允许再分发" };

type ResearchCollectionProps = { base: string; workspace: Workspace; evidence: Evidence[]; lineId: string | null; canCollect: boolean; refresh: () => Promise<void>; onResponsibilityLock: (value: boolean) => void; onAuthorityLost?: (message: string) => void };

export function ResearchCollection(props: ResearchCollectionProps) {
  return <ResearchCollectionPanel key={JSON.stringify([props.base, props.lineId])} {...props}/>;
}
function ResearchCollectionPanel({ base, workspace, evidence, lineId, canCollect, refresh, onResponsibilityLock, onAuthorityLost }: ResearchCollectionProps) {
  const search = useSearchParams();
  const showSubscription = search.has("subscription_id") || search.get("responsibility_kind") === "subscription";
  const [denied, setDenied] = useState(false);
  const deniedCallback = useRef(onAuthorityLost);
  useEffect(() => { deniedCallback.current = onAuthorityLost; }, [onAuthorityLost]);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [searchConfigured, setSearchConfigured] = useState<boolean | null>(null);
  const [suggestedUrl, setSuggestedUrl] = useState("");
  const [suggestedName, setSuggestedName] = useState("");
  const [registerOpen, setRegisterOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [body, setBody] = useState<EvidenceContent | null>(null);
  const [filter, setFilter] = useState("");
  const [captured, setCaptured] = useState<{ id: string; message: string } | null>(null);
  const alive = useRef(false);
  const operation = useRef(0);
  const locked = useRef(false);
  const sourceVersion = useRef(0);
  const [reading, setReading] = useState(false);
  const clearAuthority = useCallback((message: string) => {
    sourceVersion.current += 1; operation.current += 1; locked.current = false;
    setBusy(false); setReading(false); setDenied(true); setBody(null); setCaptured(null); setNotice(null); setSources([]); setSourceId(""); setSearchConfigured(null);
    setSuggestedUrl(""); setSuggestedName(""); setRegisterOpen(false); setFilter("");
    deniedCallback.current?.(message);
  }, []);
  const load = useCallback(async () => {
    const version = ++sourceVersion.current;
    const value = await request<{ items: ResearchSource[]; search_available: boolean }>(`${base}/sources`);
    if (!alive.current || version !== sourceVersion.current) return;
    setSources(value.items); setSearchConfigured(value.search_available);
  }, [base]);
  useEffect(() => {
    alive.current = true;
    void load().catch((failure) => { if (alive.current) { if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) clearAuthority(failure.message); setError(failure.message); } });
    return () => { alive.current = false; operation.current += 1; sourceVersion.current += 1; };
  }, [load, clearAuthority]);
  const execute = async (work: (current: () => boolean) => Promise<void>, readingBody = false) => {
    if (locked.current) return;
    locked.current = true;
    const version = ++operation.current;
    const current = () => alive.current && version === operation.current;
    setBusy(true); setReading(readingBody); setError(null); setNotice(null);
    try { await work(current); }
    catch (failure) {
      if (!current()) return;
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) {
        clearAuthority(failure.message);
      }
      setError(failure instanceof Error ? failure.message : "来源操作失败");
    } finally { if (current()) { locked.current = false; setBusy(false); setReading(false); } }
  };
  const readBody = (id: string) => execute(async current => {
    setBody(null);
    const value = await request<EvidenceContent>(`${base}/evidence/${id}/content`);
    if (!current()) return;
    if (value.snapshot_id !== id) throw new Error("正文与请求快照不一致，请核对来源后重试");
    setBody(value);
  }, true);
  const cancelReading = () => {
    operation.current += 1; locked.current = false;
    setReading(false); setBusy(false); setBody(null); setError(null);
  };
  const refreshAuthority = () => execute(async current => {
    await load();
    if (!current()) return;
    await refresh();
    if (current()) setDenied(false);
  });
  if (denied) return <details open id="research-collection" className="rounded-lg border p-4"><summary className="cursor-pointer font-semibold">研究来源与公开页面采集</summary><div className="mt-3 space-y-3">{error && <p role="alert" className="text-sm text-destructive">{error}</p>}<p className="text-sm text-muted-foreground">当前来源权限需重新核对，已隐藏原资料。</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void refreshAuthority()}>重新核对来源权限</Button></div></details>;
  const source = sources.find((item) => item.id === sourceId);
  const shown = evidence.filter((item) => `${item.name} ${item.url ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  return <details open={showSubscription || undefined} id="research-collection" className="rounded-lg border p-4"><summary className="cursor-pointer font-semibold">研究来源与公开页面采集</summary>
    <div className="mt-3 space-y-4">
      <p className="text-sm text-muted-foreground">公开来源和快照保存到租户共享证据库。请选择符合来源许可的用途；可为指定公开页面登记订阅；AI 自主研究尚未接入。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void refreshAuthority()}>刷新来源与快照</Button>
      <ResearchSearch key={`search:${lineId ?? "market"}`} base={base} lineId={lineId} configured={searchConfigured} canSearch={workspace.space.lifecycle !== "archived"} onPick={(url, title) => {
        setSuggestedUrl(url); setSuggestedName(title); const origin = new URL(url).origin;
        const matching = sources.find((item) => { try { return item.status === "active" && new URL(item.base_url).origin === origin; } catch { return false; } });
        if (matching) { setSourceId(matching.id); setNotice("候选页面已填入采集表单，请确认来源许可后采集。"); }
        else { setSourceId(""); setRegisterOpen(true); setNotice(workspace.can_manage_sources ? "请先登记此页面的来源和许可依据，再采集。" : "该页面的来源尚未登记，请空间管理成员补充来源许可。"); }
      }} />
      {workspace.can_manage_sources && <details className="rounded-md border p-3" open={registerOpen} onToggle={(event) => setRegisterOpen(event.currentTarget.open)}><summary className="cursor-pointer text-sm">登记公开来源</summary><form key={suggestedUrl} className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(event) => {
        event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
        void execute(async current => { const created = await request<ResearchSource>(`${base}/sources`, "POST", { name: String(form.get("name")).trim(), base_url: String(form.get("url")).trim(), allowed_use: form.get("use"), license_note: String(form.get("license")).trim(), retention_policy: form.get("retention"), trust_tier: form.get("trust") }); if (!current()) return; setSources(current => [created, ...current.filter(item => item.id !== created.id)]); setSourceId(created.id); setRegisterOpen(false); formElement.reset(); setNotice("来源已登记，可以采集该站点的公开页面。"); await load(); });
      }}>
        <label className="text-sm">来源名称<input name="name" required maxLength={256} defaultValue={suggestedName.slice(0, 256)} className={field} /></label><label className="text-sm">来源地址<input name="url" type="url" required maxLength={1024} placeholder="https://example.com" defaultValue={suggestedUrl ? new URL(suggestedUrl).origin : ""} className={field} /></label>
        <label className="text-sm">许可用途<select name="use" className={field}>{Object.entries(uses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="text-sm">许可依据<textarea name="license" required maxLength={2048} className={field} placeholder="记录来源声明或已获许可的依据" /></label>
        <label className="text-sm">来源类别<select name="trust" className={field}><option value="unknown">待确认</option><option value="official">官方</option><option value="public">公开资料</option><option value="community">社区</option></select></label><label className="text-sm">保留政策<select name="retention" className={field}><option value="standard">标准</option><option value="minimal">最短</option><option value="extended">延长</option></select></label>
        <Button disabled={busy} className="justify-self-start">登记来源</Button>
      </form></details>}
      {canCollect && <form className="grid gap-3 rounded-md border p-3 sm:grid-cols-2" onSubmit={(event) => {
        event.preventDefault(); const form = new FormData(event.currentTarget);
        void execute(async current => {
          setBody(null); setCaptured(null);
          const value = await request<{ snapshot: { id: string }; reused_existing: boolean; message: string }>(`${base}/capture`, "POST", { source_id: sourceId, url: String(form.get("url")).trim(), product_line_id: lineId, freshness_days: form.get("days") ? Number(form.get("days")) : null });
          if (!current()) return;
          setCaptured({ id: value.snapshot.id, message: value.reused_existing ? "相同来源、版本和正文已存在，已复用原快照。" : value.message });
          const [updated, content] = await Promise.allSettled([refresh(), request<EvidenceContent>(`${base}/evidence/${value.snapshot.id}/content`)]);
          if (!current()) return;
          for (const result of [updated, content]) if (result.status === "rejected" && result.reason instanceof ProductRequestError && [401, 403].includes(result.reason.status)) throw result.reason;
          if (content.status === "fulfilled" && content.value.snapshot_id === value.snapshot.id) setBody(content.value);
          const warnings = [updated.status === "rejected" ? "快照列表刷新失败，可刷新来源与快照" : "", content.status === "rejected" ? "正文暂未读到，可读取已保存快照，无需重新采集" : content.value.snapshot_id !== value.snapshot.id ? "正文与保存快照不一致，请核对来源后重试" : ""].filter(Boolean);
          if (warnings.length) setError(`快照已保存。${warnings.join("；")}。`);
        });
      }}>
        <h4 className="font-medium sm:col-span-2">采集一个公开页面</h4><label className="text-sm">来源<select required value={sourceId} onChange={(event) => { setSourceId(event.target.value); setSuggestedUrl(""); }} className={field}><option value="">请选择来源</option>{sources.filter((item) => item.status === "active").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="text-sm">页面地址<input key={`${sourceId}:${suggestedUrl}`} name="url" type="url" required maxLength={1024} defaultValue={suggestedUrl || source?.base_url || ""} className={field} /></label>
        <label className="text-sm">建议复查间隔（天，可留空）<input name="days" type="number" min={1} max={366} className={field} /></label>{source && <p className="self-center break-all text-xs text-muted-foreground">{uses[source.allowed_use]} · {source.license_note} · {source.base_url}</p>}
        <div className="flex items-center gap-2 sm:col-span-2"><Button disabled={busy || !sourceId}>{busy ? "正在办理…" : "采集并保存快照"}</Button><span className="text-xs text-muted-foreground">仅公开文本页面，单页最多2 MiB；需要登录的页面不可采集。</span></div>
      </form>}
      {captured && <section aria-label="本次采集回执" className="space-y-2 rounded-md border p-3"><p role="status" className="text-sm">{captured.message}</p><p className="break-all text-xs text-muted-foreground">已保存快照：{captured.id}</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void readBody(captured.id)}>读取已保存快照</Button></section>}
      <details><summary className="cursor-pointer text-sm">共享来源负责人及移交历史</summary><p className="mt-2 text-xs text-muted-foreground">来源负责人服务于整个租户；各空间订阅的采集负责人独立办理。</p><ul className="mt-2 space-y-2 text-sm">{sources.map(s => <li key={s.id}><a className="underline" href={`/knowledge?source_owner_id=${s.id}`}>{s.name} · 来源责任与历史</a></li>)}</ul></details>
      <ResearchSubscriptions onResponsibilityLock={onResponsibilityLock} key={`subscriptions:${lineId ?? "market"}`} base={base} lineId={lineId} sources={sources} sourceId={sourceId} suggestedUrl={suggestedUrl} canCreate={canCollect} inspect={(id) => void readBody(id)} />
      <label className="block text-sm">查找已有快照<input value={filter} onChange={(event) => setFilter(event.target.value)} className={field} placeholder="来源名称或页面地址" /></label>
      <ul className="max-h-80 space-y-2 overflow-y-auto">{shown.map((item) => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"><div className="min-w-0"><p className="text-sm font-medium">{item.name}</p><p className="break-all text-xs text-muted-foreground">{new Date(item.captured_at).toLocaleString()} · {item.url}{item.is_stale ? " · 需复查" : ""}{item.superseded ? " · 有新版" : ""}{item.has_conflict ? " · 有冲突" : ""}</p></div><Button size="sm" variant="outline" disabled={busy} onClick={() => void readBody(item.id)}>查看快照正文</Button></li>)}</ul>
      {reading && <div className="flex items-center gap-2"><p role="status" className="text-sm">正在读取快照正文…</p><Button size="sm" variant="ghost" onClick={cancelReading}>取消读取正文</Button></div>}
      {body && <section className="space-y-2 rounded-md border p-3"><div className="flex justify-between gap-2"><h4 className="text-sm font-medium">已保存的原始正文 · {body.taint === "untrusted_external" ? "外部资料，未经验证" : body.taint}</h4><Button size="sm" variant="ghost" onClick={() => setBody(null)}>关闭正文</Button></div><p className="break-all text-xs text-muted-foreground">快照 {body.snapshot_id} · {body.byte_size} 字节 · 摘要 {body.content_digest}</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{body.content}</pre></section>}
    </div>
  </details>;
}
