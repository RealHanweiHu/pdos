"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const txt = (value: unknown) => value == null ? "" : String(value);
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const active = (item: Row) => ["queued", "running"].includes(txt(item.status));
const status: Record<string, string> = { queued: "等待识别", running: "正在识别", succeeded: "已提取 · 待核对", failed: "未完成", cancelled: "已停止" };

async function request(path: string, body?: unknown, signal?: AbortSignal): Promise<Row> {
  const response = await fetch(path, { cache: "no-store", signal, ...(body !== undefined ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : {}) });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(txt(obj(obj(value).detail).message) || "识别记录暂不可读取");
  return value;
}

export function CaptureRecognition({ path, media, selectedId, editable, disabled = false, adopt }: {
  path: string; media: string; selectedId?: string; editable: boolean; disabled?: boolean;
  adopt?: (id: string, text: string) => void;
}) {
  const photo = media.startsWith("image/"), kind = photo ? "ocr" : "speech";
  const [language, setLanguage] = useState(photo ? "zh" : "auto");
  const [items, setItems] = useState<Row[]>([]), [available, setAvailable] = useState(false);
  const [viewed, setViewed] = useState(selectedId ?? ""), [receipt, setReceipt] = useState<Row | null>(null);
  const [revision, setRevision] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false), [showAllParts, setShowAllParts] = useState(false);
  const requestId = useRef<{ id: string; language: string } | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const listPath = `${path}/recognitions`;
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const result = await request(listPath, undefined, controller.signal);
        if (controller.signal.aborted) return;
        const next = rows(result.items); setItems(next); setAvailable(obj(result.available)[kind] === true);
        setLoaded(true); setError("");
        if (next.some(active)) timer = setTimeout(() => void load(), 3000);
      } catch (failure) {
        if (!controller.signal.aborted) { setLoaded(true); setError(failure instanceof Error ? failure.message : "读取失败"); }
      }
    }
    void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [listPath, kind, revision]);
  const chosen = viewed || selectedId || txt(items[0]?.id);
  const chosenStatus = txt(items.find(item => item.id === chosen)?.status);
  useEffect(() => {
    if (!chosen) return;
    const controller = new AbortController();
    void request(`${listPath}/${chosen}`, undefined, controller.signal).then(value => {
      if (!controller.signal.aborted) setReceipt(value);
    }).catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "读取失败"); });
    return () => controller.abort();
  }, [listPath, chosen, chosenStatus, revision]);
  async function act(work: () => Promise<void>) {
    setBusy(true); setError("");
    try { await work(); }
    catch (failure) { if (mounted.current) setError(failure instanceof Error ? failure.message : "操作失败"); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function start() {
    if (!requestId.current || requestId.current.language !== language) requestId.current = { id: crypto.randomUUID(), language };
    const value = await request(listPath, { request_id: requestId.current.id, language });
    requestId.current = null;
    if (mounted.current) { setViewed(txt(value.id)); setReceipt(value); setRevision(v => v + 1); }
  }
  const current = receipt?.id === chosen ? receipt : null;
  const result = obj(current?.result), parts = rows(result.parts);
  const shownParts = showAllParts ? parts : parts.filter(part => part.uncertain);
  return <section className="space-y-3 rounded-md border p-3">
    <h4 className="text-sm font-medium">{photo ? "照片文字识别" : "录音转写"}</h4>
    <p className="text-xs text-muted-foreground">识别只提取原件文字，可能错漏。编号、单位、测试结论和实际时间须人工核对，不会自动关联样机或登记业务。</p>
    {editable && <div className="flex flex-wrap items-end gap-2">
      <label className="text-sm">原件语言<select value={language} disabled={busy || disabled} onChange={e => setLanguage(e.target.value)} className="ml-2 rounded-md border bg-background p-2">
        {!photo && <option value="auto">自动检测</option>}<option value="zh">{photo ? "中文与英文" : "中文"}</option><option value="en">英文</option>
      </select></label>
      <Button type="button" size="sm" variant="outline" disabled={busy || disabled || !available || items.some(active)} onClick={() => void act(start)}>{items.length ? "重新识别并保留旧结果" : "开始识别"}</Button>
    </div>}
    {!loaded && <p role="status" className="text-sm">正在读取识别状态…</p>}
    {loaded && editable && !available && <p className="text-sm text-muted-foreground">本地识别尚未启用或缺少引擎、固定模型，可继续人工填写。</p>}
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setRevision(v => v + 1)}>刷新识别状态</Button>
      {editable && items.filter(active).map(item => <Button key={txt(item.id)} type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => void act(async () => {
        await request(`${listPath}/${txt(item.id)}/cancel`, {}); if (mounted.current) setRevision(v => v + 1);
      })}>停止{item.status === "queued" ? "等待" : "识别"}</Button>)}
    </div>
    {items.length > 0 && <label className="block text-sm">最近20次识别记录<select value={chosen} onChange={e => { setViewed(e.target.value); setShowAllParts(false); }} className="mt-1 w-full rounded-md border bg-background p-2">
      {chosen && !items.some(item => item.id === chosen) && <option value={chosen}>草稿已关联的识别结果</option>}
      {items.map(item => <option key={txt(item.id)} value={txt(item.id)}>{new Date(txt(item.created_at)).toLocaleString("zh-CN")} · {status[txt(item.status)]}{item.id === selectedId ? " · 当前草稿来源" : ""}</option>)}
    </select></label>}
    {current && <div className="space-y-2 text-sm"><p role="status">{status[txt(current.status)]} {txt(current.message)}</p>
      {current.status === "succeeded" && <>
        <p className="whitespace-pre-wrap break-words rounded-md bg-muted/30 p-3">{txt(result.text) || "未识别出文字，请对照原件人工填写。"}</p>
        {Array.isArray(result.warnings) && result.warnings.map((warning, i) => <p key={i} className="text-xs text-muted-foreground">{txt(warning)}</p>)}
        <details><summary className="cursor-pointer">{photo ? "照片词语位置" : "录音时间段"}与不确定提示（{parts.filter(p => p.uncertain).length}处）</summary>
          <p className="mt-2 text-xs text-muted-foreground">{photo ? "位置以按拍摄方向转正的照片像素计算：左、上、宽、高。" : "时间从原录音起点计算，请打开上方原件按时间回听。"}未标注也不代表正确。</p>
          <label className="my-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={showAllParts} onChange={e => setShowAllParts(e.target.checked)}/>显示全部片段</label>
          <div className="max-h-64 space-y-2 overflow-auto">{shownParts.map((part, i) => <div key={i} className="break-words rounded border p-2"><span className="text-xs text-muted-foreground">{part.uncertain ? "待重点核对 · " : ""}{photo ? `位置 ${Array.isArray(part.box) ? part.box.join(", ") : "未知"} · 识别分 ${Number(part.confidence).toFixed(1)}` : `${Number(part.start_seconds).toFixed(1)}–${Number(part.end_seconds).toFixed(1)} 秒`}</span><p>{txt(part.text)}</p></div>)}</div>
        </details>
        <p className="text-xs text-muted-foreground">来源：{txt(result.engine)}{result.duration_seconds != null ? ` · 录音 ${Number(result.duration_seconds).toFixed(1)} 秒` : ""}</p>
        {editable && adopt && current.id !== selectedId && <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy || disabled || !txt(result.text)} onClick={() => adopt(txt(current.id), txt(result.text))}>追加到草稿说明并核对</Button>
          <Button type="button" size="sm" variant="ghost" disabled={busy || disabled} onClick={() => adopt(txt(current.id), "")}>仅关联来源，手动整理</Button>
        </div>}
      </>}
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
