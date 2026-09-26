"use client";

import { useState } from "react";
import { EmailExtractionNotice } from "@/components/ai/email-extraction-notice";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
export function EmailDocumentText({ base }: { base: string }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null), [after, setAfter] = useState(0), [previous, setPrevious] = useState<number[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(cursor = 0, direction: "next" | "previous" | "start" = "start") {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`${base}/email-text?after_ordinal=${cursor}`, { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.fragments)) throw new Error("邮件原文暂不可读取，请稍后重试");
      setData(value); setAfter(cursor); setPrevious(old => direction === "next" ? [...old, after] : direction === "previous" ? old.slice(0, -1) : []);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  return <details className="space-y-3 rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}><summary className="cursor-pointer text-sm font-medium">读取邮件头、正文及未读范围</summary>
    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void load()}>重新读取原文</Button>
    {data && <><EmailExtractionNotice metadata={isRecord(data.document) ? data.document.extraction_metadata : null}/>{Array.isArray(data.fragments) && data.fragments.filter(isRecord).map(fragment => <section key={String(fragment.ordinal)} className="space-y-1"><p className="text-xs font-medium">{String(fragment.locator)}</p><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">{String(fragment.text)}</pre></section>)}<div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || !previous.length} onClick={() => void load(previous[previous.length - 1], "previous")}>上一组原文</Button><Button type="button" size="sm" variant="outline" disabled={busy || data.next_after == null} onClick={() => void load(Number(data.next_after), "next")}>下一组原文</Button></div></>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </details>;
}
