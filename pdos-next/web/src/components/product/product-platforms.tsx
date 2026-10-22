"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowsClockwise, LinkSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { DefinitionApi } from "@/lib/product-view";
import type { Variant, VariantList } from "@/lib/variant-view";
import type { Platform, PlatformCommand, PlatformList, PlatformPreview } from "@/lib/platform-view";

type Props = { product: { id: string; revision: number }; categoryId: string; principalId: string; api: DefinitionApi; onSaved: () => void | Promise<void> };
type Editor = { mode: "existing" | "new"; platformId: string; variantId: string; code: string; name: string; description: string; compatibility: string; platformVersion: string; reason: string };
const blank: Editor = { mode: "existing", platformId: "", variantId: "", code: "", name: "", description: "", compatibility: "", platformVersion: "", reason: "" };
const targetQuery = (variantId: string) => variantId ? `&variant_id=${encodeURIComponent(variantId)}` : "";
const message = (failure: unknown) => (failure as Error).message || "读取失败，请刷新后重试。";

export function ProductPlatforms(props: Props) {
  return <PlatformsPanel key={`${props.principalId}:${props.categoryId}:${props.product.id}`} {...props} />;
}

function PlatformsPanel({ product, categoryId, principalId, api, onSaved }: Props) {
  const storageKey = `pdos-next:platforms:${principalId}:${categoryId}:${product.id}`;
  const [editor, setEditor] = useState<Editor>(blank);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [linked, setLinked] = useState<Platform[]>([]);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [variantMore, setVariantMore] = useState(false);
  const [platformCursor, setPlatformCursor] = useState<string | null>(null);
  const [linkCursor, setLinkCursor] = useState<string | null>(null);
  const [historyState, setHistoryState] = useState<Record<string, "loading" | "loaded">>({});
  const [historyGeneration, setHistoryGeneration] = useState(0);
  const historyRequests = useRef(new Set<string>());
  const [pending, setPending] = useState<PlatformCommand | null>(null);
  const [preview, setPreview] = useState<PlatformPreview | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const alive = useRef(true), lock = useRef(false), readEpoch = useRef(0);
  const dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLElement | null>(null);
  const editable = ready && !busy && !pending;

  function remember(next: Editor, waiting: PlatformCommand | null) {
    try { localStorage.setItem(storageKey, JSON.stringify({ editor: next, pending: waiting })); } catch { /* In-memory original request remains available. */ }
  }
  function edit(next: Editor) { setEditor(next); remember(next, pending); }
  const failedRead = useCallback((failure: unknown) => {
    if (!alive.current) return;
    setError(message(failure));
    setLinked([]); setPlatforms([]); setVariants([]); setPlatformCursor(null); setLinkCursor(null);
    if ((failure as { status?: number }).status === 403) {
      try { localStorage.removeItem(storageKey); } catch { /* Optional storage. */ }
      setEditor(blank); setPending(null); setPreview(null); dialog.current?.close();
    }
  }, [storageKey]);
  const refresh = useCallback(async (variantId: string) => {
    const epoch = ++readEpoch.current;
    setLoading(true);
    try {
      const [list, links, derived] = await Promise.all([
        api<PlatformList>("v1/platforms?page_size=200"),
        api<PlatformList>(`v1/products/${product.id}/platform-links?page_size=200${targetQuery(variantId)}`),
        api<VariantList>(`v1/products/${product.id}/variants`),
      ]);
      if (!alive.current || epoch !== readEpoch.current) return;
      setPlatforms(list.items); setPlatformCursor(list.next_cursor);
      setLinked(links.items); setLinkCursor(links.next_cursor);
      setHistoryState({}); historyRequests.current.clear();
      setHistoryGeneration(value => value + 1);
      setVariants(derived.items); setVariantMore(derived.has_more); setError("");
    } catch (failure) { if (epoch === readEpoch.current) failedRead(failure); }
    finally { if (alive.current && epoch === readEpoch.current) setLoading(false); }
  }, [api, product.id, failedRead]);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null");
        if (saved?.editor && Object.keys(blank).every(key => typeof saved.editor[key] === "string")) setEditor(saved.editor);
        const request = saved?.pending as PlatformCommand | undefined;
        if (request?.operation === "platform.link.create" && request.product_id === product.id && request.payload?.product_id === product.id && typeof request.idempotency_key === "string") setPending(request);
      } catch { /* Optional local draft. */ }
      setReady(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- This is a request generation, not a DOM ref.
    return () => { alive.current = false; readEpoch.current++; };
  }, [storageKey, product.id]);
  useEffect(() => { if (ready) void Promise.resolve().then(() => { if (alive.current) return refresh(editor.variantId); }); }, [ready, refresh, editor.variantId]);
  useEffect(() => { if (preview) dialog.current?.showModal(); }, [preview]);
  function closePreview() { dialog.current?.close(); setPreview(null); trigger.current?.focus(); }

  async function prepare(action: "attach" | "detach", element: HTMLElement) {
    if (lock.current || pending) return;
    if (!editor.reason.trim()) { setError("请填写本次关联或解除的原因。"); return; }
    const selected = platforms.find(row => row.id === editor.platformId);
    if (editor.mode === "existing" && !selected) { setError("请选择实际平台。"); return; }
    if (editor.mode === "new" && (!editor.code.trim() || !editor.name.trim())) { setError("请填写新平台编号与名称。"); return; }
    lock.current = true; setBusy(true); setError(""); setNotice(""); trigger.current = element;
    try {
      let version = 0;
      if (selected && editor.mode === "existing") {
        const actual = await api<PlatformList>(`v1/platforms?product_id=${product.id}&code=${encodeURIComponent(selected.code)}${targetQuery(editor.variantId)}`);
        version = actual.items[0]?.links[0]?.current_version ?? 0;
      }
      const request: PlatformCommand = {
        command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "platform.link.create",
        product_id: product.id, expected_revision: product.revision, source_read_set: [],
        payload: { product_id: product.id, variant_id: editor.variantId || null,
          platform_id: editor.mode === "existing" ? editor.platformId : null,
          new_platform: editor.mode === "new" ? { code: editor.code.trim(), name: editor.name.trim(), description: editor.description.trim() } : null,
          action, compatibility: editor.compatibility.trim() || null, platform_version: editor.platformVersion.trim() || null,
          reason: editor.reason.trim(), expected_link_version: version },
      };
      const result = await api<PlatformPreview>("v1/commands/preview", request);
      if (result.command?.product_id !== product.id || result.command.operation !== "platform.link.create" || !result.command.payload.confirmation_token || !result.review?.platform) throw new Error("确认材料不完整，请刷新后重新核对。");
      if (alive.current) setPreview(result);
    } catch (failure) { if (alive.current) { setError(message(failure)); if ((failure as { status?: number }).status === 403) failedRead(failure); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function submit(request: PlatformCommand) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); setPending(request); remember(editor, request);
    let saved = false;
    try {
      const receipt = await api<{ id: string; subject_type: string; result: { platform_id: string; link_version: number } }>("v1/commands", request);
      if (!receipt.id || receipt.subject_type !== "platform_link" || !receipt.result?.platform_id) throw new Error("保存结果尚未确认，请按原请求重试。");
      if (!alive.current) return;
      saved = true; setPending(null); closePreview();
      const next = { ...editor, mode: "existing" as const, platformId: receipt.result.platform_id, reason: "" };
      setEditor(next); remember(next, null);
      setNotice(`平台${request.payload.action === "detach" ? "解除" : "关联"}已保存 · 关联版本 v${receipt.result.link_version}，历史可查。`);
      await refresh(editor.variantId); await onSaved();
    } catch (failure) {
      if (!alive.current) return;
      const status = (failure as { status?: number }).status;
      closePreview();
      if (status && status < 500) { setPending(null); remember(editor, null); }
      if (status === 403) failedRead(failure);
      else setError(saved ? `保存成功，最新读取失败，可刷新。${message(failure)}` : message(failure));
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function more(kind: "platforms" | "links") {
    if (lock.current) return;
    const cursor = kind === "platforms" ? platformCursor : linkCursor;
    if (!cursor) return;
    const epoch = readEpoch.current;
    lock.current = true; setBusy(true);
    try {
      const path = kind === "platforms" ? "v1/platforms?page_size=200" : `v1/products/${product.id}/platform-links?page_size=200${targetQuery(editor.variantId)}`;
      const result = await api<PlatformList>(`${path}&cursor=${cursor}`);
      if (!alive.current || epoch !== readEpoch.current) return;
      if (kind === "platforms") { setPlatforms(rows => [...rows, ...result.items]); setPlatformCursor(result.next_cursor); }
      else { setLinked(rows => [...rows, ...result.items]); setLinkCursor(result.next_cursor); }
    } catch (failure) { if (epoch === readEpoch.current) failedRead(failure); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function loadHistory(platform: Platform) {
    if (historyState[platform.id] === "loaded" || historyRequests.current.has(platform.id)) return;
    const epoch = readEpoch.current;
    historyRequests.current.add(platform.id); setHistoryState(rows => ({ ...rows, [platform.id]: "loading" }));
    try {
      const result = await api<PlatformList>(`v1/platforms?product_id=${product.id}&code=${encodeURIComponent(platform.code)}&include_history=true${targetQuery(editor.variantId)}`);
      if (!alive.current || epoch !== readEpoch.current) return;
      const actual = result.items.find(row => row.id === platform.id);
      if (!actual?.links.length) throw new Error("此关联的读取范围已变化，请刷新后核对。");
      setLinked(rows => rows.map(row => row.id === actual.id ? actual : row));
      setHistoryState(rows => ({ ...rows, [platform.id]: "loaded" }));
    } catch (failure) { if (epoch === readEpoch.current) failedRead(failure); }
    finally { if (epoch === readEpoch.current) historyRequests.current.delete(platform.id); }
  }
  const scope = variants.find(row => row.id === editor.variantId);
  const privacy = scope ? (scope.visibility === "category" ? "品类成员可见" : "仅该变体原有受众可见") : "随型号原有权限展示";
  return <section className="panel mt-6 min-w-0" aria-labelledby="platforms-heading">
    <div className="mb-3 flex items-center gap-2"><LinkSimple className="shrink-0 text-primary" /><h2 id="platforms-heading" className="font-semibold">平台关联</h2><Button variant="ghost" size="sm" className="ml-auto" disabled={!editable || loading} onClick={() => void refresh(editor.variantId)}><ArrowsClockwise />刷新</Button></div>
    <p className="subtle mb-5">记录复用哪个平台、适用范围与平台版本。关联本身不证明兼容性；未填写的范围和版本保留为待确认。</p>
    {error && <p role="alert" className="mb-4 break-words text-destructive">{error}</p>}
    {notice && <p role="status" className="mb-4">{notice}</p>}
    {pending && <div className="mb-5 rounded-lg border border-border p-4"><p>保存结果尚未确认。请使用原请求核对，避免重复新建平台。</p><Button className="mt-3" disabled={busy} onClick={() => void submit(pending)}>按原请求重试</Button></div>}
    <label>关联对象<select value={editor.variantId} disabled={!editable || loading} onChange={event => edit({ ...editor, variantId: event.target.value })}><option value="">当前型号</option>{variants.map(row => <option key={row.id} value={row.id}>{row.name} · {row.visibility === "category" ? "品类成员可见" : "限原有受众"}</option>)}</select></label>
    <p className="subtle mb-4">{privacy}{variantMore && "；当前仅列出首批可见变体。"}</p>
    <div className="grid gap-x-5 lg:grid-cols-2"><div>
      <label>平台来源<select value={editor.mode} disabled={!editable} onChange={event => edit({ ...editor, mode: event.target.value as Editor["mode"] })}><option value="existing">选择已有平台</option><option value="new">新建平台并关联</option></select></label>
      {editor.mode === "existing" ? <><label>选择平台<select value={editor.platformId} disabled={!editable || loading} onChange={event => edit({ ...editor, platformId: event.target.value })}><option value="">请选择</option>{platforms.map(row => <option key={row.id} value={row.id}>{row.code} · {row.name}</option>)}</select></label>{platformCursor && <Button variant="outline" size="sm" disabled={!editable} onClick={() => void more("platforms")}>加载更多平台</Button>}</> : <>
        <p className="subtle mb-3">编号、名称、通用说明供租户各品类共用，请勿填写客户身份或专属要求。</p>
        <label>新平台编号<input disabled={!editable} value={editor.code} onChange={event => edit({ ...editor, code: event.target.value })} /></label>
        <label>新平台名称<input disabled={!editable} value={editor.name} onChange={event => edit({ ...editor, name: event.target.value })} /></label>
        <label>平台通用说明<textarea rows={2} disabled={!editable} value={editor.description} onChange={event => edit({ ...editor, description: event.target.value })} /></label>
      </>}
    </div><div>
      <label>兼容范围<textarea rows={3} placeholder="尚未确认可留空；客户专属范围请选择对应变体" disabled={!editable} value={editor.compatibility} onChange={event => edit({ ...editor, compatibility: event.target.value })} /></label>
      <label>平台版本<input placeholder="未确定可留空" disabled={!editable} value={editor.platformVersion} onChange={event => edit({ ...editor, platformVersion: event.target.value })} /></label>
      <label>关联或解除原因<textarea rows={2} disabled={!editable} value={editor.reason} onChange={event => edit({ ...editor, reason: event.target.value })} /></label>
    </div></div>
    <div className="mb-6 flex flex-wrap gap-2"><Button disabled={!editable || loading} onClick={event => void prepare("attach", event.currentTarget)}>核对并关联</Button>{editor.mode === "existing" && <Button variant="outline" disabled={!editable || loading} onClick={event => void prepare("detach", event.currentTarget)}>核对并解除</Button>}</div>
    <h3 className="mb-3 font-medium">当前对象的关联与历史</h3>
    {loading ? <p role="status" className="subtle">正在读取平台记录…</p> : linked.length === 0 ? <p className="subtle">当前对象还没有可见的平台关联记录。</p> : <div className="space-y-3">{linked.map(platform => {
      const latest = platform.links.find(link => link.version === link.current_version);
      if (!latest) return null;
      return <article key={platform.id} className="min-w-0 rounded-lg border border-border p-4 break-words">
        <div className="mb-2 flex flex-wrap items-center gap-2"><span className="font-medium">{platform.code} · {platform.name}</span><span className="subtle">{latest.attached ? "已关联" : "已解除"} · v{latest.version}</span></div>
        <p>兼容范围：{latest.compatibility ?? "待确认"}</p><p>平台版本：{latest.platform_version ?? "待确认"}</p><p className="subtle mt-2">{latest.reason}</p>
        <details key={historyGeneration} className="mt-3" onToggle={event => { if (event.currentTarget.open) void loadHistory(platform); }}><summary className="cursor-pointer">查看版本记录{historyState[platform.id] === "loaded" && ` · ${platform.links.length} 条`}</summary>{historyState[platform.id] === "loaded" ? <ol className="mt-3 space-y-3">{platform.links.map(link => <li key={link.id} className="border-l border-border pl-3"><p>v{link.version} · {link.action === "attach" ? "关联" : "解除"} · {new Date(link.provenance.created_at).toLocaleString("zh-CN")}</p><p>兼容范围：{link.compatibility ?? "待确认"} · 平台版本：{link.platform_version ?? "待确认"}</p><p className="subtle">{link.reason} · {link.provenance.origin === "ai_draft" ? "小Pai起草，经本人确认" : "人工确认"}</p></li>)}</ol> : <p role="status" className="subtle mt-3">正在读取版本记录…</p>}</details>
      </article>;
    })}</div>}
    {linkCursor && <Button variant="outline" className="mt-4" disabled={!editable} onClick={() => void more("links")}>加载更多关联</Button>}
    <dialog ref={dialog} className="max-h-[90vh] overflow-auto" aria-labelledby="platform-confirm-heading" onCancel={event => { if (busy) event.preventDefault(); else closePreview(); }}>
      {preview && <><h3 id="platform-confirm-heading" className="mb-4 text-lg font-semibold">确认{preview.command.payload.action === "detach" ? "解除" : "关联"}平台</h3><p>{preview.review.product_name}{preview.review.variant_name && ` / ${preview.review.variant_name}`}</p><p className="mt-2 font-medium">{preview.review.platform.code} · {preview.review.platform.name}</p>{preview.command.payload.new_platform && <p className="subtle mt-2">将同时新建租户共用平台。通用说明：{preview.review.platform.description || "未填写"}</p>}<p className="mt-3">兼容范围：{preview.command.payload.compatibility ?? "待确认"}</p><p>平台版本：{preview.command.payload.platform_version ?? "待确认"}</p><p>原因：{preview.command.payload.reason}</p><p className="subtle mt-3">{preview.review.effect}</p><p className="subtle mt-2">关联 v{preview.review.next_link_version} · 确认有效至 {new Date(preview.expires_at).toLocaleTimeString("zh-CN")}</p><div className="mt-5 flex flex-wrap gap-2"><Button disabled={busy || !!pending} onClick={() => void submit(preview.command)}>确认保存</Button><Button variant="outline" disabled={busy} onClick={closePreview}>返回修改</Button></div></>}
    </dialog>
  </section>;
}
