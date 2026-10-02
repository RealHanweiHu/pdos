"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProductRequestError, request, type Evidence, type EvidenceContent, type SourceRef } from "./product-work-api";

const referenceKey = (ref: SourceRef) => JSON.stringify([ref.tenant_id, ref.project_id ?? null, ref.kind, ref.ref_id, ref.as_of, ref.digest]);

type Props = { base: string; references: SourceRef[]; evidence: Evidence[]; onAuthorityLost?: (message: string) => void };
export function SourceCitations(props: Props) {
  const identities = props.references.map(referenceKey);
  return <SourceCitationsPanel key={JSON.stringify([props.base, identities.sort()])} {...props}/>;
}
function SourceCitationsPanel({ base, references: incomingReferences, onAuthorityLost }: Props) {
  const [references] = useState(() => incomingReferences.map(ref => ({ ...ref })));
  const authorityLost = useRef(onAuthorityLost);
  useEffect(() => { authorityLost.current = onAuthorityLost; }, [onAuthorityLost]);
  const [content, setContent] = useState<EvidenceContent | null>(null), [error, setError] = useState("");
  const [deniedRef, setDeniedRef] = useState<SourceRef | null>(null);
  const [reading, setReading] = useState(false);
  const [verified, setVerified] = useState<Record<string, Evidence>>({});
  const revision = useRef(0);
  const readLock = useRef(false);
  useEffect(() => () => { revision.current += 1; }, [base]);
  useEffect(() => {
    let active = true;
    const current = revision.current;
    async function loadMetadata() {
      const resolved: Record<string, Evidence> = {};
      try {
        for (let offset = 0; offset < references.length; offset += 100) {
          const batch = references.slice(offset, offset + 100);
          const query = new URLSearchParams(batch.map(ref => ["snapshot_ids", ref.ref_id]));
          const result = await request<{ items: Evidence[] }>(`${base}/evidence?${query}`);
          if (!active || current !== revision.current) return;
          for (const ref of batch) {
            const source = result.items?.find(item => item.id === ref.ref_id && referenceKey(item.reference) === referenceKey(ref));
            if (source) resolved[referenceKey(ref)] = source;
          }
        }
        if (active && current === revision.current) setVerified(resolved);
      } catch (failure) {
        if (!active || current !== revision.current) return;
        if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) {
          revision.current += 1; readLock.current = false; setReading(false);
          setDeniedRef(references[0] ?? null); setContent(null); setVerified({});
          authorityLost.current?.(failure.message);
        }
        setError(failure instanceof Error ? failure.message : "来源质量尚未核对");
      }
    }
    void loadMetadata();
    return () => { active = false; };
  }, [base, references]);
  async function read(ref: SourceRef) {
    if (readLock.current) return;
    readLock.current = true;
    const current = ++revision.current;
    setReading(true); setContent(null); setError("");
    setVerified(previous => { const next = { ...previous }; delete next[referenceKey(ref)]; return next; });
    try {
      const value = await request<EvidenceContent>(`${base}/evidence/${ref.ref_id}/content`);
      if (current !== revision.current) return;
      if (value.snapshot_id !== ref.ref_id || value.content_digest !== ref.digest) throw new Error("正文与此条引用的原版本不一致，请核对来源后重试");
      setContent(value); setDeniedRef(null);
      const metadata = await request<{ items: Evidence[] }>(`${base}/evidence?snapshot_ids=${encodeURIComponent(ref.ref_id)}`);
      if (current !== revision.current) return;
      const source = metadata.items?.find(item => item.id === ref.ref_id && referenceKey(item.reference) === referenceKey(ref));
      if (!source) throw new Error("此原快照的来源质量尚未核对，请重试读取");
      setVerified(previous => ({ ...previous, [referenceKey(ref)]: source }));
    } catch (failure) {
      if (current === revision.current) {
        if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) { setDeniedRef(ref); setContent(null); setVerified({}); authorityLost.current?.(failure.message); }
        setError(failure instanceof Error ? failure.message : "原快照正文暂不可读");
      }
    }
    finally { if (current === revision.current) { readLock.current = false; setReading(false); } }
  }
  if (!references.length) return null;
  if (deniedRef) return <div className="space-y-2 text-xs">{error && <p role="alert" className="text-destructive">{error}</p>}<p>当前引用权限需重新核对，已隐藏原资料。</p><Button type="button" variant="outline" size="sm" disabled={reading} onClick={() => void read(deniedRef)}>重新核对引用权限</Button></div>;
  return <div className="space-y-2 text-xs">
    <ul className="space-y-2">{references.map(ref => {
      const source = verified[referenceKey(ref)];
      return <li key={`${ref.ref_id}:${ref.digest}`} className="break-words"><p>{source?.name ?? "历史来源快照"} · {new Date(ref.as_of).toLocaleString()}{!source ? " · 来源质量尚未核对" : ""}{source?.source_version ? ` · 来源版本 ${source.source_version}` : source ? " · 来源未标版本" : ""}{source ? ` · ${source.taint}` : ""}{source?.is_stale ? " · 已陈旧" : ""}{source?.superseded ? " · 有新版，当前仍引用原快照" : ""}{source?.has_conflict ? " · 有冲突" : ""}</p><Button type="button" variant="link" size="sm" className="px-0" disabled={reading} onClick={() => void read(ref)}>查看此引用的原快照</Button>{source?.url && /^https?:\/\//i.test(source.url) && <a className="ml-3 inline-flex min-h-9 items-center underline" href={source.url} target="_blank" rel="noreferrer">打开来源网页</a>}</li>;
    })}</ul>
    {reading && <div className="flex items-center gap-2"><p role="status">正在读取引用的原快照…</p><Button type="button" size="sm" variant="ghost" onClick={() => { revision.current += 1; readLock.current = false; setReading(false); setContent(null); setError(""); }}>取消读取原快照</Button></div>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {content && <section className="space-y-2 rounded-md border bg-background p-3"><div className="flex items-center justify-between gap-2"><h5 className="font-medium">引用的原快照正文</h5><Button type="button" variant="ghost" size="sm" onClick={() => setContent(null)}>收起原快照</Button></div><details className="text-xs text-muted-foreground"><summary className="cursor-pointer">技术核对</summary><p className="mt-2 break-all">快照：{content.snapshot_id}<br/>完整性摘要：{content.content_digest}</p></details><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm">{content.content}</pre></section>}
  </div>;
}
